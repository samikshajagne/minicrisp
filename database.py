# database.py
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from datetime import datetime
import os

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "mini_crisp_db")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# Collections
customers = db["customers"]         # table1
email_sent = db["email_sent"]       # table2_email_sent
email_received = db["email_received"]  # table3_email_recieved
threads = db["threads"]             # store admin/customer message-ids per visitor
counters = db["counters"]           # for auto-increment tb1_id

# Ensure indexes
customers.create_index("cust_email", unique=True)
threads.create_index("visitor_email", unique=True)

def get_next_sequence(name: str) -> int:
    """Auto-increment counter for tb1_id, using a counters collection."""
    doc = counters.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return int(doc["seq"])

def ensure_customer(email: str, name: str | None = None) -> dict:
    """Return customer doc, create if missing with auto-increment tb1_id."""
    if not email:
        raise ValueError("email required")

    email = email.strip().lower()
    doc = customers.find_one({"cust_email": email})
    if doc:
        return doc

    # create new customer
    tb1_id = get_next_sequence("tb1_id")
    try:
        res = customers.insert_one({
            "tb1_id": tb1_id,
            "name": name or "",
            "cust_email": email,
            "created_at": datetime.utcnow()
        })
    except DuplicateKeyError:
        doc = customers.find_one({"cust_email": email})
        return doc

    return customers.find_one({"cust_email": email})

def get_customer_by_email(email: str) -> dict | None:
    if not email:
        return None
    return customers.find_one({"cust_email": email.strip().lower()})
