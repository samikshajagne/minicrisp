import logging
import sys

# Configure logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

from gmail_reader import fetch_emails
from database import email_received

print("--- Running fetch_emails() ---")
try:
    results = fetch_emails(criteria="UNSEEN")
    print(f"Fetch complete. Found {len(results)} messages.")
    for r in results:
        print(f"  [MSG] From: {r['visitor']} | Sender: {r['sender']} | Subj: {r['body'][:30]}...")
except Exception as e:
    print(f"CRITICAL FAILURE: {e}")
    import traceback
    traceback.print_exc()

print("--- Done ---")
