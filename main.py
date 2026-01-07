import os
import asyncio
import threading
import logging
import json
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Response, Depends, status, Form, UploadFile, File
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordBearer
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from database import (
    mark_customer_read, create_user, get_user_by_email, ensure_customer, 
    email_received, fs, whatsapp_accounts, get_email_accounts, add_email_account,
    search_customers, customers
)
from whatsapp_service import verify_webhook, process_whatsapp_payload, send_whatsapp_text
from email_service import (
    send_admin_and_customer_notifications,
    send_reply_from_admin_to_customer,
    forward_visitor_message_to_admin
)
from gmail_reader import fetch_emails, test_credentials

try:
    from groq import Groq
except ImportError:
    Groq = None
try:
    import google.generativeai as genai
except ImportError:
    genai = None
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None
# DB
from database import email_received, ensure_customer

print("DEBUG: main.py is loading...")
print(f"DEBUG: OPENAI_API_KEY present: {bool(os.environ.get('OPENAI_API_KEY'))}")

# Email services
from email_service import (
    send_admin_and_customer_notifications,
    send_reply_from_admin_to_customer,
    forward_visitor_message_to_admin
)

# Gmail reader
from gmail_reader import fetch_emails, test_credentials

logger = logging.getLogger("main")
logger.setLevel(logging.INFO)
# Add file handler for debug
fh = logging.FileHandler("debug_log.txt")
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    # Start sync thread
    thread = threading.Thread(target=gmail_sync_loop, daemon=True)
    thread.start()
    yield
    # Shutdown logic if needed

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# -----------------------------
# WhatsApp Webhook
# -----------------------------

@app.get("/webhook/whatsapp")
async def whatsapp_webhook_verify(request: Request):
    """Meta webhook verification endpoint."""
    params = request.query_params
    hub_mode = params.get("hub.mode")
    hub_token = params.get("hub.verify_token")
    hub_challenge = params.get("hub.challenge")
    
    challenge = verify_webhook(hub_mode, hub_token, hub_challenge)
    if challenge is not None:
        return Response(content=str(challenge), media_type="text/plain")
    return Response(content="Verification failed", status_code=403)

@app.post("/webhook/whatsapp")
async def whatsapp_webhook_receive(request: Request):
    """WhatsApp message receiver endpoint with Automated Discovery."""
    try:
        payload = await request.json()
        # Log raw payload pretty-printed for senior-level debugging
        logger.info("--- Incoming WhatsApp Webhook ---")
        logger.info(json.dumps(payload, indent=2))
        
        data = process_whatsapp_payload(payload)
        if data:
            # --- Automated Discovery Logic ---
            # Capture phone_number_id and display_phone_number ONLY from webhook
            business_id = data["business_number_id"]
            display_num = data["display_phone_number"]
            
            if business_id:
                from database import whatsapp_accounts
                # Persistent record for routing, even if access_token is missing initially
                whatsapp_accounts.update_one(
                    {"phone_number_id": business_id},
                    {"$set": {
                        "phone_number_id": business_id,
                        "display_phone_number": display_num,
                        "last_seen_webhook": datetime.now(timezone.utc)
                    }},
                    upsert=True
                )
            # ----------------------------------

            insert_message(
                sender="visitor",
                text=data["text"],
                visitor_phone=data["visitor_phone"],
                origin="whatsapp",
                message_id=data["message_id"],
                timestamp=data["timestamp"],
                business_number_id=business_id
            )
            
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return {"status": "error", "message": str(e)}

# -----------------------------
# Security / Auth Config
# -----------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "supersecretkey") # Change this in production!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login") # Not strictly used with cookies but good for docs

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        # Remove "Bearer " if present (though we set cookie directly)
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
    except JWTError:
        return None
    return email

