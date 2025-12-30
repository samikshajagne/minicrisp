import os
from dotenv import load_dotenv
load_dotenv()

import asyncio
import threading
import logging
from pymongo.errors import DuplicateKeyError
import time
from datetime import datetime, timezone, timedelta # Added timedelta
from database import mark_customer_read, create_user, get_user_by_email # Added auth helpers
from passlib.context import CryptContext # Added
from jose import jwt, JWTError # Added
from fastapi.security import OAuth2PasswordBearer # Added
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Response, Depends, status, Form, UploadFile, File
import json # Added Form, Depends, status
import os
try:
    from groq import Groq
except ImportError:
    Groq = None
try:
    import google.generativeai as genai
except ImportError:
    genai = None
from fastapi import FastAPI, WebSocket, Request, BackgroundTasks, WebSocketDisconnect, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from database import ensure_customer, get_customer_by_email
from database import get_email_accounts, add_email_account, fs
from bson import ObjectId
# DB
from database import email_received, ensure_customer

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

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

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


def insert_message(sender, text, visitor_email, guest_id=None, origin="chat", message_id=None, timestamp=None, attachments=None, account_email=None, html_content=None, subject=None, cc=None, bcc=None):
    if not visitor_email:
        return

    visitor_email = visitor_email.lower().strip()

    # Allow ALL origins to create customers (User Request: "read all mails... show as chats")
    cust = ensure_customer(visitor_email)
    tb1_id = cust["tb1_id"]

    
    now = timestamp or datetime.now(timezone.utc)

    doc = {
        "tb1_id": tb1_id,
        "email": visitor_email,
        "content": text,
        "sender": sender,
        "source": origin,   # "chat" or "email" or "imap"
        "timestamp": now,
        "seen_at": None,
        "attachments": attachments or [],
        "account_email": account_email,
        "html_content": html_content,
        "subject": subject,
        "cc": cc or [],
        "bcc": bcc or []
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
        "email": visitor_email,
        "timestamp": now.isoformat(),
        "timestamp": now.isoformat(),
        "attachments": attachments or [],
        "html_content": html_content
    }

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast(visitor_email, guest_id, payload))
    except RuntimeError:
        # No running loop (e.g., script execution or background thread without loop)
        pass # Broadcast not critical for sync scripts

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
                {"email": regex}
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
        
    cursor = email_received.find(query).sort("timestamp", -1)

    for m in cursor:
        tb1_id = m["tb1_id"]

        # Filter by search results
        if relevant_tb1_ids is not None:
             if tb1_id not in relevant_tb1_ids:
                 continue

        # ONLY keep latest message per customer
        if tb1_id not in conversations:
            customer = ensure_customer(m["email"])

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
    visitor_email: str = Form(...),
    text: str = Form(...),
    account_email: str | None = Form(None),
    subject: str | None = Form(None),
    html_content: str | None = Form(None),
    cc: str | None = Form(None),
    bcc: str | None = Form(None),
    files: list[UploadFile] = File(None)
):
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
            visitor_email, 
            account_email=account_email,
            html_content=html_content,
            subject=subject,
            cc=cc_list,
            bcc=bcc_list,
            attachments=attachments_metadata
        )
        
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

        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
             return {"status": "error", "message": "GROQ_API_KEY missing. Please set it in .env"}
        
        if not Groq:
             return {"status": "error", "message": "groq library not installed."}

        client = Groq(api_key=api_key)
        
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a professional email assistant. Return ONLY the HTML body of the email (using p, br, ul tags). No <html> or <body> tags. No subject line. Just the body."},
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.7,
            max_tokens=1024,
            stream=False,
        )
        
        content = completion.choices[0].message.content
        return {"status": "ok", "content": content}
    except Exception as e:
        logger.error(f"Groq Generation Error: {e}")
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
        initial_emails = fetch_emails(criteria="ALL")
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

threading.Thread(target=gmail_sync_loop, daemon=True).start()

# -----------------------------
# Start server
# -----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
