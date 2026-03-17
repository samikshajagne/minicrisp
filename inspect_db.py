from pymongo import MongoClient
import os
import re
import json
from datetime import datetime

from bson import ObjectId

# Helper to serialize datetime and ObjectId
class DateTimeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, ObjectId):
            return str(o)
        return super().default(o)

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "mini_crisp_db")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db["email_received"]

# Query: content like "what is the matter" (case insensitive)
query = {"content": {"$regex": "what is the matter", "$options": "i"}}

results = list(collection.find(query))

print(f"Found {len(results)} documents:")
print(json.dumps(results, indent=2, cls=DateTimeEncoder))
