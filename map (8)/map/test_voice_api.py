
import requests
import json
import sys

def log(msg):
    print(msg)
    with open("test_result.txt", "a") as f:
        f.write(msg + "\n")

try:
    log("Checking imports...")
    import google.genai
    import dotenv
    log("Imports successful.")
except ImportError as e:
    log(f"Import failed: {e}")
    sys.exit(1)

url = "http://localhost:5000/api/voice-search"
payload = {"query": "Chemical companies in Mumbai"}
headers = {"Content-Type": "application/json"}

try:
    log(f"Connecting to {url}...")
    response = requests.post(url, json=payload, headers=headers)
    log(f"Status Code: {response.status_code}")
    log("Response JSON:")
    log(json.dumps(response.json(), indent=2))
except Exception as e:
    log(f"Connection Error: {e}")
