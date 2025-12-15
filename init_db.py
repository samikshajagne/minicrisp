from pymongo import MongoClient, ReturnDocument

from database import MONGO_URI, DB_NAME

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# Collections (tables)
customers = db["customers"]
email_sent = db["email_sent"]
email_received = db["email_received"]
threads = db["threads"]
counters = db["counters"]

# Ensure indexes (like SQL constraints)
customers.create_index("cust_email", unique=True)
threads.create_index("visitor_email", unique=True)

# Initialize counter for tb1_id (if missing)
counters.update_one(
    {"_id": "tb1_id"},
    {"$setOnInsert": {"seq": 0}},
    upsert=True
)

print("MongoDB setup complete!")
print("Collections created:")
print(db.list_collection_names())
