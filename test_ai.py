import requests
import json

def test_ai():
    url = "http://127.0.0.1:8000/api/generate-email"
    payload = {
        "prompt": "Write a professional follow-up email for a web design inquiry."
    }
    headers = {
        "Content-Type": "application/json"
    }

    print(f"Testing AI Generation at {url}...")
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers)
        print(f"Status Code: {response.status_code}")
        
        result = response.json()
        if result.get("status") == "ok":
            print("\n✅ AI Generation SUCCESS!")
            print("-" * 30)
            print("Content Snippet:")
            print(result.get("content")[:500] + ("..." if len(result.get("content")) > 500 else ""))
            print("-" * 30)
        else:
            print(f"\n❌ AI Generation FAILED: {result.get('message')}")
            
    except Exception as e:
        print(f"\n❌ Request Error: {e}")

if __name__ == "__main__":
    test_ai()