def login_required(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
    return user

MAIN_LOOP = None

# -----------------------------
# WebSocket connections
# -----------------------------
CONNECTIONS = {}

def visitor_key(email, guest_id):
    return email or guest_id


async def broadcast(email, guest_id, payload):
    key = visitor_key(email, guest_id)
    if not key:
        return

    for ws in CONNECTIONS.get(key, set()).copy():
        try:
            await ws.send_json(payload)
        except:
            CONNECTIONS[key].discard(ws)

# -----------------------------
# Insert message (SINGLE SOURCE)
# -----------------------------


def insert_message(sender, text, visitor_email=None, guest_id=None, origin="chat", message_id=None, timestamp=None, attachments=None, account_email=None, html_content=None, subject=None, cc=None, bcc=None, visitor_phone=None, business_number_id=None):
    if not visitor_email and not visitor_phone:
        return

    # Normalize data
    visitor_email = visitor_email.lower().strip() if visitor_email else None
    
    # Identify/Create customer
    cust = ensure_customer(email=visitor_email, phone=visitor_phone)
    tb1_id = cust["tb1_id"]
    
    # Use phone as identifier if email is missing (for UI consistency)
    display_identifier = visitor_email or visitor_phone
    
    now = timestamp or datetime.now(timezone.utc)

    doc = {
        "tb1_id": tb1_id,
        "email": display_identifier, # Keep as 'email' field for dashboard compatibility, but can be phone
        "content": text,
        "sender": sender,
        "source": origin,   # "chat", "email", "imap", "whatsapp"
        "timestamp": now,
        "seen_at": None,
        "attachments": attachments or [],
        "account_email": account_email,
        "html_content": html_content,
        "subject": subject,
        "cc": cc or [],
        "bcc": bcc or [],
        "visitor_phone": visitor_phone,
        "business_number_id": business_number_id
    }
    if message_id:
        doc["message_id"] = message_id

    try:
        email_received.insert_one(doc)
    except DuplicateKeyError:
        return # Skip duplicates silently

    payload = {
        "sender": sender,
        "text": text,
        "email": display_identifier,
        "timestamp": now.isoformat(),
        "attachments": attachments or [],
        "html_content": html_content,
        "source": origin
    }

    try:
        if MAIN_LOOP and MAIN_LOOP.is_running():
            asyncio.run_coroutine_threadsafe(broadcast(display_identifier, guest_id, payload), MAIN_LOOP)
        else:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcast(display_identifier, guest_id, payload))
    except RuntimeError:
        pass

# -----------------------------
# Models
# -----------------------------
class Message(BaseModel):
    text: str
    email: str
    guest_id: str | None = None


class AdminReply(BaseModel):
    text: str
    visitor_email: str
    account_email: str | None = None
    subject: str | None = None
    html_content: str | None = None
    cc: list[str] | None = None
    bcc: list[str] | None = None

# -----------------------------
# Routes
# -----------------------------
# -----------------------------
# Routes
# -----------------------------

# --- Auth Routes ---

@app.get("/signup")
async def get_signup(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@app.post("/signup")
async def post_signup(request: Request, email: str = Form(...), password: str = Form(...), confirm_password: str = Form(...)):
    if password != confirm_password:
        return templates.TemplateResponse("signup.html", {"request": request, "error": "Passwords do not match"})
    
    existing_user = get_user_by_email(email)
    if existing_user:
        return templates.TemplateResponse("signup.html", {"request": request, "error": "Email already registered"})
    
    hashed_pw = get_password_hash(password)
    create_user(email, hashed_pw)
    
    # Auto login or redirect
    return Response(status_code=302, headers={"Location": "/login"})

@app.get("/login")
async def get_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def post_login(request: Request, email: str = Form(...), password: str = Form(...)):
    with open("debug_login.txt", "a") as f:
        f.write(f"Login attempt for {email}\n")
    
    user = get_user_by_email(email)
    
    if user:
        is_valid = verify_password(password, user["password_hash"])
        with open("debug_login.txt", "a") as f:
            f.write(f"User found: Yes, Password valid: {is_valid}\n")
    else:
        is_valid = False
        with open("debug_login.txt", "a") as f:
            f.write("User found: No\n")

    if not user or not is_valid:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})
    
    access_token = create_access_token(data={"sub": user["email"]})
    
    with open("debug_login.txt", "a") as f:
        f.write("Token created, redirecting...\n")
        
    response = Response(status_code=302, headers={"Location": "/admin"})
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response

@app.get("/logout")
async def logout(request: Request):
    response = Response(status_code=302, headers={"Location": "/login"})
    response.delete_cookie("access_token")
    return response

# --- App Routes ---

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/admin")
async def admin(request: Request, user: str = Depends(login_required)):
    return templates.TemplateResponse("admin.html", {"request": request, "user": user})

@app.get("/whatsapp")
async def whatsapp_dashboard(request: Request, user: str = Depends(login_required)):
    return templates.TemplateResponse("whatsapp.html", {"request": request, "user": user})

