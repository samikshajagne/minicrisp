# database.py
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from datetime import datetime
import os

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "mini_crisp_db")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# -----------------------------
# Collections
# -----------------------------
customers = db["customers"]                 # table1
email_sent = db["email_sent"]               # table2_email_sent
email_received = db["email_received"]       # table3_email_received
threads = db["threads"]                     # optional future use
counters = db["counters"]                   # auto-increment counters

# -----------------------------
# Indexes
# -----------------------------
customers.create_index("cust_email", unique=True)
customers.create_index("tb1_id", unique=True)
email_received.create_index("email")
email_received.create_index("tb1_id")
threads.create_index("visitor_email", unique=True)

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
def ensure_customer(email: str, name: str | None = None) -> dict:
    """
    Return customer doc.
    If not exists -> create.
    Always ensures last_seen & last_read_at fields exist.
    """
    if not email:
        raise ValueError("email required")

    email = email.strip().lower()
    now = datetime.utcnow()

    doc = customers.find_one({"cust_email": email})

    if doc:
        # 🔄 Update last_seen
        customers.update_one(
            {"cust_email": email},
            {"$set": {"last_seen": now}}
        )

        # 🧩 Backward compatibility (older customers)
        if "last_read_at" not in doc:
            customers.update_one(
                {"cust_email": email},
                {"$set": {"last_read_at": None}}
            )
            doc["last_read_at"] = None

        doc["last_seen"] = now
        return doc

    # 🆕 Create new customer
    tb1_id = get_next_sequence("tb1_id")
    try:
        customers.insert_one({
            "tb1_id": tb1_id,
            "name": name or "",
            "cust_email": email,
            "created_at": now,
            "last_seen": now,
            "last_read_at": None   # 🔴 required for unread counter
        })
    except DuplicateKeyError:
        return customers.find_one({"cust_email": email})

    return customers.find_one({"cust_email": email})

def get_customer_by_email(email: str) -> dict | None:
    if not email:
        return None
    return customers.find_one({"cust_email": email.strip().lower()})

# -----------------------------
# Unread helpers (NEW)
# -----------------------------
def mark_customer_read(email: str):
    """Mark conversation as read by admin."""
    if not email:
        return

    customers.update_one(
        {"cust_email": email.strip().lower()},
        {"$set": {"last_read_at": datetime.utcnow()}}
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
