from database import email_received
from datetime import timezone

def verify():
    msg = email_received.find_one()
    if not msg:
        print("No messages found in DB.")
        return
    
    ts = msg.get("timestamp")
    print(f"Timestamp: {ts}")
    print(f"Type: {type(ts)}")
    print(f"Tzinfo: {ts.tzinfo}")
    
    if ts.tzinfo is None:
        print("FAIL: Timestamp is NAIVE (no timezone).")
    else:
        print("SUCCESS: Timestamp is AWARE.")

if __name__ == "__main__":
    verify()