# -----------------------------
# ✅ ADMIN INBOX (CUSTOMERS ONLY)
# -----------------------------
@app.get("/api/admin/messages")
async def api_admin_messages(
    user: str = Depends(login_required),
    search: str | None = None, 
    account: str | None = None, 
    start_date: str | None = None, 
    end_date: str | None = None, 
    has_attachments: bool = False, 
    source: str | None = None
):
    conversations = {}

    # 1. Identify relevant customers if search is active
    relevant_tb1_ids = None
    if search:
        relevant_tb1_ids = set()
        regex = {"$regex": search, "$options": "i"}
        # Find messages matching content OR email
        matched = email_received.find({
            "$or": [
                {"content": regex},
                {"html_content": regex},
                {"subject": regex},
                {"email": regex},
                {"cc": regex},
                {"bcc": regex}
            ]
        }, {"tb1_id": 1})
        for m in matched:
            relevant_tb1_ids.add(m["tb1_id"])
        
        # If no matches found, return empty early
        if not relevant_tb1_ids:
            return {"messages": []}

    # 2. Fetch latest message for each customer (standard logic)
    # Fetch ALL sources (chat, imap, email)
    query = {}
    if account:
        query["account_email"] = account.lower().strip()
    
    # Date Filtering
    date_filter = {}
    if start_date:
        try:
            # Assume YYYY-MM-DD from frontend
            sd = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            date_filter["$gte"] = sd
        except ValueError:
            pass
    
    if end_date:
        try:
            # End of the selected day
            ed = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            date_filter["$lte"] = ed
        except ValueError:
            pass

    if date_filter:
        query["timestamp"] = date_filter
    
    # New Filters
    if has_attachments:
        query["attachments"] = {"$exists": True, "$ne": []}
    
    if source and source != "all":
        query["source"] = source.lower()
    elif not source:
        # Default for Email Dashboard: exclude whatsapp
        query["source"] = {"$ne": "whatsapp"}
        
    # Limit search to avoid hanging if there are thousands of messages
    # We still fetch ALL unique conversations eventually, but we sort by newest first
    cursor = email_received.find(query).sort("timestamp", -1)

    for m in cursor:
        tb1_id = m["tb1_id"]

        # Filter by search results
        if relevant_tb1_ids is not None:
             if tb1_id not in relevant_tb1_ids:
                 continue

        # ONLY keep latest message per customer
        if tb1_id not in conversations:
            # OPTIMIZATION: Do not update 'last_seen' writing into DB during a simple list fetch
            customer = ensure_customer(m["email"], refresh_last_seen=False)

            last_read = customer.get("last_read_at")
            unread = email_received.count_documents({
                "tb1_id": tb1_id,
                "sender": "visitor",
                **({"timestamp": {"$gt": last_read}} if last_read else {})
            })

            conversations[tb1_id] = {
                "email": m["email"],
                "last_message": m["content"],
                "timestamp": m["timestamp"].isoformat(),
                "unread": unread,
                "attachments": m.get("attachments", []),
                "html_content": m.get("html_content")
            }

    return {"messages": list(conversations.values())}

@app.get("/api/admin/email-accounts")
async def get_accounts():
    accounts = get_email_accounts()
    
    # Legacy/Env Account Support (matches gmail_reader.py logic)
    import os
    env_email = os.environ.get("IMAP_EMAIL", "ai.intern@cetl.in").lower()
    
    # Check if already in DB
    if not any(a["email"] == env_email for a in accounts):
        accounts.append({
            "email": env_email,
            "imap_host": "imap.gmail.com",
            "active": True,
            "source": "env"
        })
        
    return {"accounts": accounts}

@app.post("/api/admin/email-accounts")
async def add_account(payload: dict, response: Response):
    # Sanitize password (remove spaces)
    if "app_password" in payload:
        payload["app_password"] = payload["app_password"].replace(" ", "")
    
    # Verify Credentials
    email = payload.get("email")
    pwd = payload.get("app_password")
    host = payload.get("imap_host", "imap.gmail.com")
    
    is_valid, error_msg = test_credentials(email, pwd, host)
    
    if not is_valid:
        response.status_code = 400
        return {"status": "error", "message": error_msg}

    add_email_account(payload)
    return {"status": "ok"}

@app.post("/api/admin/whatsapp-accounts")
async def add_whatsapp_account_api(payload: dict, user: str = Depends(login_required)):
    from database import add_whatsapp_account
    
    phone_number_id = payload.get("phone_number_id")
    access_token = payload.get("access_token")
    display_phone_number = payload.get("display_phone_number")
    
    if not phone_number_id or not access_token:
        raise HTTPException(status_code=400, detail="phone_number_id and access_token are required")
        
    add_whatsapp_account(phone_number_id, access_token, display_phone_number or phone_number_id)
    return {"status": "ok"}

@app.get("/api/admin/whatsapp-accounts")
async def get_whatsapp_accounts_api(user: str = Depends(login_required)):
    from database import get_whatsapp_accounts
    return {"accounts": get_whatsapp_accounts()}

@app.delete("/api/admin/whatsapp-accounts/{phone_number_id}")
async def delete_whatsapp_account_api(phone_number_id: str, user: str = Depends(login_required)):
    from database import whatsapp_accounts
    whatsapp_accounts.delete_one({"phone_number_id": phone_number_id})
    return {"status": "ok"}

