from database import customers
import uuid

def check_and_fix():
    print("Checking customers for missing conversation_id...")
    count = 0
    fixed = 0
    for c in customers.find({}):
        count += 1
        if "conversation_id" not in c:
            print(f"Fixing customer {c.get('cust_email')}...")
            customers.update_one(
                {"_id": c["_id"]},
                {"$set": {"conversation_id": str(uuid.uuid4())}}
            )
            fixed += 1
            
    print(f"Scanned {count} customers. Fixed {fixed} missing conversation_ids.")

if __name__ == "__main__":
    check_and_fix()
