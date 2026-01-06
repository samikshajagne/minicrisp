import os
from dotenv import load_dotenv

# Try to load .env from current directory
print("Loading .env...")
load_dotenv()

key = os.environ.get("OPENAI_API_KEY")
if key:
    print(f"✅ OPENAI_API_KEY is found in environment.")
    print(f"Length: {len(key)}")
    print(f"Starts with: {key[:5]}...")
else:
    print("❌ OPENAI_API_KEY NOT found in environment.")

# Check files in CWD
print(f"Files in CWD: {os.listdir('.')}")
if ".env" in os.listdir('.'):
    print(".env file exists in CWD.")
else:
    print(".env file NOT found in CWD.")