def run_full_sync():
    try:
        logging.info("Starting MANUAL full sync...")
        results = fetch_emails(criteria="ALL")
        for r in results:
            insert_message(r["sender"], r["body"], r["visitor"], origin=r["source"], message_id=r.get("message_id"), timestamp=r.get("timestamp"), attachments=r.get("attachments"), account_email=r.get("account_email"), html_content=r.get("html_content"))
        logging.info("Manual full sync complete.")
    except Exception as e:
        logger.error(f"Manual sync error: {e}")

@app.post("/api/admin/resync")
async def api_resync(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_full_sync)
    return {"status": "ok", "message": "Sync started in background"}


@app.post("/api/admin/mark-read")
async def api_mark_read(payload: dict):
    email = payload.get("email")
    if email:
        mark_customer_read(email)
    return {"status": "ok"}


# -----------------------------
# Chat sync (per customer)
# -----------------------------
@app.get("/api/sync")
async def api_sync(email: str, start_date: str | None = None, end_date: str | None = None):
    email = email.lower().strip()

    query = {"email": email}
    
    # Date Filtering
    date_filter = {}
    if start_date:
        try:
            # Assume YYYY-MM-DD from frontend
            sd = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            date_filter["$gte"] = sd
        except ValueError:
            pass
    
    if end_date:
        try:
            # End of the selected day
            ed = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            date_filter["$lte"] = ed
        except ValueError:
            pass

    if date_filter:
        query["timestamp"] = date_filter

    msgs = []
    for m in email_received.find(query):
        msgs.append({
            "sender": m.get("sender", "visitor"),
            "text": m["content"],
            "text": m["content"],
            "timestamp": m["timestamp"].isoformat(),
            "text": m["content"],
            "timestamp": m["timestamp"].isoformat(),
            "attachments": m.get("attachments", []),
            "html_content": m.get("html_content")
        })

    msgs.sort(key=lambda x: x["timestamp"])
    return {"messages": msgs}

