# database.py
from pymongo import MongoClient, ReturnDocument
from gridfs import GridFS
from pymongo.errors import DuplicateKeyError
from datetime import datetime, timezone
import os
import uuid

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "mini_crisp_db")

client = MongoClient(MONGO_URI, tz_aware=True)
db = client[DB_NAME]
fs = GridFS(db)

# -----------------------------
# Collections
# -----------------------------
customers = db["customers"]                 # table1
email_sent = db["email_sent"]               # table2_email_sent
email_received = db["email_received"]       # table3_email_received
threads = db["threads"]                     # optional future use
counters = db["counters"] 
email_accounts = db.email_accounts
whatsapp_accounts = db["whatsapp_accounts"]
social_accounts = db["social_accounts"]
ai_history = db["ai_history"] # Store AI interactions
# auto-increment counters

# -----------------------------
# Indexes
# -----------------------------
# Drop existing non-sparse index if it exists to allow update
try:
    customers.drop_index("cust_email_1")
except Exception:
    pass

customers.create_index("cust_email", unique=True, sparse=True)
customers.create_index("phone", unique=True, sparse=True)
customers.create_index("tb1_id", unique=True)
email_received.create_index("email")
email_received.create_index("tb1_id")
email_received.create_index("timestamp")
email_received.create_index("message_id", unique=True, sparse=True)
email_received.create_index([("tb1_id", 1), ("timestamp", -1)]) # Composite for faster conversation list
threads.create_index("visitor_email", unique=True)
whatsapp_accounts.create_index("phone_number_id", unique=True)
social_accounts.create_index("account_id", unique=True)
ai_history.create_index("timestamp", expireAfterSeconds=60*60*24*30) # Keep history for 30 days


# -----------------------------
# Auto-increment helper
# -----------------------------
def get_next_sequence(name: str) -> int:
    """Auto-increment counter for tb1_id."""
    doc = counters.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return int(doc["seq"])

# -----------------------------
# Customer helpers
# -----------------------------
def ensure_customer(email: str | None = None, name: str | None = None, phone: str | None = None, refresh_last_seen: bool = True) -> dict:
    """
    Return customer doc.
    If not exists -> create.
    Always ensures last_seen & last_read_at fields exist.
    Can identify by email OR phone.
    """
    if not email and not phone:
        raise ValueError("email or phone required")

    email = email.strip().lower() if email else None
    now = datetime.now(timezone.utc)

    # Try finding by email
    doc = None
    if email:
        doc = customers.find_one({"cust_email": email})
    
    # Try finding by phone if email search failed or was not provided
    if not doc and phone:
        doc = customers.find_one({"phone": phone})

    if doc:
        # 🔄 Update last_seen
        if refresh_last_seen:
            customers.update_one(
                {"_id": doc["_id"]},
                {"$set": {"last_seen": now}}
            )

        # 🧩 Backward compatibility (older customers)
        if "last_read_at" not in doc:
            customers.update_one(
                {"_id": doc["_id"]},
                {"$set": {"last_read_at": None}}
            )
            doc["last_read_at"] = None

        if "conversation_id" not in doc:
             new_conv_id = str(uuid.uuid4())
             customers.update_one(
                 {"_id": doc["_id"]},
                 {"$set": {"conversation_id": new_conv_id}}
             )
             doc["conversation_id"] = new_conv_id

        doc["last_seen"] = now
        return doc

    # 🆕 Create new customer
    tb1_id = get_next_sequence("tb1_id")
    customer_data = {
        "tb1_id": tb1_id,
        "name": name or "",
        "created_at": now,
        "last_seen": now,
        "created_at": now,
        "last_seen": now,
        "last_read_at": None,
        "conversation_id": str(uuid.uuid4()) # Persistent Conversation ID
    }
    if email:
        customer_data["cust_email"] = email
    if phone:
        customer_data["phone"] = phone

    try:
        customers.insert_one(customer_data)
        return customer_data
    except DuplicateKeyError:
        # In case of race condition, try fetching again
        if email:
            return customers.find_one({"cust_email": email})
        if phone:
            return customers.find_one({"phone": phone})
    
    return customers.find_one({"tb1_id": tb1_id})

def get_whatsapp_accounts():
    """List all configured WhatsApp business accounts."""
    return list(whatsapp_accounts.find({}, {"_id": 0}))

