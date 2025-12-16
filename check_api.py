import urllib.request
import json
import time

try:
    print("Fetching /api/admin/messages...")
    with urllib.request.urlopen("http://localhost:8000/api/admin/messages") as response:
        data = json.loads(response.read().decode())
        msgs = data.get("messages", [])
        print(f"API returned {len(msgs)} conversations.")
        for m in msgs[:5]:
            print(f"  Email: {m['email']} | Last: {m['last_message'][:30]}... | Time: {m['timestamp']}")
except Exception as e:
    print(f"API Check Failed: {e}")