@app.get("/api/export")
async def api_export(email: str):
    email = email.lower().strip()
    
    # Reuse sync logic to get messages
    msgs = []
    for m in email_received.find({"email": email}):
        msgs.append({
            "sender": m.get("sender", "visitor"),
            "text": m["content"],
            "timestamp": m["timestamp"]
        })
    msgs.sort(key=lambda x: x["timestamp"])

    # Build Transcript
    lines = []
    lines.append(f"Conversation Log: {email}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("-" * 50)
    lines.append("")

    for m in msgs:
        ts_str = m["timestamp"].strftime("%Y-%m-%d %H:%M")
        sender = m["sender"].upper()
        lines.append(f"[{ts_str}] {sender}:")
        lines.append(f"{m['text']}")
        lines.append("")
    
    content = "\n".join(lines)
    
    content = "\n".join(lines)
    
    filename = f"chat_{email.replace('@','_').replace('.','_')}.txt"
    return PlainTextResponse(content, headers={
        "Content-Disposition": f"attachment; filename={filename}"
    })

@app.get("/api/attachments/{file_id}")
async def get_attachment_file(file_id: str):
    try:
        grid_out = fs.get(ObjectId(file_id))
        return StreamingResponse(
            grid_out, 
            media_type=grid_out.content_type or "application/octet-stream",
            headers={"Content-Disposition": f"inline; filename={grid_out.filename}"}
        )
    except Exception:
        return Response(status_code=404)

# -----------------------------
# Visitor sends message
# -----------------------------
@app.post("/api/message")
async def api_message(msg: Message):
    insert_message("visitor", msg.text, msg.email, msg.guest_id)
    send_admin_and_customer_notifications(msg.email, msg.text)
    return {"status": "ok"}

# -----------------------------
# Admin replies
# -----------------------------
@app.post("/api/reply")
async def api_reply(
    background_tasks: BackgroundTasks,
    visitor_email: str = Form(...),
    text: str = Form(...),
    account_email: str | None = Form(None),
    subject: str | None = Form(None),
    html_content: str | None = Form(None),
    cc: str | None = Form(None),
    bcc: str | None = Form(None),
    files: Optional[List[UploadFile]] = File(None)
):
    logger.info(f"api_reply called: visitor={visitor_email}, account={account_email}, text_len={len(text)}")
    try:
        # Parse CC/BCC if they come as JSON strings or plain text
        cc_list = []
        if cc:
            try:
                parsed = json.loads(cc)
                if isinstance(parsed, list):
                    cc_list = parsed
                else:
                    cc_list = [str(parsed)]
            except json.JSONDecodeError:
                cc_list = [e.strip() for e in cc.split(",") if e.strip()]

        bcc_list = []
        if bcc:
            try:
                parsed = json.loads(bcc)
                if isinstance(parsed, list):
                    bcc_list = parsed
                else:
                    bcc_list = [str(parsed)]
            except json.JSONDecodeError:
                bcc_list = [e.strip() for e in bcc.split(",") if e.strip()]

        # Process Attachments
        attachments_for_email = []
        attachments_metadata = []

        if files:
            for file in files:
                content = await file.read()
                # 1. Save to GridFS
                file_id = fs.put(content, filename=file.filename, content_type=file.content_type)
                
                # 2. Metadata for DB
                attachments_metadata.append({
                    "id": str(file_id),
                    "url": f"/api/attachments/{file_id}",
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "size": len(content)
                })

                # 3. Data for Email Service
                attachments_for_email.append({
                    "filename": file.filename,
                    "content": content,
                    "content_type": file.content_type
                })

        insert_message(
            "admin", 
            text, 
            visitor_email if "@" in visitor_email else None,
            visitor_phone=None if "@" in visitor_email else visitor_email,
            account_email=account_email,
            html_content=html_content,
            subject=subject,
            cc=cc_list,
            bcc=bcc_list,
            attachments=attachments_metadata,
            origin="email" if "@" in visitor_email else "whatsapp"
        )
        
        if "@" in visitor_email:
            send_reply_from_admin_to_customer(
                visitor_email, 
                text, 
                account_email=account_email,
                html_content=html_content,
                subject=subject,
                cc=cc_list,
                bcc=bcc_list,
                attachments=attachments_for_email
            )
        else:
            # Routing to WhatsApp
            # In this case, 'visitor_email' actually contains the phone number
            # We prioritize account_email (which will be business_number_id) if provided
            business_id = account_email if account_email and "@" not in account_email else None
            
            if not business_id:
                # Fallback: Find which business number received the LAST message in this thread
                last_msg = email_received.find_one({"visitor_phone": visitor_email, "source": "whatsapp"}, sort=[("timestamp", -1)])
                business_id = last_msg.get("business_number_id") if last_msg else None
            
            if business_id:
                background_tasks.add_task(send_whatsapp_text, business_id, visitor_email, text)
            else:
                logger.error(f"Could not find business_number_id for WhatsApp reply to {visitor_email}")

        return {"status": "ok"}
    except Exception as e:
        logger.exception(f"API Reply Error: {e}")
        # Return 500 with detail so frontend can see it (optional, but good for us)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/seen")
async def mark_seen(payload: dict):
    email = payload.get("email")
    if not email:
        return {"status": "error"}

    email_received.update_many(
        {"email": email, "sender": "admin", "seen_at": None},
        {"$set": {"seen_at": datetime.utcnow()}}
    )
    return {"status": "ok"}


# -----------------------------
# WebSocket
# -----------------------------
@app.websocket("/ws")
async def websocket_handler(
    ws: WebSocket,
    email: str | None = None,
    guest_id: str | None = None
):
    key = visitor_key(email, guest_id)
    if not key:
        await ws.close()
        return

    await ws.accept()
    CONNECTIONS.setdefault(key, set()).add(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        CONNECTIONS[key].discard(ws)

# -----------------------------
# AI Email Generation
# -----------------------------
@app.post("/api/generate-email")
async def generate_email(request: Request):
    try:
        data = await request.json()
        prompt_text = data.get("prompt")
        if not prompt_text:
            raise HTTPException(status_code=400, detail="Prompt required")

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
             return {"status": "error", "message": "GEMINI_API_KEY missing. Please set it in .env"}
        
        if not genai:
             return {"status": "error", "message": "google-generativeai library not installed."}
        
        genai.configure(api_key=api_key)
        model_name = os.environ.get("GEMINI_MODEL_NAME", "gemini-1.5-flash")
        model = genai.GenerativeModel(model_name)
        
        system_instr = "You are a professional email assistant. Return ONLY the HTML body of the email (using p, br, ul tags). No <html> or <body> tags. No subject line. Just the body."
        
        response = model.generate_content(f"{system_instr}\n\nUser request: {prompt_text}")
        
        content = response.text.replace("```html", "").replace("```", "").strip()
        return {"status": "ok", "content": content}
    except Exception as e:
        logger.error(f"Gemini Generation Error: {e}")
        return {"status": "error", "message": str(e)}

# -----------------------------
# AI Agent (Gemini Tool Calling)
# -----------------------------

# Configure Gemini
api_key = os.environ.get("GEMINI_API_KEY")
if api_key and genai:
    genai.configure(api_key=api_key)

def get_emails_tool(query: str = None, start_date: str = None, end_date: str = None, account: str = None):
    """
    Search for emails/messages based on criteria.
    Dates should be in YYYY-MM-DD format.
    """
    filter_query = {}
    if account:
        filter_query["account_email"] = account.lower().strip()
    
    date_filter = {}
    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            date_filter["$gte"] = sd
        except: pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            date_filter["$lte"] = ed
        except: pass
    if date_filter:
        filter_query["timestamp"] = date_filter

    if query:
        filter_query["$or"] = [
            {"content": {"$regex": query, "$options": "i"}},
            {"email": {"$regex": query, "$options": "i"}},
            {"subject": {"$regex": query, "$options": "i"}}
        ]

    msgs = list(email_received.find(filter_query).sort("timestamp", -1).limit(10))
    results = []
    for m in msgs:
        results.append({
            "from": m["email"],
            "content": m["content"][:200] + "..." if len(m["content"]) > 200 else m["content"],
            "timestamp": m["timestamp"].isoformat(),
            "subject": m.get("subject", "No Subject")
        })
    return {
        "action": "fetch_emails", 
        "results": results, 
        "filter": {"query": query, "start": start_date, "end": end_date}
    }

def switch_admin_sender_account_view_tool(account_email: str):
    """
    CRITICAL: Switches WHICH admin account YOU are currently viewing/sending FROM.
    Use this ONLY when the user says 'switch to my other account' or 'switch view to [email]'.
    DO NOT use this to select a person to talk to.
    """
    return {"action": "switch_account", "account": account_email}

def open_chat_tool(email: str):
    """
    Open the conversation/chat with a specific RECIPIENT (visitor).
    Use this when the user picks a contact from a list or asks to see a specific person's messages.
    """
    return {"action": "open_chat", "email": email}

def send_email_tool(to: str, subject: str, body: str):
    """Send an email to a recipient."""
    # We'll use the first active account if none specified or we can ask for context
    # For now, we'll just trigger the send logic
    try:
        send_reply_from_admin_to_customer(to, body, subject=subject)
        insert_message("admin", body, to, subject=subject, origin="ai_agent")
        return {"status": "success", "message": f"Email sent to {to}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def search_customers_tool(query: str):
    """Search for customers by name, email, or phone in the database."""
    from database import search_customers
    results = search_customers(query)
    formatted = []
    for r in results:
        formatted.append({
            "name": r.get("name", "Unknown"),
            "email": r.get("cust_email") or r.get("phone") or "No Email/Phone",
            "phone": r.get("phone"),
            "last_seen": r.get("last_seen").isoformat() if r.get("last_seen") else None
        })
    return {"results": formatted}

def draft_reply_tool(email: str, body: str):
    """
    Draft a reply to a specific conversation. 
    This opens the composer and fills it with the suggested body, but does NOT send it.
    """
    return {"action": "draft_reply", "email": email, "body": body}

def get_inbox_stats_tool():
    """Get unread message counts across all email and WhatsApp sources."""
    from database import get_unread_count, get_email_accounts, get_whatsapp_accounts
    stats = {"unread_total": 0, "email_accounts": [], "whatsapp_accounts": []}
    all_customers = list(customers.find({"last_read_at": {"$exists": True}}))
    for cust in all_customers:
        stats["unread_total"] += get_unread_count(cust["tb1_id"])
    stats["email_accounts"] = [a["email"] for a in get_email_accounts()]
    stats["whatsapp_accounts"] = [a["display_phone_number"] for a in get_whatsapp_accounts()]
    return stats

def summarize_conversation_tool(email: str):
    """Fetch the last 10 messages for a conversation and return a summary."""
    cust = ensure_customer(email=email)
    if not cust: return "Customer not found."
    msgs = list(email_received.find({"tb1_id": cust["tb1_id"]}).sort("timestamp", -1).limit(10))
    if not msgs: return "No messages found."
    summary_data = []
    for m in reversed(msgs):
        summary_data.append(f"{m['sender']}: {m['content'][:100]}")
    return "\n".join(summary_data)

def compose_new_tool(to: str, subject: str = "", body: str = ""):
    """Open the composer for a new recipient (global email)."""
    return {"action": "compose_new", "to": to, "subject": subject, "body": body}

def confirm_and_send_action_tool():
    """Execute the final send action on the dashboard after user confirmation."""
    return {"action": "send_email"}

def sync_emails_tool():
    """Trigger a fresh manual resync of all email accounts to fetch latest messages."""
    return {"action": "sync_emails"}

def wait_tool(ms: int = 500):
    """Wait for a brief period (in milliseconds) for the UI to stabilize or background tasks to finish."""
    return {"action": "wait", "ms": ms}

def update_search_tool(query: str):
    """Type a query into the sidebar search box to filter conversations."""
    return {"action": "update_search", "query": query}

def navigate_tool(target: str):
    """Navigate to a dashboard section: 'whatsapp', 'inbox', 'add_account', 'resync', 'logout', 'filters'."""
    return {"action": "navigate", "target": target}

def clear_filters_tool():
    """Clear all active search and date filters in the sidebar."""
    return {"action": "clear_filters"}

def mark_read_tool(email: str):
    """Mark a specific conversation as read."""
    return {"action": "mark_read", "email": email}

def export_chat_tool(email: str):
    """Export the conversation with this email to a TXT file."""
    return {"action": "export_chat", "email": email}

@app.post("/api/ai/agent")
async def ai_agent(request: Request):
    if not genai:
        return {"status": "error", "message": "google-generativeai not installed"}
    
    data = await request.json()
    prompt = data.get("prompt")
    if not prompt:
        return {"status": "error", "message": "Prompt required"}

    try:
        def safe_get_text(resp):
            try:
                if resp.candidates and resp.candidates[0].content.parts:
                    for p in resp.candidates[0].content.parts:
                        if p.text: return p.text
            except: pass
            return "I've processed your request and performed the necessary actions on your dashboard."
    
        # Grounding: Get available accounts to inject into system prompt
        from database import get_email_accounts
        accounts_data = get_email_accounts()
        env_email = os.environ.get("IMAP_EMAIL", "ai.intern@cetl.in").lower()
        if not any(a["email"] == env_email for a in accounts_data):
            accounts_data.append({"email": env_email})
        account_list_str = ", ".join([a["email"] for a in accounts_data])

        model_name = os.environ.get("GEMINI_MODEL_NAME", "gemini-1.5-flash")
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=(
                "You are an OPERATOR for the Mini Crisp Admin UI. "
                "Your job is to EXECUTE ACTIONS using the provided tools. "
                "DO NOT narrate an action unless you have also emitted the corresponding TOOL CALL. "
                f"AVAILABLE SENDER ACCOUNTS: [{account_list_str}]. "
                "Rules:\n"
                "1. To switch the admin view, use 'switch_admin_sender_account_view_tool'.\n"
                "2. To open a chat with a visitor, use 'open_chat_tool'.\n"
                "3. Always use 'open_chat_tool' before 'draft_reply_tool'.\n"
                "4. Distinguish between switching YOUR account (sender) and opening a visitor chat (recipient)."
            ),
            tools=[
                get_emails_tool, switch_admin_sender_account_view_tool, send_email_tool,
                search_customers_tool, get_inbox_stats_tool, summarize_conversation_tool,
                compose_new_tool, navigate_tool, clear_filters_tool,
                mark_read_tool, export_chat_tool, draft_reply_tool,
                confirm_and_send_action_tool, open_chat_tool,
                sync_emails_tool, wait_tool, update_search_tool
            ]
        )
        
        chat = model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(prompt)
        
        # Check tool results for actions
        final_actions = []
        for msg in chat.history:
            for part in msg.parts:
                if part.function_response:
                    # Robust extraction for Gemini's complex protobuf-like objects
                    try:
                        # Convert MapComposite/RepeatedComposite to dict/list
                        def recursive_to_dict(obj):
                            if hasattr(obj, 'items'):
                                return {k: recursive_to_dict(v) for k, v in obj.items()}
                            elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
                                return [recursive_to_dict(x) for x in obj]
                            else:
                                return obj
                                
                        res = recursive_to_dict(part.function_response.response)
                        
                        # Handle potential 'result' wrapper
                        if "result" in res:
                            res = res["result"]

                        if isinstance(res, dict):
                            if "action" in res:
                                final_actions.append(res)
                            elif "results" in res:
                                final_actions.append({"action": "search_customers", "results": res["results"]})
                    except Exception as e:
                        print(f"Error parsing tool response: {e}")

        return {
            "status": "ok",
            "response": safe_get_text(response),
            "actions": final_actions
        }
    except Exception as e:
        logger.exception("AI Agent Error")
        return {"status": "error", "message": str(e)}

# -----------------------------
# AI Assistant (Gemini Autonomous Agent)
# -----------------------------

@app.post("/api/ai/command")
async def ai_command(request: Request):
    if not genai:
        return {"status": "error", "message": "google-generativeai not installed"}
    
    # Reload env to pick up latest API key
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"status": "error", "message": "GEMINI_API_KEY missing in .env"}
    
    genai.configure(api_key=api_key)
    
    data = await request.json()
    text = data.get("text")
    if not text:
        return {"status": "error", "message": "No command provided"}

    try:
        # Grounding: Get available accounts to inject into system prompt
        accounts_data = get_email_accounts()
        env_email = os.environ.get("IMAP_EMAIL", "ai.intern@cetl.in").lower()
        if not any(a["email"] == env_email for a in accounts_data):
            accounts_data.append({"email": env_email})
        account_list_str = ", ".join([a["email"] for a in accounts_data])

        def safe_get_text(resp):
            try:
                if resp.candidates and resp.candidates[0].content.parts:
                    for part in resp.candidates[0].content.parts:
                        if part.text:
                            return part.text
            except: pass
            return "Request handled. I've updated the dashboard according to your instructions."

        # We use the same model config as ai_agent for consistency and power
        model_name = os.environ.get("GEMINI_MODEL_NAME", "gemini-1.5-flash")
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=(
                "You are an OPERATOR for the Mini Crisp Admin UI. "
                "Your job is to EXECUTE ACTIONS using the provided tools. "
                "DO NOT narrate an action unless you have also emitted the corresponding TOOL CALL. "
                f"AVAILABLE SENDER ACCOUNTS: [{account_list_str}]. "
                "Rules:\n"
                "1. To switch the admin view, use 'switch_admin_sender_account_view_tool'.\n"
                "2. To open a chat with a visitor, use 'open_chat_tool'.\n"
                "3. Always use 'open_chat_tool' before 'draft_reply_tool'.\n"
                "4. Distinguish between switching YOUR account (sender) and opening a visitor chat (recipient)."
            ),
            tools=[
                get_emails_tool, switch_admin_sender_account_view_tool, send_email_tool,
                search_customers_tool, get_inbox_stats_tool, summarize_conversation_tool,
                compose_new_tool, navigate_tool, clear_filters_tool,
                mark_read_tool, export_chat_tool, draft_reply_tool,
                confirm_and_send_action_tool, open_chat_tool,
                sync_emails_tool, wait_tool, update_search_tool
            ]
        )
        
        chat = model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(text)
        
        # Collect any "action" dicts returned by tools to pass to frontend
        result_actions = []
        for msg in chat.history:
            for part in msg.parts:
                if part.function_response:
                    # Robust extraction for Gemini's complex protobuf-like objects
                    try:
                        # Convert MapComposite/RepeatedComposite to dict/list
                        def recursive_to_dict(obj):
                            if hasattr(obj, 'items'):
                                return {k: recursive_to_dict(v) for k, v in obj.items()}
                            elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
                                return [recursive_to_dict(x) for x in obj]
                            else:
                                return obj
                                
                        res = recursive_to_dict(part.function_response.response)
                        
                        # Handle potential 'result' wrapper
                        if "result" in res:
                            res = res["result"]

                        if isinstance(res, dict):
                            if "action" in res:
                                result_actions.append(res)
                            elif "results" in res:
                                result_actions.append({"action": "search_customers", "results": res["results"]})
                    except Exception as e:
                        print(f"Error parsing tool response: {e}")
        
        # DEBUG LOGGING
        try:
            with open("ai_actions_debug.log", "a", encoding="utf-8") as f:
                 f.write(f"PROMPT: {text}\n")
                 f.write(f"HISTORY DUMP: {chat.history}\n")
                 f.write(f"ACTIONS DETECTED: {result_actions}\n-------------------\n")
        except Exception as e:
            print(f"Log error: {e}")

        return {
            "status": "ok",
            "response": safe_get_text(response),
            "actions": result_actions
        }
    except Exception as e:
        logger.exception("AI Command Error")
        return {"status": "error", "message": str(e)}

