
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def test_db_features():
    print("--- Testing AI Database Features ---")

    # 1. Add Note
    print("\n1. Testing Add Note Tool...")
    email = "test_note@example.com"
    note_content = "This is a test note from verification script."
    
    # Simulate AI calling the tool via direct DB check (since tool is internal to AI)
    # We will use the python function directly if possible, but here we can only access API
    # So we will try to ASK the AI to do it.
    
    prompt = f"Add a note to {email} saying '{note_content}'"
    print(f"Prompt: {prompt}")
    
    try:
        res = requests.post(f"{BASE_URL}/api/ai/agent", json={"prompt": prompt})
        print(f"Status: {res.status_code}")
        print(f"Response: {res.json()}")
        
        # Verify in DB
        # We can implement a check script or trust the AI response for now
        # Let's use the 'get_customer_details_tool' via AI to verify
        
        time.sleep(1)
        
        prompt_check = f"Get details for {email}"
        print(f"\n2. Verifying Note via AI: {prompt_check}")
        res = requests.post(f"{BASE_URL}/api/ai/agent", json={"prompt": prompt_check})
        print(f"Response: {res.json()}")
        
    except Exception as e:
        print(f"Error: {e}")

    # 3. Test Disambiguation Logic (Simulated)
    print("\n3. Testing Disambiguation Flow Logic (Simulated)")
    
    # CASE A: EMAIL INTENT
    prompt_email = "Email Samiksha"
    print(f"\nPrompt: {prompt_email}")
    res = requests.post(f"{BASE_URL}/api/ai/agent", json={"prompt": prompt_email})
    data = res.json()
    actions = data.get("actions", [])
    search_action = next((a for a in actions if a.get("action") == "search_customers"), None)
    
    if search_action and search_action.get("purpose") == "email":
        print("✅ PASS: AI inferred purpose='email'")
    else:
        print(f"❌ FAIL: AI Purpose: {search_action.get('purpose') if search_action else 'None'}")

    # CASE B: CHAT INTENT
    prompt_chat = "Open chat with Samiksha"
    print(f"\nPrompt: {prompt_chat}")
    res = requests.post(f"{BASE_URL}/api/ai/agent", json={"prompt": prompt_chat})
    data = res.json()
    actions = data.get("actions", [])
    search_action = next((a for a in actions if a.get("action") == "search_customers"), None)
    
    if search_action and search_action.get("purpose") == "chat":
        print("✅ PASS: AI inferred purpose='chat'")
    else:
        print(f"❌ FAIL: AI Purpose: {search_action.get('purpose') if search_action else 'None'}")

    # CASE C: SUMMARY INTENT
    prompt_summary = "Summarize Samiksha"
    print(f"\nPrompt: {prompt_summary}")
    res = requests.post(f"{BASE_URL}/api/ai/agent", json={"prompt": prompt_summary})
    data = res.json()
    actions = data.get("actions", [])
    search_action = next((a for a in actions if a.get("action") == "search_customers"), None)
    
    if search_action and search_action.get("purpose") == "summary":
        print("✅ PASS: AI inferred purpose='summary'")
    else:
        print(f"❌ FAIL: AI Purpose: {search_action.get('purpose') if search_action else 'None'}")

if __name__ == "__main__":
    test_db_features()
