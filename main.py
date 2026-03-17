import os
import sys
import asyncio
import websockets
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
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordBearer
from bson import ObjectId
from pymongo.errors import DuplicateKeyError



from database import (
    mark_customer_read, create_user, get_user_by_email, ensure_customer, 
    email_received, fs, whatsapp_accounts, get_email_accounts, get_whatsapp_accounts, add_email_account,
    get_social_accounts, add_social_account,
    search_customers, customers, add_note, get_notes, add_tag, get_tags, save_ai_interaction,
    get_recent_ai_history
)
from whatsapp_service import verify_webhook, process_whatsapp_payload, send_whatsapp_text, upload_media, send_whatsapp_media, download_media_bytes
import social_service
from email_service import (
    send_admin_and_customer_notifications,
    send_reply_from_admin_to_customer,
    forward_visitor_message_to_admin
)
from gmail_reader import fetch_emails, test_credentials, _strip_quoted_text
from summary_engine import generate_short_summary_txt, generate_detailed_summary_pdf
import map_router

try:
    from groq import Groq
except ImportError:
    Groq = None
try:
    import google.generativeai as genai
except ImportError:
    genai = None
api_key = os.environ.get("GEMINI_API_KEY")
if api_key and genai:
    genai.configure(api_key=api_key)
try:
    from openai import OpenAI
    import httpx
except ImportError:
    OpenAI = None
    httpx = None
# DB
from database import email_received, ensure_customer

try:
    from deepgram import AsyncDeepgramClient, DeepgramClient
    from deepgram.core import EventType
except ImportError:
    AsyncDeepgramClient = None
    DeepgramClient = None
    EventType = None

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

