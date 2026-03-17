from pymongo import MongoClient
import os

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "mini_crisp_db")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db["email_received"]

print("Starting duplicate cleanup...")

# Find all message_ids with more than 1 entry
pipeline = [
    {
        "$group": {
            "_id": "$message_id",
            "count": {"$sum": 1},
            "docs": {"$push": {"_id": "$_id", "sender": "$sender", "timestamp": "$timestamp"}}
        }
    },
    {
        "$match": {
            "count": {"$gt": 1},
            "_id": {"$ne": None} # Ignore docs without message_id
        }
    }
]

duplicates = list(collection.aggregate(pipeline))
print(f"Found {len(duplicates)} duplicate sets.")

deleted_count = 0

for dup in duplicates:
    msg_id = dup["_id"]
    docs = dup["docs"]
    
    # Check for "Mixed" sender case (Visitor vs Admin copy)
    visitor_doc = next((d for d in docs if d.get("sender") == "visitor"), None)
    admin_doc = next((d for d in docs if d.get("sender") == "admin"), None)
    
    if visitor_doc and admin_doc:
        # Rule: Keep Visitor, Delete Admin
        print(f"Fixing Mixed Duplicate for ID {msg_id}: Deleting Admin copy {_id}")
        collection.delete_one({"_id": admin_doc["_id"]})
        deleted_count += 1
    else:
        # If both are same sender (e.g. 2 admin copies), keep the earliest one?
        # Or just keep the one with 'api' source?
        # Default: Keep first, delete others.
        print(f"Fixing Same-Sender Duplicate for ID {msg_id}")
        # Sort by timestamp (keep earliest?) OR just keep first found
        # Usually checking `source` is better, but here we just dedup by ID.
        docs.sort(key=lambda x: x.get("timestamp") or "")
        
        # Keep the FIRST one, delete rest
        to_delete = docs[1:]
        for d in to_delete:
            collection.delete_one({"_id": d["_id"]})
            deleted_count += 1

print(f"Cleanup complete. Deleted {deleted_count} duplicate documents.")
