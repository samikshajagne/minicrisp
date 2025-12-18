
import urllib.request
import json
import datetime
from main import insert_message
from database import email_received

# Configuration
API_URL = "http://localhost:8000"
TEST_EMAIL = "test_att@example.com"
TIMESTAMP = datetime.datetime.utcnow()

def test_attachment_flow():
    print(f"Testing attachment flow for {TEST_EMAIL}...")
    
    # 1. Clear previous test data
    email_received.delete_many({"email": TEST_EMAIL})
    
    # 2. Insert message with spoofed attachments directly via function
    attachments = [
        {
            "filename": "test_image.jpg",
            "url": "/static/attachments/test_image.jpg",
            "content_type": "image/jpeg"
        },
        {
            "filename": "document.pdf",
            "url": "/static/attachments/document.pdf",
            "content_type": "application/pdf"
        }
    ]
    
    insert_message(
        sender="visitor",
        text="Check these files",
        visitor_email=TEST_EMAIL,
        origin="test",
        timestamp=TIMESTAMP,
        attachments=attachments
    )
    print("Inserted message with attachments.")
    
    # 3. Fetch from API
    try:
        with urllib.request.urlopen(f"{API_URL}/api/sync?email={TEST_EMAIL}") as response:
            if response.status != 200:
                print(f"API Error: {response.status}")
                return False
            
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"Request failed: {e}")
        return False
        
    messages = data.get("messages", [])
    
    if not messages:
        print("No messages found in API response.")
        return False
        
    last_msg = messages[-1]
    retrieved_atts = last_msg.get("attachments", [])
    
    print(f"Retrieved attachments: {retrieved_atts}")
    
    if len(retrieved_atts) != 2:
        print("Mismatch in attachment count.")
        return False
        
    if retrieved_atts[0]["filename"] == "test_image.jpg":
        print("✅ Attachment 1 verified.")
    else:
        print("❌ Attachment 1 mismatch.")
        
    if retrieved_atts[1]["filename"] == "document.pdf":
        print("✅ Attachment 2 verified.")
    else:
         print("❌ Attachment 2 mismatch.")
         
    return True

if __name__ == "__main__":
    with open("verify_output.txt", "w") as f:
        try:
            if test_attachment_flow():
                f.write("SUCCESS: Attachment flow verified.\n")
                f.flush()
                print("SUCCESS: Attachment flow verified.")
            else:
                f.write("FAILURE: Attachment flow failed.\n")
                f.flush()
                print("FAILURE: Attachment flow failed.")
        except Exception as e:
            f.write(f"Exception: {e}\n")
            f.flush()
            print(f"Exception: {e}")