app.include_router(map_router.router)

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
async def meta_webhook_receive(request: Request):
    """Generic Meta message receiver (WhatsApp, Facebook, Instagram)."""
    try:
        payload = await request.json()
        logger.info("--- Incoming Meta Webhook ---")
        logger.info(json.dumps(payload, indent=2))
        
        # 1. Try WhatsApp
        data = process_whatsapp_payload(payload)
        if data:
            # WhatsApp Logic
            business_id = data["business_number_id"]
            display_num = data["display_phone_number"]
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

            attachments_metadata = []
            if data.get("attachments_info"):
                 # Fetch token to download media
                 wa_acc = whatsapp_accounts.find_one({"phone_number_id": business_id})
                 if wa_acc and wa_acc.get("access_token"):
                     for att in data["attachments_info"]:
                         content, mime = await download_media_bytes(att["whatsapp_id"], wa_acc["access_token"])
                         if content:
                             f_id = fs.put(content, filename=att["filename"], content_type=mime)
                             attachments_metadata.append({
                                 "id": str(f_id),
                                 "url": f"/api/attachments/{f_id}",
                                 "filename": att["filename"],
                                 "content_type": mime,
                                 "size": len(content)
                             })

            insert_message(
                sender="visitor",
                text=data["text"],
                visitor_phone=data["visitor_phone"],
                origin="whatsapp",
                message_id=data["message_id"],
                timestamp=data["timestamp"],
                business_number_id=business_id,
                account_email=business_id,  # Pass business_id as account identifier
                attachments=attachments_metadata
            )
        else:
            # 2. Try Facebook/Instagram
            data = social_service.process_social_payload(payload)
            if data:
                insert_message(
                    sender="visitor",
                    text=data["text"],
                    visitor_email=data["sender_id"], # Store sender_id as email/identifier
                    origin=data["platform"],
                    message_id=data["message_id"],
                    timestamp=data["timestamp"],
                    account_email=data["account_id"]
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
ADMIN_CONNECTIONS = set()

def visitor_key(email, guest_id):
    return email or guest_id


async def broadcast_to_admins(payload):
    for ws in ADMIN_CONNECTIONS.copy():
        try:
            await ws.send_json(payload)
        except:
            ADMIN_CONNECTIONS.discard(ws)

async def broadcast(email, guest_id, payload):
    key = visitor_key(email, guest_id)
    if not key:
        return

    for ws in CONNECTIONS.get(key, set()).copy():
        try:
            await ws.send_json(payload)
        except:
            CONNECTIONS[key].discard(ws)
    
    # Also notify global admins
    for ws in ADMIN_CONNECTIONS.copy():
        try:
            await ws.send_json({"type": "new_message", "payload": payload})
        except:
            ADMIN_CONNECTIONS.discard(ws)

def process_email_background_task(
    visitor_email, text, account_email, html_content, subject, cc, bcc, attachments, custom_message_id
):
    """
    Wrapper to run sync SMTP safely and update status on completion.
    """
    try:
        # Run the sync function (it might block, so we are in a threadpool via BackgroundTasks)
        res = send_reply_from_admin_to_customer(
            visitor_email, text, account_email, html_content, subject, cc, bcc, attachments, custom_message_id
        )
        
        success = res.get("success") if isinstance(res, dict) else res
        new_status = "sent" if success else "failed"
        
        # Update DB
        if custom_message_id:
            msg_id = custom_message_id.strip("<>")
            email_received.update_one(
                {"message_id": msg_id},
                {"$set": {"status": new_status}}
            )
            
            # Broadcast Status Update
            if MAIN_LOOP and MAIN_LOOP.is_running():
                 asyncio.run_coroutine_threadsafe(
                     broadcast_to_admins({"type": "message_status", "id": msg_id, "status": new_status}),
                     MAIN_LOOP
                 )

    except Exception as e:
        logger.error(f"Background Email Task Failed: {e}")
        # Mark as failed
        if custom_message_id:
             msg_id = custom_message_id.strip("<>")
             email_received.update_one(
                {"message_id": msg_id},
                {"$set": {"status": "failed"}}
            )

# -----------------------------
# Insert message (SINGLE SOURCE)
# -----------------------------


def insert_message(sender, text, visitor_email=None, guest_id=None, origin="chat", message_id=None, timestamp=None, attachments=None, account_email=None, html_content=None, subject=None, cc=None, bcc=None, visitor_phone=None, business_number_id=None, in_reply_to=None, sender_name=None):
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
        "conversation_id": cust.get("conversation_id"), # Persistent ID
        "sender": sender,
        "sender_name": sender_name,
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
        "business_number_id": business_number_id,
        "in_reply_to": in_reply_to
    }
    if message_id:
        doc["message_id"] = message_id
    
    # Status handling
    doc["status"] = "sent" # Default
    if origin == "email" and sender == "admin":
        doc["status"] = "sending" # Initial state for admin emails


    try:
        email_received.insert_one(doc)
    except DuplicateKeyError:
        # 1. Stop Future Duplicates: Enforce Idempotency
        # 2. Lock Sender: Never update 'sender' or 'source' (origin)
        # 3. Update Status/Metadata only
        
        update_fields = {}
        if doc.get("status") == "sent": 
             update_fields["status"] = "sent"  # IMAP confirmation updates 'sending' to 'sent'
        
        if doc.get("html_content"):
             update_fields["html_content"] = doc["html_content"]
             
        if doc.get("timestamp"):
             # Optional: Update timestamp if we prefer the latest sync time? 
             # Usually keep first. Let's skip timestamp update to preserve ordering.
             pass

        if update_fields:
            email_received.update_one(
                {"message_id": message_id},
                {"$set": update_fields}
            )
        return

    payload = {
        "sender": sender,
        "sender_name": sender_name,
        "text": text,
        "email": display_identifier,
        "timestamp": now.isoformat(),
        "attachments": attachments or [],
        "html_content": html_content,
        "source": origin,
        "account_email": account_email,
        "conversation_id": cust.get("conversation_id")
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

@app.get("/map-dashboard")
async def map_dashboard_view(request: Request):
    return templates.TemplateResponse("map_dashboard.html", {"request": request})

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
    source: str | None = None,
    since: str | None = None
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
            return {"messages": [], "server_time": datetime.now(timezone.utc).isoformat()}

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
        
    # Ensure customers collection is available
    from database import customers

    # --- INCREMENTAL SYNC LOGIC ---
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            # Logic: We need conversations where:
            # A) A new message arrived > since
            # OR
            # B) Customer metadata (tags) updated > since
            
            # Find updated customers
            updated_customers = list(customers.find({"updated_at": {"$gt": since_dt}}, {"tb1_id": 1}))
            updated_tb1_ids = [c["tb1_id"] for c in updated_customers]
            
            # Add timestamp condition to message query OR match updated customers
            # Complex query: (OriginalQuery AND MessageTimestamp > Since) OR (OriginalQuery AND tb1_id IN updated_ids)
            
            # Simpler approach: Fetch messages > since with original filters
            incremental_query = query.copy()
            incremental_query["timestamp"] = {"$gt": since_dt}
            # Note: If date_filter was set, we intersect.
            if date_filter:
                incremental_query["timestamp"] = {"$gt": since_dt, **date_filter}
                
            # Fetch messages
            cursor_msgs = list(email_received.find(incremental_query).sort("timestamp", -1))
            
            # Also fetch LATEST message for any customer whose tags updated, even if message is old
            if updated_tb1_ids:
                # We need the latest message for these customers to return the conversation object
                # But we must respect original filters (like account, source)
                meta_query = query.copy()
                meta_query["tb1_id"] = {"$in": updated_tb1_ids}
                cursor_meta = list(email_received.find(meta_query).sort("timestamp", -1))
                
                # Merge cursors (deduplicate by message_id or processed logic)
                # We feed 'cursor' to the loop below. 
                # Let's verify we don't process duplicates in 'conversations' dict logic
                cursor = cursor_msgs + cursor_meta
            else:
                cursor = cursor_msgs
            
        except ValueError:
            # Fallback to full sync if invalid date
            cursor = email_received.find(query).sort("timestamp", -1)
    else:
        # Full Sync
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
                "conversation_id": customer.get("conversation_id"), # Persistent ID for frontend key
                "email": m["email"],
                "name": customer.get("name") or m["email"], # Helpful for display
                "last_message": _strip_quoted_text(m["content"]) if m.get("content") else "",
                "timestamp": m["timestamp"].isoformat(),
                "unread": unread,
                "attachments": m.get("attachments", []),
                "html_content": m.get("html_content"),
                "source": m.get("source", "chat"),
                "tags": customer.get("tags", [])
            }

    return {
        "messages": list(conversations.values()),
        "server_time": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/admin/email-accounts")
async def get_accounts():
    accounts = get_email_accounts()
    
    # Legacy/Env Account Support (matches gmail_reader.py logic)
    import os
    env_email = os.environ.get("BOT_EMAIL", os.environ.get("IMAP_EMAIL", "ai.intern@cetl.in")).lower()
    
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

@app.get("/api/admin/social-accounts")
async def get_social_accounts_api(user: str = Depends(login_required)):
    return {"accounts": get_social_accounts()}

@app.post("/api/admin/social-accounts")
async def add_social_account_api(payload: dict, user: str = Depends(login_required)):
    account_id = payload.get("account_id")
    access_token = payload.get("access_token")
    platform = payload.get("platform")
    display_name = payload.get("display_name")
    
    if not account_id or not access_token or not platform:
        raise HTTPException(status_code=400, detail="account_id, access_token and platform are required")
        
    add_social_account(account_id, access_token, platform, display_name or account_id)
    return {"status": "ok"}

@app.delete("/api/admin/social-accounts/{account_id}")
async def delete_social_account_api(account_id: str, user: str = Depends(login_required)):
    from database import social_accounts
    social_accounts.delete_one({"account_id": account_id})
    return {"status": "ok"}

def run_full_sync():
    try:
        logging.info("Starting MANUAL full sync...")
        results = fetch_emails(criteria="ALL")
        for r in results:
            insert_message(r["sender"], r["body"], r["visitor"], origin=r["source"], message_id=r.get("message_id"), timestamp=r.get("timestamp"), attachments=r.get("attachments"), account_email=r.get("account_email"), html_content=r.get("html_content"), in_reply_to=r.get("in_reply_to"))
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


@app.post("/api/admin/move-conversation")
async def api_move_conversation(payload: dict, user: str = Depends(login_required)):
    conversation_id = payload.get("conversation_id")
    target = payload.get("target") # "inbox" or "notifications"
    
    if not conversation_id or not target:
        return {"status": "error", "message": "Missing conversation_id or target"}
    
    # Logic: Toggle tags
    # If target is "notifications", add "notifications" tag, remove "inbox" tag
    # If target is "inbox", add "inbox" tag, remove "notifications" tag
    
    from database import customers
    
    # Audit Trail Entry
    audit_entry = {
         "action": "move_to_" + target,
         "performed_by": user,
         "timestamp": datetime.now(timezone.utc)
    }
    
    # Use aggregation pipeline for atomic update to avoid $addToSet/$pull conflict on same field
    pipeline = [
        {"$set": {
            "updated_at": datetime.now(timezone.utc),
            "tag_history": {"$concatArrays": [{"$ifNull": ["$tag_history", []]}, [audit_entry]]}
        }}
    ]

    if target == "notifications":
        # Remove 'inbox', Add 'notifications'
        pipeline.append({"$set": {"tags": {"$setDifference": [{"$ifNull": ["$tags", []]}, ["inbox"]]}}})
        pipeline.append({"$set": {"tags": {"$setUnion": ["$tags", ["notifications"]]}}})
    elif target == "inbox":
        # Remove 'notifications', Add 'inbox'
        pipeline.append({"$set": {"tags": {"$setDifference": [{"$ifNull": ["$tags", []]}, ["notifications"]]}}})
        pipeline.append({"$set": {"tags": {"$setUnion": ["$tags", ["inbox"]]}}})

    result = customers.update_one(
        {"conversation_id": conversation_id},
        pipeline
    )
    
    if result.matched_count == 0:
        # Fallback: Try identifying by email if conversation_id failed 
        # (This handles race conditions where frontend might have old state)
        # Note: We don't have email in payload currently, so we return error.
        return {"status": "error", "message": "Conversation not found (invalid conversation_id)"}
        
    return {"status": "ok"}


# -----------------------------
# Chat sync (per customer)
# -----------------------------
@app.get("/api/sync")
async def api_sync(email: str, account: str | None = None, start_date: str | None = None, end_date: str | None = None):
    email = email.lower().strip()

    query = {"email": email}
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

    msgs = []
    for m in email_received.find(query):
        # Referenced Message Lookup
        referenced_msg = None
        if m.get("in_reply_to"):
            # Try to find the message this one replies to
            # The In-Reply-To ID usually matches a 'message_id' in our DB
            ref = email_received.find_one({"message_id": m["in_reply_to"]})
            if ref:
                referenced_msg = {
                    "sender": ref.get("sender", "visitor"),
                    "text": _strip_quoted_text(ref["content"])[:150] + "..." if ref.get("content") and len(ref["content"]) > 150 else _strip_quoted_text(ref.get("content", "")),
                    "id": ref.get("message_id")
                }

        msgs.append({
            "sender": m.get("sender", "visitor"),
            "text": _strip_quoted_text(m["content"]) if m.get("content") else "",
            "timestamp": m["timestamp"].isoformat(),
            "attachments": m.get("attachments", []),
            "html_content": m.get("html_content"),
            "status": m.get("status", "sent"),
            "referenced_message": referenced_msg
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

async def process_whatsapp_reply(business_id: str, to_phone: str, text: str, attachments: list):
    """
    Helper to send text and media sequentially to WhatsApp.
    """
    if text and text.strip():
        await send_whatsapp_text(business_id, to_phone, text)
    
    for att in attachments:
         mime = att["content_type"]
         w_type = "document"
         if mime.startswith("image/"): w_type = "image"
         elif mime.startswith("video/"): w_type = "video"
         elif mime.startswith("audio/"): w_type = "audio"
         elif mime.startswith("application/pdf"): w_type = "document"
         
         # Upload
         media_id = await upload_media(business_id, att["content"], mime, att["filename"])
         if media_id:
             # Send
             await send_whatsapp_media(business_id, to_phone, w_type, media_id, caption=att["filename"])
         else:
             logger.error(f"Failed to upload media {att['filename']} for WhatsApp reply")


async def process_social_reply(account_id: str, recipient_id: str, text: str, platform: str):
    """Sends a social media message in the background."""
    await social_service.send_social_message(account_id, recipient_id, text, platform)

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

        # --- DETERMINE CHANNEL ---
        platform = "email"
        if "@" not in visitor_email:
            # Check if it's a social account
            account = social_accounts.find_one({"account_id": account_email})
            if account:
                platform = account.get("platform", "facebook")
            else:
                platform = "whatsapp"

        if platform == "email":
            # --- EMAIL PATH (ASYNC SENDING + IMMEDIATE UI) ---
            
            # 1. Pre-generate Message-ID (RFC complient with brackets)
            from email.utils import make_msgid
            raw_msg_id = make_msgid(domain="mini-crisp")
            
            # 2. Prepare DB Message-ID (Clean without brackets for storage consistency)
            db_msg_id = raw_msg_id
            if db_msg_id.startswith("<") and db_msg_id.endswith(">"):
                db_msg_id = db_msg_id[1:-1]

            # 3. Insert into DB immediately (Authoritative Source of Truth)
            insert_message(
                "admin", 
                text, 
                visitor_email,
                visitor_phone=None,
                account_email=account_email,
                html_content=html_content,
                subject=subject,
                cc=cc_list,
                bcc=bcc_list,
                attachments=attachments_metadata,
                origin="email",
                message_id=db_msg_id, # Stores clean ID
                timestamp=datetime.now(timezone.utc),
                sender_name="You"
            )

            # 4. Hand off SMTP sending to Background Task
            # We pass the raw_msg_id so the sent email header matches exactly what we expect
            background_tasks.add_task(
                process_email_background_task,
                visitor_email, 
                text, 
                account_email,
                html_content,
                subject,
                cc_list,
                bcc_list,
                attachments_for_email,
                raw_msg_id
            )

        elif platform == "whatsapp":
            # --- WHATSAPP PATH ---
            # Insert immediately (WhatsApp doesn't have the IMAP duplication issue)
            insert_message(
                "admin", 
                text, 
                None,
                visitor_phone=visitor_email,
                account_email=account_email,
                html_content=html_content,
                subject=subject,
                cc=cc_list,
                bcc=bcc_list,
                attachments=attachments_metadata,
                origin="whatsapp",
                timestamp=datetime.now(timezone.utc)
            )

            # Routing to WhatsApp
            # In this case, 'visitor_email' actually contains the phone number
            # We prioritize account_email (which will be business_number_id) if provided
            business_id = account_email if account_email and "@" not in account_email else None
            
            if not business_id:
                # Fallback: Find which business number received the LAST message in this thread
                last_msg = email_received.find_one({"visitor_phone": visitor_email, "source": "whatsapp"}, sort=[("timestamp", -1)])
                business_id = last_msg.get("business_number_id") if last_msg else None
            
            if business_id:
                background_tasks.add_task(process_whatsapp_reply, business_id, visitor_email, text, attachments_for_email)
            else:
                logger.error(f"Could not find business_number_id for WhatsApp reply to {visitor_email}")
        else:
            # --- SOCIAL PATH (Facebook/Instagram) ---
            insert_message(
                "admin", text, visitor_email, # visitor_email holds sender_id
                account_email=account_email,
                attachments=attachments_metadata,
                origin=platform,
                timestamp=datetime.now(timezone.utc)
            )
            background_tasks.add_task(process_social_reply, account_email, visitor_email, text, platform)

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
        {"$set": {"seen_at": datetime.now(timezone.utc)}}
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
    if email == "admin_global":
        await ws.accept()
        ADMIN_CONNECTIONS.add(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            ADMIN_CONNECTIONS.discard(ws)
        return

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

def search_customers_tool(query: str, purpose: str = "chat"):
    """
    Search for customers. 
    'purpose' must be:
    - 'email' (send email)
    - 'chat' (view chat)
    - 'summary' (summarize conversation)
    """
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
    return {
    "action": "search_customers",
    "results": formatted,
    "purpose": purpose
}


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

# --- LOCKED FEATURE: CHAT SUMMARIZATION ---
# DO NOT MODIFY THIS TOOL OR ITS LOGIC
def summarize_conversation_tool(email: str, summary_type: str = "short", start_date: str = None, end_date: str = None, last_n: int = None):
    """
    Generate a summary for a conversation.
    'summary_type': 'short' (TXT) or 'detailed' (PDF).
    'start_date', 'end_date': Optional ISO-8601 date strings (YYYY-MM-DD).
    'last_n': Optional integer to fetch the last N messages (e.g. 1, 5).
    """
    cust = ensure_customer(email=email)
    if not cust: return {"error": "Customer not found."}
    
    if summary_type == "detailed":
        url, error = generate_detailed_summary_pdf(email, start_date, end_date)
        if error: return {"error": error}
        msg = f"I've generated a detailed analytical report for your conversation with {email}"
        if start_date: msg += f" from {start_date}"
        if end_date: msg += f" to {end_date}"
        msg += "."
        
        return {
            "action": "summary_ready",
            "type": "detailed",
            "url": url,
            "message": msg
        }
    else:
        # Short Mode
        query = {"tb1_id": cust["tb1_id"]}
        
        msgs = []
        if last_n is not None:
            try:
                last_n = int(last_n) # Force to int as Gemini often sends floats like 5.0
            except:
                last_n = 5 # Default fallback
            
        if last_n and last_n > 0:
            # Last N messages
            msgs = list(email_received.find(query).sort("timestamp", -1).limit(last_n))
            msgs.reverse() # Chronological
            
        else:
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
                query["timestamp"] = date_filter
                msgs = list(email_received.find(query).sort("timestamp", 1)) # Chronological for range
                
                # If no messages in range
                if not msgs:
                    return {"error": f"No messages found between {start_date} and {end_date}."}
            else:
                # Default: Fetch all messages for the entire conversation
                msgs = list(email_received.find(query).sort("timestamp", 1))
                if not msgs:
                    return {"error": "No message history found for this contact."}

        summary_data = []
        for m in msgs:
            ts = m["timestamp"].strftime("%Y-%m-%d")
            summary_data.append(f"[{ts}] {m['sender']}: {m['content']}")
        raw_context = "\n".join(summary_data)
        
        msg = f"I'm analyzing the conversation with {email}"
        if start_date or end_date: msg += " for the selected dates"
        else: msg += " (recent messages)"
        msg += " to provide a synthesized summary."
        
        return {
            "action": "short_summary_logic",
            "email": email,
            "context": raw_context,
            "message": msg
        }

def compose_new_tool(to: str = None, subject: str = None, body: str = None):
    """Open or update the global email composer."""
    return {"action": "compose_new", "to": to, "subject": subject, "body": body}

def confirm_and_send_action_tool():
    """Execute the final send action on the dashboard after user confirmation."""
    return {"action": "send_email"}

def ask_summary_type_tool(email: str):
    """Present the user with a choice between Detailed (PDF) and Short (TXT) summary."""
    return {
        "action": "ask_mode",
        "email": email,
        "options": [
            {"label": "📊 Detailed Summary (PDF)", "type": "detailed", "email": email},
            {"label": "📝 Short Summary (TXT)", "type": "short", "email": email}
        ]
    }

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


def add_customer_note_tool(email: str, note: str):
    """Add a permanent note to a customer's profile."""
    from database import add_note
    res = add_note(email, note)
    return f"Note added: {note}"


# --- LOCKED FEATURE: AI ACCOUNT SWITCHING ---
# DO NOT MODIFY THESE TOOLS
def search_accounts_tool():
    """Returns a list of all configured email accounts with their display names/emails."""
    emails = [{"name": a.get("email"), "email": a.get("email"), "type": "email"} for a in get_email_accounts()]
    
    # Also include the system-default BOT_EMAIL from environment
    bot_email = os.environ.get("BOT_EMAIL", "ai.intern@cetl.in").lower()
    if not any(e["email"] == bot_email for e in emails):
        emails.append({"name": "AI Intern", "email": bot_email, "type": "email"})
        
    return emails

def switch_account_tool(account: str):
    """Switch the dashboard view to a specific account (email or ID)."""
    return {"action": "switch_account", "account": account}

def get_customer_details_tool(email: str):
    """Get full details including ID, phone, notes, and tags for a customer."""
    from database import get_notes, get_tags, ensure_customer
    cust = ensure_customer(email=email)
    notes = get_notes(email)
    tags = get_tags(email)
    return {"customer": cust["name"], "email": email, "notes": notes, "tags": tags}

def add_customer_tag_tool(email: str, tag: str):
    """Add a tag to a customer."""
    from database import add_tag
    add_tag(email, tag)
    return f"Tag added: {tag}"



# --- LOCKED FEATURE: MESSAGE FILTERING ---
def apply_filter_tool(query: str = None, start_date: str = None, end_date: str = None):
    """
    Apply filters to the message list.
    Args:
        query: Keyword to search for.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
    """
    return {"action": "apply_filters", "query": query, "start": start_date, "end": end_date}

@app.post("/api/ai/agent")
async def ai_agent(request: Request):
    return {
        "status": "error",
        "message": "This endpoint is deprecated. Use /api/ai/command instead."
    }


# -----------------------------
# Deepgram Transcription
# -----------------------------
@app.post("/api/ai/transcribe")
async def ai_transcribe(file: UploadFile = File(...)):
    if not DeepgramClient:
        return {"status": "error", "message": "deepgram-sdk not installed"}
    
    try:
        api_key = os.environ.get("DEEPGRAM_API_KEY")
        if not api_key:
            return {"status": "error", "message": "DEEPGRAM_API_KEY missing in .env"}
        
        deepgram = DeepgramClient(api_key=api_key)
        
        content = await file.read()
        payload = {"buffer": content}
        
        options = {
            "model": "nova-2",
            "smart_format": True,
            "language": "en-US"
        }
        
        response = deepgram.listen.v1.media.transcribe_file(request=content, **options)
        
        # Robust parsing for both object and dict responses
        if hasattr(response, 'results'):
            transcript = response.results.channels[0].alternatives[0].transcript
        else:
            transcript = response['results']['channels'][0]['alternatives'][0]['transcript']
            
        return {"status": "ok", "transcript": transcript}
    except Exception as e:
        logger.exception("Deepgram Transcription Error")
        return {"status": "error", "message": str(e)}

# -----------------------------
# AI Assistant (Gemini Autonomous Agent)
# -----------------------------

# GROQ Fallback Helper
async def call_groq_fallback(text: str, history_context: str = ""):
    """Fallback to GROQ when Gemini rate limits are hit - with intent parsing"""
    if not Groq:
        return None
    
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    
    try:
        client = Groq(api_key=api_key)
        
        # Enhanced system prompt to match Gemini's behavior
        system_prompt = f"""You are an AI assistant for Mini Crisp dashboard. 

RECENT HISTORY:
{history_context}

When the user asks to:
- "Write/send/compose email to [name]" - respond with: COMPOSE_EMAIL|[name]|[message if provided]
- "Search for [name]" - respond with: SEARCH_CONTACT|[name]
- "Open chat with [name]" - respond with: OPEN_CHAT|[name]
- "Show messages/emails" - respond with: FETCH_EMAILS
- "Summarize char/messages with [name]" - respond with: SUMMARIZE|[name]
- Navigate somewhere - respond with: NAVIGATE|[target]
- "Pick option [number]" or "Select [name]" - respond with: SELECT_OPTION|[number or name]
- General Chat - respond with a helpful conversational sentence.

CRITICAL: If you use a command like FETCH_EMAILS or SUMMARIZE, DO NOT include the command name in your final helpful sentence. Just say "I am fetching those for you" or "I am summarizing the chat with [name]".
Be concise and action-oriented. Do not mention that you are a backup AI. """

        completion = await run_in_threadpool(
            lambda: client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.3,
                max_tokens=500
            )
        )
        
        response_text = completion.choices[0].message.content.strip()
        
        # Parse intent from GROQ response
        actions = []
        display_message = response_text
        
        # Check if response contains action commands
        if "|" in response_text:
            parts = response_text.split("|")
            command = parts[0].strip()
            
            if command == "COMPOSE_EMAIL" and len(parts) >= 2:
                recipient_name = parts[1].strip()
                body = parts[2].strip() if len(parts) > 2 else ""
                
                # Search for the contact first
                from database import search_customers
                results = search_customers(recipient_name)
                
                if results and len(results) > 0:
                    # Format results for display
                    formatted_results = []
                    for r in results[:5]:  # Limit to 5 results
                        formatted_results.append({
                            "name": r.get("name", "Unknown"),
                            "email": r.get("cust_email") or r.get("phone") or "No Email/Phone",
                            "phone": r.get("phone"),
                        })
                    
                    # Show search results and let user pick
                    actions.append({
                        "action": "search_customers",
                        "results": formatted_results,
                        "purpose": "email",
                        "body": body  # Save the message body for later
                    })
                    display_message = f"I found {len(formatted_results)} contact(s) named '{recipient_name}'. Which one would you like to email?"
                else:
                    # Contact not found
                    actions.append({
                        "action": "search_customers",
                        "results": [],
                        "purpose": "email"
                    })
                    display_message = f"I couldn't find anyone named '{recipient_name}' in your contacts. Could you provide their email address?"
            
            elif command == "SEARCH_CONTACT" and len(parts) >= 2:
                search_name = parts[1].strip()
                from database import search_customers
                results = search_customers(search_name)
                
                formatted_results = []
                for r in results[:5]:  # Limit to 5 results
                    formatted_results.append({
                        "name": r.get("name", "Unknown"),
                        "email": r.get("cust_email") or r.get("phone") or "No Email/Phone",
                        "phone": r.get("phone"),
                    })
                
                actions.append({
                    "action": "search_customers",
                    "results": formatted_results,
                    "purpose": "chat"
                })
                display_message = f"Found {len(formatted_results)} result(s) for '{search_name}'"
            
            elif command == "OPEN_CHAT" and len(parts) >= 2:
                contact_ref = parts[1].strip()
                actions.append({
                    "action": "open_chat",
                    "email": contact_ref
                })
                display_message = f"Opening chat with {contact_ref}..."

            elif command == "SELECT_OPTION" and len(parts) >= 2:
                selection = parts[1].strip()
                # Try to resolve selection from history context manually or just pass it as open_chat for now
                # Since we don't have the structured history object easily available here to lookup exact email
                # We will rely on the frontend or backend heuristic to resolve it if possible.
                # But actually, 'open_chat' usually takes an email.
                # However, if selection is a number (e.g. "1"), we need to look it up.
                
                # Heuristic: If it's a number, try to extract email from the visible history in prompt
                import re
                email_match = None
                if selection.isdigit():
                    idx = int(selection)
                    # Regex to find: "1. Name (email)"
                    matches = re.findall(rf"{idx}\.\s+.*?\((\S+@\S+|\S+)\)", history_context)
                    if matches:
                        email_match = matches[0]
                
                if email_match:
                    # Check if previous context was search for email
                    # This is hard to know exactly without saving conversational state outside of history string
                    # But we can default to 'open_chat' and let the frontend/backend heuristic fix handle it?
                    # Wait, 'open_chat' opens chat. 'compose_new' opens email.
                    # We need to know the INTENT of the previous search.
                    
                    # Heuristic: Check history for email intent
                    purpose = "chat"
                    if any(phrase in history_context for phrase in ["email?", "mail", "compose", "write to", "send to", "Which one would you like to email?"]):
                        purpose = "email"
                        purpose = "email"
                    
                    if purpose == "email":
                         actions.append({
                            "action": "compose_new",
                            "to": email_match
                         })
                         display_message = f"Opening composer for {email_match}..."
                    else:
                         actions.append({
                            "action": "open_chat",
                            "email": email_match
                         })
                         display_message = f"Opening chat with {email_match}..."

                else:
                    display_message = "I couldn't identify the option from our history. Please try searching again."

            elif command == "FETCH_EMAILS":
                actions.append({
                    "action": "fetch_emails"
                })
                display_message = "Fetching your messages..."
            
                target = parts[1].strip().lower()
                actions.append({
                    "action": "navigate",
                    "target": target
                })
                display_message = f"Navigating to {target}..."
            
            elif command == "CANCEL":
                 actions.append({"action": "close_composer"})
                 display_message = "Cancelling and closing composer."

        
        # Add note that this is from backup AI
        if not actions and "(via backup AI)" not in display_message:
            display_message += " (via backup AI)"
        
        # Text-to-Action Safety Net
        if not actions and any(x in display_message for x in ["opened", "drafted", "updated the email", "added a subject"]):
             import re
             
             # Extract Subject and Body (heuristic)
             subject = None
             body = None
             subj_match = re.search(r"subject\s+['\"`](.+?)['\"`]", display_message, re.IGNORECASE)
             if subj_match: subject = subj_match.group(1)
             
             body_match = re.search(r"body\s+['\"`](.+?)['\"`]", display_message, re.IGNORECASE)
             if body_match: body = body_match.group(1)

             email_match = re.search(r"to\s+([a-zA-Z0-9._%+-]+@\S+)", display_message)
             email = None
             if email_match:
                 email = email_match.group(1).rstrip('.,!?')
                 
             if email or subject or body:
                 actions.append({
                     "action": "compose_new",
                     "to": email,
                     "subject": subject,
                     "body": body
                 })

        return {
            "status": "ok",
            "response": display_message,
            "actions": actions
        }
    except Exception as e:
        logger.error(f"GROQ Fallback Error: {e}")
        return None
    
def classify_intent(prompt: str, history: str = ""):
    """Robust 3-stage intent classification: Gemini -> GROQ -> Keywords"""
    prompt_lower = prompt.lower().strip()
    
    # --- 1. PRIMARY: Gemini Intent Classification ---
    try:
        intent_model = genai.GenerativeModel(
            model_name=os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ],
            system_instruction="""
You are an AI assistant for Mini Crisp dashboard. Your role is "Mini Crisp Admin Assistant – intent classification only".
Analyze user input and return valid JSON with intent, confidence (0.0 to 1.0), and missing_info list.

Intents:
- compose: write, send, or draft a new email. DO NOT use for summarization requests.
- reply: respond to an existing student/customer
- search: find customers, messages, or search history
- navigate: go to specific pages (whatsapp, inbox, dashboard)
- resync: sync or refresh emails
- select_contact: pick a specific person from a list (e.g., "first one", "second one", "this one")
- note: add or view customer notes
- export: download conversation transcripts
- mark_read: mark a message as read
- summarize: provide a short or detailed summary of a conversation (e.g. 'summarize last message', 'summarize chat')
- switch_account: change the active account view (e.g., "switch to account X", "change account")
- open_chat: open a specific conversation with a customer (e.g., "open chat with [name]", "see messages from [name]")
- cancel: cancel or close the current UI modal (e.g., "close composer", "cancel email", "stop writing"). DO NOT use this for email content (e.g. "ask him to leave").
- manage_filters: apply, update or clear search and date filters (e.g. "clear filter", "filter by date", "remove filter")

Schema:
{
  "intent": "compose|reply|search|navigate|resync|select_contact|note|export|mark_read|summarize|switch_account|open_chat|cancel|manage_filters|unknown",
  "confidence": 0.0,
  "missing_info": []
}"""
        )
        
        # Generation config moved inside generate_content for better reliability
        response = intent_model.generate_content(
            f"User input: {prompt}\nRecent history:\n{history}",
            generation_config={"temperature": 0.0}
        )
        
        if response and hasattr(response, 'text'):
            res_text = response.text.strip()
            # Clean markdown code blocks
            if res_text.startswith("```"):
                res_text = res_text.strip("`").replace("json", "", 1).strip()
            
            result = json.loads(res_text)
            if "intent" in result:
                # Normalize 'unknown' intent
                if result["intent"] == "unknown":
                    result["intent"] = "chat"
                    result["confidence"] = max(result.get("confidence", 0.0), 0.51)
                return result

    except Exception as e:
        err_str = str(e).lower()
        # Log specifically for 429s/Quota
        if "429" in err_str or "quota" in err_str or "exhausted" in err_str:
            logger.warning(f"Gemini Intent Classification Rate Limited: {e}")
        else:
            logger.error(f"Gemini Intent Error: {e}")

    # --- 2. SECONDARY: GROQ Intent Classification ---
    if Groq and os.environ.get("GROQ_API_KEY"):
        try:
            client = Groq(api_key=os.environ["GROQ_API_KEY"])
            groq_prompt = f"""
You are an AI assistant for Mini Crisp dashboard. Your role is "Mini Crisp Admin Assistant – intent classification only".
Available intents: 
- compose (write/send email, DO NOT use for summarization)
- reply (respond to customer)
- search (find customers/messages)
- navigate (go to pages)
- resync (refresh)
- select_contact (pick from list)
- note (add note)
- export (download transcript)
- mark_read (mark read)
- summarize (e.g. 'summarize last message', 'summarize chat')
- switch_account (change view)
- open_chat (view conversation)
- manage_filters (date/keyword filters)
- unknown

User Input: {prompt}
History: {history}

Return ONLY valid JSON matching this schema:
{{
  "intent": "intent_label",
  "confidence": 0.6,
  "missing_info": []
}}"""
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": groq_prompt}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(completion.choices[0].message.content.strip())
            if "intent" in result:
                # Map back to known labels if GROQ hallucinates (extra safety)
                valid_intents = ["compose", "reply", "search", "navigate", "resync", "select_contact", "note", "export", "mark_read", "summarize", "switch_account", "open_chat", "manage_filters", "unknown"]
                if result["intent"] not in valid_intents:
                    result["intent"] = "unknown"
                
                if result["intent"] == "unknown":
                    result["intent"] = "chat"
                    result["confidence"] = max(result.get("confidence", 0.0), 0.51)
                return result
        except Exception as ge:
            logger.error(f"GROQ Intent Fallback Error: {ge}")

    # --- 3. TERTIARY: Keyword Heuristic Fallback ---
    # Final safety net to prevent loop
    intent = "chat" # Default internal fallback
    confidence = 0.51

    keywords = {
        "switch_account": ["account", "switch"],
        "compose": ["send", "write", "compose", "mail", "tell"],
        "reply": ["reply", "respond", "answer"],
        "search": ["find", "search", "look for", "show me"],
        "navigate": ["go to", "open", "navigate"],
        "resync": ["sync", "refresh", "resync"],
        "note": ["note", "profile"],
        "export": ["download", "export", "transcript"],
        "summarize": ["summarize", "summary", "report", "analysis"],
        "open_chat": ["open chat", "view chat", "show messages", "see messages", "conversation with"],
        "cancel": ["cancel", "close composer", "stop writing", "close email"],
        "manage_filters": ["filter", "clear filter", "remove filter", "date range", "keyword"]
    }

    # High priority keyword matches for selection
    if any(word in prompt_lower for word in ["first", "second", "third", "number 1", "number 2", "1st", "2nd"]):
        return {"intent": "select_contact", "confidence": 0.95, "missing_info": []}

    for label, words in keywords.items():
        if any(word in prompt_lower for word in words):
            intent = label
            confidence = 0.8
            break

    return {
        "intent": intent, 
        "confidence": confidence, 
        "missing_info": []
    }
TOOLS_BY_INTENT = {
    "compose": [
        search_customers_tool,
        compose_new_tool,
        confirm_and_send_action_tool
    ],
    "reply": [
        open_chat_tool,
        draft_reply_tool,
        confirm_and_send_action_tool
    ],
    "search": [
        search_customers_tool,
        get_emails_tool,
        open_chat_tool,
        summarize_conversation_tool,
        ask_summary_type_tool,
        get_inbox_stats_tool,
        apply_filter_tool
    ],
    "navigate": [
        navigate_tool,
        clear_filters_tool,
        update_search_tool,
        apply_filter_tool
    ],
    "resync": [
        sync_emails_tool
    ],
    "select_contact": [
        open_chat_tool,
        compose_new_tool,
        search_customers_tool,
        summarize_conversation_tool,
        ask_summary_type_tool
    ],
    "note": [
        add_customer_note_tool,
        get_customer_details_tool,
        add_customer_tag_tool
    ],
    "export": [
        export_chat_tool
    ],
    "mark_read": [
        mark_read_tool
    ],
    "summarize": [
        search_customers_tool,
        summarize_conversation_tool,
        ask_summary_type_tool
    ],
    "switch_account": [
        search_accounts_tool,
        switch_account_tool
    ],
    "open_chat": [
        search_customers_tool,
        open_chat_tool
    ],
    "manage_filters": [
        clear_filters_tool,
        apply_filter_tool
    ]
}


@app.post("/api/ai/command")
async def ai_command(request: Request):
    """Execution endpoint with unified intent-based whitelisting and robust fallbacks."""
    try:
        data = await request.json()
        text = data.get("text")
        if not text:
            return {"status": "error", "message": "No command provided", "actions": []}

        # 1. Grounding context
        accounts_data = get_email_accounts()
        env_email = os.environ.get("BOT_EMAIL", os.environ.get("IMAP_EMAIL", "ai.intern@cetl.in")).lower()
        if not any(a["email"] == env_email for a in accounts_data):
            accounts_data.append({"email": env_email})

        # 2. History context
        from database import get_recent_ai_history, save_ai_interaction
        history_items = get_recent_ai_history(5)
        
        # Format for textual instruction grounding (legacy but useful for intent)
        history_context_lines = []
        # Format for Gemini Native Chat Session
        gemini_history = []

        for h in reversed(history_items):
             # Textual line for intent classification grounding
             line = f"User: {h['prompt']}\nAI: {h['response']}"
             
             # Reconstruct native history parts
             model_parts = [h['response']]
             
             if h.get('tools'):
                 for tool in h['tools']:
                     # Add to textual grounding
                     if tool.get("action") in ["search_customers", "fetch_customers"] and tool.get("results"):
                         line += "\n[Visible Options:]"
                         for i, res in enumerate(tool["results"]):
                             line += f"\n{i+1}. {res.get('name')} ({res.get('email')})"
                     
                     # Note: We don't reconstruct full FunctionCall/Response objects from DB yet
                     # but injecting the visible tool output into the model's history part
                     # helps Gemini "remember" what it just showed the user.
                     if tool.get("action") == "search_customers" and tool.get("results"):
                        model_parts.append(f"SEARCH_RESULTS: {json.dumps(tool.get('results'))}")

             history_context_lines.append(line)
             
             # Native Gemini History objects
             gemini_history.append({"role": "user", "parts": [h['prompt']]})
             gemini_history.append({"role": "model", "parts": model_parts})

        history_context = "\n".join(history_context_lines)
        
        # 3. INTENT CLASSIFICATION (Robust chain)
        intent_result = await run_in_threadpool(classify_intent, text, history_context)
        intent = intent_result["intent"]
        confidence = intent_result["confidence"]
        missing = intent_result.get("missing_info", [])

        # Strict whitelisting
        allowed_tools = TOOLS_BY_INTENT.get(intent, [])
        logger.debug(f"AI command intent: {intent} (conf: {confidence}), tools: {len(allowed_tools)}")
        
        # 4. ACTION EXECUTION
        model_name = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
        
        # Lower safety thresholds for administrative summarization/actions
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        model = genai.GenerativeModel(
            model_name=model_name,
            safety_settings=safety_settings,
            system_instruction=f"""You are an ACTION EXECUTOR for Mini Crisp Admin UI.
Your role: DISCAAT KID an AI assistant for SCPL.
Today's Date: {datetime.now().strftime('%Y-%m-%d')}
Intent: {intent} (FIXED)

CORE FLOW FOR GLOBAL EMAIL COMPOSITION:
1. SEARCH FIRST: If a name is mentioned (e.g., "mail Samiksha", "tell her hi"), ALWAYS call `search_customers_tool` first (purpose="email").
2. LIST MATCHES: In your text response, **explicitly list the matching contacts with numbers** (e.g., "1. Samiksha (s@e.com), 2. Samiksha J (sj@e.com). Which one?").
3. SELECTION: When the user picks a number (e.g., "first one"), call `compose_new_tool` with the selected email.
4. CONTEXTUAL GENERATION: If the user provided a topic (e.g., "regarding meeting" or "tell her hi"), you MUST generate an appropriate Subject and Body and pass them to `compose_new_tool`.
5. UPDATES: If the user gives subject/body after the composer is open, call `compose_new_tool` again with those specific fields to update the modal.
6. NO SENDING: Never send automatically. Stop after opening/filling.
7. CONFIRM SEND: Only call `confirm_and_send_action_tool` if the user explicitly says "send" or "confirm" while the composer is visible.

GENERAL RULES:
- **Identity**: If the user asks who you are or what your name is, ALWAYS respond with: "hi i am DISCAAT KID an AI assistant for SCPL."
- **No Intermediate Thoughts**: DO NOT say "Searching for...", "Let me look that up", "Checking our records", or similar. 
- **Wait for Tools**: Call your tools, wait for the result, and ONLY provide the final response to the user.
- **No Hallucinated Logs**: Never output text like "[System: ...]" or simulate background logs.
- **Numbered Lists**: For any search result, always provide a numbered list (1, 2, 3...) in your text.

# --- LOCKED FLOW: CHAT SUMMARIZATION ---
# CORE FLOW FOR CHAT SUMMARIZATION:
1. IDENTIFY: Even if an email or full name is provided, ALWAYS call `search_customers_tool` first (purpose="summary") to verify and list the contact. Proceed to stage 3 only after confirming the selection.
2. LIST MATCHES: After the tool result, **explicitly list the matching contacts with numbers** in your final text response.
3. SELECTION & ACTION: Once a contact is selected (or if specific email was provided):
   - **DATE/QUANTITY EXTRACTION**:
     - If user says "last N messages" (e.g., "last 5", "last message", "previous 10"), pass `last_n=N` (integer).
     - If user mentions ranges (e.g., "today", "last week"), set `start_date`/`end_date` (YYYY-MM-DD).
   - **DEFAULT**: Call `summarize_conversation_tool` with `summary_type="short"` and EITHER `last_n` OR dates.
   - **PDF/REPORT**: Only if requested, call `summarize_conversation_tool` with `summary_type="detailed"` and dates.
4. PRESENT RESULTS: 
   - For "Detailed" mode: Present the download link.
   - For "Short" mode: The tool returns the raw messages for that period. **Synthesize them into a clear narrative.** If no messages found, report that.

# --- LOCKED FLOW: AI ACCOUNT SWITCHING ---
CORE FLOW FOR ACCOUNT SWITCHING (Gmail Only):
1. DISCOVER: Even if a name is provided (e.g., "switch to ai intern"), ALWAYS call `search_accounts_tool` first to see which GMAIL accounts are available.
2. MATCH: Look through the tool results. If a result matches (or is PHONETICALLY similar to, e.g. "ai in turn" vs "ai intern") the user's requested email/name, call `switch_account_tool` with that email.
3. FALLBACK: If NO match is found for the requested name, tell the user: "I couldn't find a Gmail account named '[name]'. Available Gmail accounts are: [list from tool result]".

CORE FLOW FOR OPENING CHATS:
1. SEARCH FIRST: If a user asks to "open chat with [name]" or "see messages from [name]", call `search_customers_tool` first (purpose="chat").
2. LIST MATCHES: In your text response, **explicitly list the matching contacts with numbers** (e.g., "1. Samiksha (s@e.com), 2. Samiksha J (sj@e.com). Which one?").
3. SELECTION: When the user picks a number (e.g., "first one"), call `open_chat_tool` with the selected email.
4. NOT FOUND: If no matches are returned by the search tool, inform the user: "I couldn't find any customers matching '[name]'."

- Be extremely precise with these multi-turn flows.
- Be helpful and professional.

CORE FLOW FOR FILTERING / LISTING EMAILS (LOCKED FLOW):
1. IDENTIFY: If the user asks to "show", "list", or "see" emails/messages from a specific date or time period.
2. EXTRACT DATE: Convert relative dates (like "today") to `YYYY-MM-DD` format.
3. ACTION: **MANDATORY**: Call `apply_filter_tool` with `start_date` and `end_date` to update the UI Visitor List.
   - If "today": Set both start and end to Today's Date.
   - If "since [date]": Set `start_date`.
4. OPTIONAL: You may ALSO call `get_emails_tool` if you want to provide a quick summary in chat, but `apply_filter_tool` is required.
5. RESPONSE: Confirm the action, e.g., "I've updated the visitor list to show emails from [date].\"""",
            tools=allowed_tools
        )

        chat = model.start_chat(history=gemini_history, enable_automatic_function_calling=True)
        
        # Standardize empty/malformed handling with GROQ fallback
        try:
            response = await run_in_threadpool(chat.send_message, text)
            # Collect actions from history FIRST
            result_actions = []
            if getattr(chat, 'history', None):
                for msg in chat.history:
                    if hasattr(msg, 'parts'):
                        for part in msg.parts:
                            if hasattr(part, 'function_response') and part.function_response:
                                def recursive_to_dict(obj):
                                    if hasattr(obj, 'items'): return {k: recursive_to_dict(v) for k, v in obj.items()}
                                    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)): return [recursive_to_dict(x) for x in obj]
                                    return obj
                                res = recursive_to_dict(part.function_response.response)
                                if isinstance(res, dict) and "result" in res: res = res["result"]
                                
                                if isinstance(res, dict):
                                    if "action" in res: result_actions.append(res)
                                    elif "results" in res: result_actions.append({"action": "search_customers", "results": res["results"], "purpose": intent})
                                    # Handle generic list results
                                    result_actions.append({"action": "search_results_list", "results": res, "purpose": intent})

            response_text = ""
            try:
                if response.text: response_text = response.text
            except (ValueError, AttributeError):
                # Handle blocked content or finish_reason=OTHER
                if hasattr(response, 'prompt_feedback'):
                    logger.warning(f"Gemini Blocked: {response.prompt_feedback}")
                
                # If we have valid actions, don't show an error message
                if result_actions:
                    response_text = f"Action processed successfully ({len(result_actions)} updates applied)."
                else:
                    response_text = "I processed your request, but my text response was blocked by safety filters. Please check the dashboard for updates."

            # --- FORCED ACTIONS BY INTENT ---
            if intent == "cancel":
                 if not any(a.get("action") == "close_composer" for a in result_actions):
                     result_actions.append({"action": "close_composer"})

            save_ai_interaction(text, response_text, result_actions)
            return {"status": "ok", "response": response_text, "actions": result_actions}

        except Exception as exec_error:
            logger.warning(f"Gemini execution failure: {exec_error}, falling back to GROQ mock...")
            groq_result = await call_groq_fallback(text, history_context)
            if groq_result:
                # Ensure actions match the whitelisted tools for this intent
                allowed_action_names = {t.__name__.replace("_tool", "") for t in allowed_tools}
                groq_result["actions"] = [a for a in groq_result.get("actions", []) if a.get("action") in allowed_action_names]
                save_ai_interaction(text, groq_result["response"], groq_result["actions"])
                return groq_result
            
            raise exec_error # Fall through to global error if GROQ also fails

    except Exception as e:
        logger.exception("Final Catch: AI Command Error")
        return {
            "status": "error",
            "message": "Temporary issue processing your request.",
            "actions": []
        }
