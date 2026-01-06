import requests
import json

def test_openai_agent():
    url = "http://127.0.0.1:8000/api/ai/command"
    
    test_prompts = [
        "Give me all the emails from today",
        "Switch the account to ai.intern@cetl.in",
        "Send an email to test@example.com saying hello how are you",
        "Show my unread messages"
    ]
    
    headers = {
        "Content-Type": "application/json"
    }

    print(f"Testing OpenAI Agent at {url}...")
    
    for prompt in test_prompts:
        print(f"\nPrompt: '{prompt}'")
        try:
            response = requests.post(url, data=json.dumps({"text": prompt}), headers=headers)
            print(f"Status Code: {response.status_code}")
            
            result = response.json()
            if result.get("status") == "ok":
                print("[SUCCESS]")
                print("Response:", result.get("response"))
                if result.get("actions"):
                    print("Actions:", json.dumps(result.get("actions"), indent=2))
            else:
                print(f"[FAILED] Message: {result.get('message')}")
        except Exception as e:
            print(f"[ERROR] {e}")

if __name__ == "__main__":
    test_openai_agent()
