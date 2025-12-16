import pymongo
import os
import sys

# Configure logging
try:
    from database import email_received, email_accounts, threads, ensure_customer
    print("--- DB Connection Successful ---")
    
    # Check total counts
    total = email_received.count_documents({})
    print(f"Total messages in email_received: {total}")
    
    print("\n--- Last 10 Messages ---")
    cursor = email_received.find({}).sort("timestamp", -1).limit(10)
    for m in cursor:
        print(f"[{m.get('timestamp')}] From: {m.get('email')} | Sender: {m.get('sender')} | Content: {m.get('content')[:50]}...")

    print("\n--- Email Accounts ---")
    for acc in email_accounts.find({}):
        print(f"Account: {acc.get('email')}")

except ImportError:
    print("Could not import database.py. Make sure you run this with the venv python.")
except Exception as e:
    print(f"Error: {e}")
