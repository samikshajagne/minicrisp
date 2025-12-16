# main.py
import time
import asyncio
import threading
import logging
from datetime import datetime
from database import mark_customer_read
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# DB
from database import email_received, ensure_customer

# Email services
from email_service import (
    send_admin_and_customer_notifications,
    send_reply_from_admin_to_customer,
    forward_visitor_message_to_admin
)

# Gmail reader
from gmail_reader import fetch_unread_replies

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
from database import ensure_customer, get_customer_by_email

def insert_message(sender, text, visitor_email, guest_id=None, origin="chat"):
    if not visitor_email:
        return

    visitor_email = visitor_email.lower().strip()

    # 🔥 ONLY chat-origin messages can create customers
    if origin == "chat":
        cust = ensure_customer(visitor_email)
        tb1_id = cust["tb1_id"]
    else:
        # Email-origin messages must belong to an EXISTING customer
        cust = get_customer_by_email(visitor_email)
        if not cust:
            return  # ❌ Ignore unwanted email users completely
        tb1_id = cust["tb1_id"]

    now = datetime.utcnow()

    email_received.insert_one({
        "tb1_id": tb1_id,
        "email": visitor_email,
        "content": text,
        "sender": sender,
        "source": origin,   # "chat" or "email"
        "timestamp": now
    })

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
async def api_admin_messages():
    conversations = {}

    cursor = email_received.find({"source": "chat"}).sort("timestamp", -1)

    for m in cursor:
        tb1_id = m["tb1_id"]

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
                "timestamp": m["timestamp"],
                "unread": unread
            }

    return {"messages": list(conversations.values())}



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
async def api_sync(email: str):
    email = email.lower().strip()

    msgs = []
    for m in email_received.find({"email": email, "source": "chat"}):
        msgs.append({
            "sender": m.get("sender", "visitor"),
            "text": m["content"],
            "timestamp": m["timestamp"]
        })

    msgs.sort(key=lambda x: x["timestamp"])
    return {"messages": msgs}

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

    while True:
        try:
            replies = fetch_unread_replies()

            for r in replies:
                sender = r["sender"]
                body = r["body"]
                email = r["visitor"]

                # Gmail replies ALSO mapped to customer
                insert_message(sender, body, email)

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
