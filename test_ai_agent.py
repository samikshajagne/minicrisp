import requests
import json

def test_ai_agent():
    url = "http://127.0.0.1:8000/api/ai/agent"
    
    test_prompts = [
        "Give me all the emails from today",
        "Switch the account to ai.intern@cetl.in",
        "Hello, how can you help me?"
    ]
    
    headers = {
        "Content-Type": "application/json"
    }

    print(f"Testing AI Agent at {url}...")
    
    for prompt in test_prompts:
        print(f"\nPrompt: '{prompt}'")
        try:
            response = requests.post(url, data=json.dumps({"prompt": prompt}), headers=headers)
            print(f"Status Code: {response.status_code}")
            
            result = response.json()
            if result.get("status") == "ok":
                print("✅ Success!")
                print("Response:", result.get("response"))
                if result.get("actions"):
                    print("Actions:", result.get("actions"))
            else:
                print(f"❌ Failed: {result.get('message')}")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_ai_agent()
