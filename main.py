from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from email_service import EmailService

import re
import threading
import time
import asyncio
import logging

from gmail_reader import fetch_unread_replies
from email_service import THREAD_IDS   # For mapping Gmail replies to visitor thread

# Logger for Gmail sync
logger = logging.getLogger("gmail_sync")
logger.setLevel(logging.INFO)

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# In-memory DB
MESSAGES = []

# WebSocket connections
CONNECTIONS: dict[str, set[WebSocket]] = {}


# ----------------------------------------
# Helper: identify visitor uniquely
# ----------------------------------------
def visitor_key(email: str | None, guest_id: str | None):
    return email or guest_id


async def broadcast(email: str | None, guest_id: str | None, payload: dict):
    """Send WebSocket update to a visitor."""
    key = visitor_key(email, guest_id)
    if not key:
        return

    sockets = CONNECTIONS.get(key, set()).copy()
    for ws in sockets:
        try:
            await ws.send_json(payload)
        except:
            CONNECTIONS[key].discard(ws)


# ----------------------------------------
# Models
# ----------------------------------------
class SuggestionRequest(BaseModel):
    text: str

class Message(BaseModel):
    text: str
    email: str | None = None
    guest_id: str | None = None

class AdminReply(BaseModel):
    text: str
    visitor_email: str | None = None
    guest_id: str | None = None


# ----------------------------------------
# Routes
# ----------------------------------------
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/admin")
async def admin(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/api/admin/messages")
async def api_admin_messages():
    return {"messages": MESSAGES}


@app.post("/api/suggest")
async def api_suggest(req: SuggestionRequest):
    text = req.text.lower().strip()
    kb = {
        "h": ["Hello", "Hi there", "How can I help?", "Help"],
        "he": ["Hello", "Help me", "Hey"],
        "hel": ["Hello", "Help", "Hello world"],
        "how": ["How are you?", "How does this work?", "How much is it?"],
        "pri": ["Price", "Private", "Privacy policy"],
        "tha": ["Thanks", "Thank you", "That's great"],
        "by": ["Bye", "Bye bye", "See you"]
    }

    if text in kb:
        return {"suggestions": kb[text]}

    suggestions = [v[0] for k, v in kb.items() if k.startswith(text)][:3]
    return {"suggestions": suggestions}


@app.get("/api/prompts")
async def api_prompts():
    return {
        "prompts": [
            "What is your pricing model?",
            "How do I integrate this?",
            "Can I get a demo?",
            "What support options are available?",
            "Is there a free trial?",
            "How secure is my data?"
        ]
    }


@app.get("/api/sync")
async def api_sync(email: str | None = None, guest_id: str | None = None):
    key = email or guest_id
    if not key:
        return {"messages": []}

    msgs = [
        m for m in MESSAGES
        if m.get("recipient") == key or m.get("email") == email or m.get("guest_id") == guest_id
    ]

    return {"messages": msgs}


# ----------------------------------------
# Admin Reply
# ----------------------------------------
@app.post("/api/reply")
async def api_reply(reply: AdminReply):

    target = reply.visitor_email or reply.guest_id
    if not target:
        return {"status": "error", "message": "missing target"}

    msg_obj = {
        "id": len(MESSAGES) + 1,
        "text": reply.text,
        "sender": "admin",
        "email": reply.visitor_email,
        "guest_id": reply.guest_id,
        "recipient": target,
        "timestamp": time.time()
    }

    MESSAGES.append(msg_obj)

    # Email + WebSocket delivery
    EmailService.send_notification(target, reply.text, "admin")
    await broadcast(reply.visitor_email, reply.guest_id, msg_obj)

    return {"status": "ok"}


# ----------------------------------------
# Visitor Message
# ----------------------------------------
@app.post("/api/message")
async def api_message(msg: Message):

    target = msg.email or msg.guest_id

    msg_obj = {
        "id": len(MESSAGES) + 1,
        "text": msg.text,
        "sender": "visitor",
        "email": msg.email,
        "guest_id": msg.guest_id,
        "recipient": target,
        "timestamp": time.time()
    }

    MESSAGES.append(msg_obj)

    EmailService.send_notification(target, msg.text, "guest")
    await broadcast(msg.email, msg.guest_id, msg_obj)

    return {"status": "ok", "message": "Message sent"}


# ----------------------------------------
# WebSocket Handler
# ----------------------------------------
@app.websocket("/ws")
async def websocket_handler(ws: WebSocket, email: str | None = None, guest_id: str | None = None):

    key = visitor_key(email, guest_id)
    if not key:
        await ws.close(code=4000)
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


# ----------------------------------------
# Gmail → Chat Sync Logic
# ----------------------------------------
def _map_thread_to_visitor(in_reply_to):
    """Match Gmail reply via THREAD_IDS."""
    if not in_reply_to:
        return None

    for visitor, thread_id in THREAD_IDS.items():
        if thread_id.strip() == in_reply_to.strip():
            return visitor

    return None


def gmail_poll_loop(poll_interval=5):
    """Runs in background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    while True:
        try:
            replies = fetch_unread_replies()

            for r in replies:
                visitor = _map_thread_to_visitor(r.get("in_reply_to"))

                # fallback subject matching
                if not visitor:
                    subj = r.get("subject", "").lower()
                    # Remove "re:", "fwd:" prefixes to match "conversation with ..."
                    clean_subj = re.sub(r'^(re|fwd|fw):\s*', '', subj).strip()
                    if clean_subj.startswith("conversation with "):
                        visitor = clean_subj.replace("conversation with ", "").strip()

                if not visitor:
                    continue

                msg_obj = {
                    "id": len(MESSAGES) + 1,
                    "text": r["body"],
                    "sender": "admin",
                    "email": visitor if "@" in visitor else None,
                    "guest_id": visitor if "@" not in visitor else None,
                    "recipient": visitor,
                    "timestamp": time.time()
                }

                MESSAGES.append(msg_obj)

                # Broadcast safely from thread
                b_email = msg_obj["email"]
                b_guest = msg_obj["guest_id"]
                loop.call_soon_threadsafe(asyncio.create_task, broadcast(b_email, b_guest, msg_obj))

        except Exception as e:
            logger.exception(f"Gmail sync error: {e}")

        time.sleep(poll_interval)


# Start Gmail Sync Thread
threading.Thread(target=gmail_poll_loop, args=(5,), daemon=True).start()


# ----------------------------------------
# Server Start
# ----------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