# AI Email Generation Endpoint (to be added to main.py after line 1289)

@app.post("/api/ai/generate-email")
async def generate_email(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "")
    if not prompt:
        return {"status": "error", "message": "No prompt provided"}

    # ---- Try GEMINI first ----
    try:
        if genai:
            model = genai.GenerativeModel(
                os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
            )
            response = model.generate_content(
                "Write a professional email body only. No subject.\n\n" + prompt
            )
            return {
                "status": "ok",
                "provider": "gemini",
                "email_body": response.text.strip()
            }
    except Exception as e:
        logger.warning(f"Gemini failed, falling back to Groq: {e}")

    # ---- GROQ fallback ----
    if not Groq:
        return {"status": "error", "message": "No AI provider available"}

    try:
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "Write a professional email body only. No subject."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=1024
        )

        return {
            "status": "ok",
            "provider": "groq",
            "email_body": completion.choices[0].message.content.strip()
        }
    except Exception as e:
        logger.exception("Email generation failed")
        return {"status": "error", "message": str(e)}

# -----------------------------
# Deepgram Real-time Streaming
# -----------------------------
@app.websocket("/api/ai/transcribe-live")
async def transcribe_live(websocket: WebSocket):
    await websocket.accept()
    logger.info("🎙️ Client connected for STREAMING transcription")

    dg_api_key = os.environ["DEEPGRAM_API_KEY"].strip()
    logger.info(f"🔑 Deepgram key length={len(dg_api_key)}, preview={dg_api_key[:4]}...{dg_api_key[-4:]}")
    dg_url = "wss://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&language=en-US&punctuate=true&encoding=linear16&sample_rate=48000"
    # NOTE: encoding=linear16&sample_rate=48000 might need adjustment based on browser input. 
    # Browser usually sends WebM/Opus. Deepgram manages container formats automatically if not specified, 
    # but for raw streaming, precise params help. 
    # Let's try auto-detect first by NOT sending encoding params for WebM, 
    # or use the minimal URL if we send WebM container.
    
    # Correction: Browser MediaRecorder sends WebM. Deepgram supports WebM streaming natively.
    # Added interim_results=true to stream partials back down, and endpointing=false to avert 1000 closures
    dg_url = "wss://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&language=en-US&punctuate=true&interim_results=true&endpointing=false"

    logger.info(f"Connecting to Deepgram: {dg_url}")
    try:
        async with websockets.connect(
            dg_url, 
            additional_headers={"Authorization": f"Token {dg_api_key}"}
        ) as dg_socket:
            logger.info("Connected to Deepgram successfully!")
            
            async def receive_audio():
                try:
                    while True:
                        data = await websocket.receive()
                        if "bytes" in data:
                            await dg_socket.send(data["bytes"])
                        elif "text" in data:
                            msg = json.loads(data["text"])
                            if msg.get("type") == "stop":
                                logger.info("Received stop command from client.")
                                await dg_socket.send(json.dumps({"type": "CloseStream"}))
                                break
                except WebSocketDisconnect:
                    logger.info("Client disconnected from audio stream.")
                except Exception as e:
                    logger.error(f"Audio receiver error: {e}", exc_info=True)

            async def receive_transcript():
                try:
                    async for msg in dg_socket:
                        res = json.loads(msg)
                        if "channel" in res:
                            transcript = res["channel"]["alternatives"][0]["transcript"]
                            if transcript:
                                logger.debug(f"Deepgram Transcript: {transcript}")
                                await websocket.send_json({
                                    "type": "transcript", 
                                    "text": transcript, 
                                    "is_final": res.get("is_final", False)
                                })
                except Exception as e:
                    logger.error(f"Transcript receiver error: {e}", exc_info=True)

            # Run bidirectional streams
            await asyncio.gather(receive_audio(), receive_transcript())

    except Exception as e:
        if "401" in str(e):
            logger.error("🛑 DEEPGRAM AUTHENTICATION FAILED (401). Please check your DEEPGRAM_API_KEY in .env!")
            try:
                await websocket.send_json({"type": "error", "message": "Deepgram Authentication Failed (401). Check API Key."})
            except: pass
        else:
            logger.error(f"Deepgram WebSocket Connection/Loop Error: {e}", exc_info=True)
    finally:
        try:
            await websocket.close()
        except: 
            pass

