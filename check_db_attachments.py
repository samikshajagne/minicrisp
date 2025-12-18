
from database import email_received
import pprint

print("Checking recent messages for attachments...")
cursor = email_received.find({"attachments": {"$exists": True, "$ne": []}}).sort("timestamp", -1).limit(5)

found = False
for doc in cursor:
    found = True
    with open("db_output.txt", "a") as f:
        f.write(f"\nEmail: {doc.get('email')}\n")
        f.write(f"Time: {doc.get('timestamp')}\n")
        f.write(f"Attachments: {doc.get('attachments')}\n")

if not found:
    with open("db_output.txt", "w") as f:
        f.write("No messages with attachments found in DB.")
