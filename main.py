import asyncio
import threading
import logging
from pymongo.errors import DuplicateKeyError
import time
from datetime import datetime,timezone
from database import mark_customer_read
from fastapi import FastAPI, WebSocket, Request, BackgroundTasks, WebSocketDisconnect, Response
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from database import ensure_customer, get_customer_by_email
from database import get_email_accounts
# DB
from database import email_received, ensure_customer

# Email services
from email_service import (
    send_admin_and_customer_notifications,
    send_reply_from_admin_to_customer,
    forward_visitor_message_to_admin
)

# Gmail reader
from gmail_reader import fetch_emails

logger = logging.getLogger("main")
logger.setLevel(logging.INFO)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

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


def insert_message(sender, text, visitor_email, guest_id=None, origin="chat", message_id=None, timestamp=None):
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
        "seen_at": None
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
        "timestamp": now.isoformat()
    }

    asyncio.create_task(broadcast(visitor_email, guest_id, payload))

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

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/admin")
async def admin(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

# -----------------------------
# ✅ ADMIN INBOX (CUSTOMERS ONLY)
# -----------------------------
@app.get("/api/admin/messages")
async def api_admin_messages(search: str | None = None):
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
    cursor = email_received.find({}).sort("timestamp", -1)

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
                "unread": unread
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
async def add_account(payload: dict):
    add_email_account(payload)
    return {"status": "ok"}

def run_full_sync():
    try:
        logging.info("Starting MANUAL full sync...")
        results = fetch_emails(criteria="ALL")
        for r in results:
            insert_message(r["sender"], r["body"], r["visitor"], origin=r["source"], message_id=r.get("message_id"), timestamp=r.get("timestamp"))
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
            "timestamp": m["timestamp"].isoformat()
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
async def api_reply(reply: AdminReply):
    insert_message("admin", reply.text, reply.visitor_email)
    send_reply_from_admin_to_customer(reply.visitor_email, reply.text)
    return {"status": "ok"}

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
            insert_message(r["sender"], r["body"], r["visitor"], origin=r["source"], message_id=r.get("message_id"), timestamp=r.get("timestamp"))
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
                insert_message(sender, body, email, origin=r["source"], message_id=r.get("message_id"), timestamp=r.get("timestamp"))

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