# -----------------------------
# Gmail sync (SAFE)
# -----------------------------
def gmail_sync_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    sync_counter = 0

    # 1. Backfill history (fetch ALL) - run once on startup
    try:
        logging.info("Starting initial email backfill...")
        # Optimization: Only backfill last 7 days initially to avoid hanging on massive inboxes
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        initial_emails = fetch_emails(criteria=f'(SINCE "{seven_days_ago}")')
        for r in initial_emails:
            insert_message(r["sender"], r["body"], r["visitor"], origin=r["source"], message_id=r.get("message_id"), timestamp=r.get("timestamp"), attachments=r.get("attachments"), account_email=r.get("account_email"), html_content=r.get("html_content"), in_reply_to=r.get("in_reply_to"), sender_name=r.get("sender_name"))
        logging.info("Initial backfill complete.")
    except Exception as e:
        logger.error(f"Backfill error: {e}")

    while True:
        try:
            # Broadcast syncing status
            if MAIN_LOOP:
                asyncio.run_coroutine_threadsafe(
                    broadcast_to_admins({"type": "sync_status", "status": "syncing"}), 
                    MAIN_LOOP
                )

            # 2. Continuous sync (fetch UNSEEN)
            # Scan Sent folder only every 6th iteration (approx 60s) to reduce load
            should_scan_sent = (sync_counter % 6 == 0)
            replies = fetch_emails(criteria="UNSEEN", scan_sent_folder=should_scan_sent)
            
            sync_counter += 1

            for r in replies:
                sender = r["sender"]
                body = r["body"]
                email = r["visitor"]

                # Gmail replies ALSO mapped to customer
                insert_message(sender, body, email, origin=r["source"], message_id=r.get("message_id"), timestamp=r.get("timestamp"), attachments=r.get("attachments"), account_email=r.get("account_email"), html_content=r.get("html_content"), in_reply_to=r.get("in_reply_to"), sender_name=r.get("sender_name"))

                # if sender == "visitor":
                #    forward_visitor_message_to_admin(email, body)
                # else:
                #    send_reply_from_admin_to_customer(email, body)

            # Broadcast idle status
            if MAIN_LOOP:
                asyncio.run_coroutine_threadsafe(
                    broadcast_to_admins({"type": "sync_status", "status": "idle"}), 
                    MAIN_LOOP
                )

        except Exception as e:
            logger.error(f"Gmail sync error: {e}")

        time.sleep(10) # 10 seconds as per plan

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)