# -----------------------------
# Gmail sync (SAFE)
# -----------------------------
def gmail_sync_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 1. Backfill history (fetch ALL) - run once on startup
    try:
        logging.info("Starting initial email backfill...")
        # Optimization: Only backfill last 7 days initially to avoid hanging on massive inboxes
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        initial_emails = fetch_emails(criteria=f'(SINCE "{seven_days_ago}")')
        for r in initial_emails:
            insert_message(r["sender"], r["body"], r["visitor"], origin=r["source"], message_id=r.get("message_id"), timestamp=r.get("timestamp"), attachments=r.get("attachments"), account_email=r.get("account_email"), html_content=r.get("html_content"))
        logging.info("Initial backfill complete.")
    except Exception as e:
        logger.error(f"Backfill error: {e}")

    while True:
        try:
            # 2. Continuous sync (fetch UNSEEN)
            replies = fetch_emails(criteria="UNSEEN")

            for r in replies:
                sender = r["sender"]
                body = r["body"]
                email = r["visitor"]

                # Gmail replies ALSO mapped to customer
                insert_message(sender, body, email, origin=r["source"], message_id=r.get("message_id"), timestamp=r.get("timestamp"), attachments=r.get("attachments"), account_email=r.get("account_email"), html_content=r.get("html_content"))

                if sender == "visitor":
                    forward_visitor_message_to_admin(email, body)
                else:
                    send_reply_from_admin_to_customer(email, body)

        except Exception as e:
            logger.error(f"Gmail sync error: {e}")

        time.sleep(1)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
 