def add_whatsapp_account(phone_number_id: str, access_token: str, display_phone_number: str):
    """Register a new WhatsApp Business account."""
    whatsapp_accounts.update_one(
        {"phone_number_id": phone_number_id},
        {"$set": {
            "phone_number_id": phone_number_id,
            "access_token": access_token,
            "display_phone_number": display_phone_number,
            "active": True,
            "created_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )

def get_social_accounts():
    """List all configured social media accounts (Instagram, Facebook)."""
    return list(social_accounts.find({}, {"_id": 0}))

def add_social_account(account_id: str, access_token: str, platform: str, display_name: str):
    """Register a new social media account (Facebook Page or Instagram)."""
    social_accounts.update_one(
        {"account_id": account_id},
        {"$set": {
            "account_id": account_id,
            "access_token": access_token,
            "platform": platform, # 'instagram' or 'facebook'
            "display_name": display_name,
            "active": True,
            "created_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )

def get_customer_by_email(email: str) -> dict | None:
    if not email:
        return None
    return customers.find_one({"cust_email": email.strip().lower()})

def search_customers(query: str) -> list:
    """Fuzzy search for customers by name, email, or phone."""
    if not query:
        return []
    # Simple regex search across relevant fields
    regex = {"$regex": query, "$options": "i"}
    curr = customers.find({
        "$or": [
            {"name": regex},
            {"cust_email": regex},
            {"phone": regex}
        ]
    }).limit(5)
    return list(curr)

def get_all_messages_for_customer(email: str) -> list:
    """Fetch all messages (received and sent) for a specific customer."""
    cust = get_customer_by_email(email)
    if not cust:
        return []
    
    # Received messages (from visitor)
    received = list(email_received.find({"tb1_id": cust["tb1_id"]}).sort("timestamp", 1))
    
    # Sent messages (from admin)
    sent = list(email_sent.find({"cust_email": email.strip().lower()}).sort("timestamp", 1))
    
    # Combine and sort by timestamp
    all_msgs = []
    for m in received:
        all_msgs.append({
            "sender": "visitor",
            "content": m.get("content", ""),
            "timestamp": m.get("timestamp"),
            "subject": m.get("subject", "")
        })
    for m in sent:
        all_msgs.append({
            "sender": "admin",
            "content": m.get("content", ""),
            "timestamp": m.get("timestamp"),
            "subject": m.get("subject", "")
        })
    
    all_msgs.sort(key=lambda x: x["timestamp"] if x["timestamp"] else datetime.min.replace(tzinfo=timezone.utc))
    return all_msgs

# -----------------------------
# Unread helpers (NEW)
# -----------------------------

def get_email_accounts():
    """Public safe list (no passwords)."""
    return list(email_accounts.find({}, {"app_password": 0, "_id": 0}))

def get_email_accounts_with_secrets():
    """Private full list (with passwords) for Sync."""
    return list(email_accounts.find({}))

def add_email_account(data):
    email_accounts.insert_one({
        "email": data["email"].lower(),
        "imap_host": data["imap_host"],
        "imap_port": data.get("imap_port", 993),
        "username": data["username"],
        "app_password": data["app_password"],
        "active": True,
        "created_at": datetime.now(timezone.utc)
    })

def mark_customer_read(email: str):
    """Mark conversation as read by admin."""
    if not email:
        return

    customers.update_one(
        {"cust_email": email.strip().lower()},
        {"$set": {"last_read_at": datetime.now(timezone.utc)}}
    )

def get_unread_count(tb1_id: int) -> int:
    """
    Count unread visitor messages for a customer.
    """
    customer = customers.find_one({"tb1_id": tb1_id})
    if not customer:
        return 0

    last_read = customer.get("last_read_at")

    query = {
        "tb1_id": tb1_id,
        "sender": "visitor"
    }

    if last_read:
        query["timestamp"] = {"$gt": last_read}

    return email_received.count_documents(query)

# -----------------------------
# User/Auth Model (NEW)
# -----------------------------
users = db["users"]
users.create_index("email", unique=True)

def create_user(email: str, password_hash: str):
    """Create a new admin user."""
    users.insert_one({
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "created_at": datetime.now(timezone.utc)
    })

def get_user_by_email(email: str):
    """Fetch user by email."""
    if not email:
        return None
    return users.find_one({"email": email.strip().lower()})
    return users.find_one({"email": email.strip().lower()})

# -----------------------------
# Customer Notes & Tags
# -----------------------------
def add_note(email: str, content: str, author: str = "AI"):
    if not email or not content: return None
    note = {
        "content": content, 
        "author": author, 
        "timestamp": datetime.now(timezone.utc)
    }
    customers.update_one(
        {"cust_email": email.strip().lower()},
        {"$push": {"notes": note}}
    )
    return note

def get_notes(email: str):
    if not email: return []
    cust = customers.find_one({"cust_email": email.strip().lower()})
    return cust.get("notes", []) if cust else []

def add_tag(email: str, tag: str):
    if not email or not tag: return
    customers.update_one(
        {"cust_email": email.strip().lower()},
        {"$addToSet": {"tags": tag.strip()}}
    )

def get_tags(email: str):
    cust = customers.find_one({"cust_email": email.strip().lower()})
    return cust.get("tags", []) if cust else []

# -----------------------------
# AI History
# -----------------------------
def save_ai_interaction(prompt: str, response: str, tools_used: list = None):
    ai_history.insert_one({
        "prompt": prompt,
        "response": response,
        "tools": tools_used or [],
        "timestamp": datetime.now(timezone.utc)
    })

def get_recent_ai_history(limit: int = 5):
    """Get recent context from DB to inject into prompt."""
    return list(ai_history.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit))
