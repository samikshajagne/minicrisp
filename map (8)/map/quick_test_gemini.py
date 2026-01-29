import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
print(f"API Key loaded: {api_key[:10]}..." if api_key else "API Key not found!")

client = genai.Client(api_key=api_key)

print("\nTesting different model name formats...")

# Test 1: gemini-1.5-flash
print("\n1. Testing: gemini-1.5-flash")
try:
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents="Say hello in one word"
    )
    print(f"   ✅ SUCCESS: {response.text}")
except Exception as e:
    print(f"   ❌ FAILED: {str(e)[:150]}")

# Test 2: gemini-1.5-pro
print("\n2. Testing: gemini-1.5-pro")
try:
    response = client.models.generate_content(
        model="gemini-1.5-pro",
        contents="Say hello in one word"
    )
    print(f"   ✅ SUCCESS: {response.text}")
except Exception as e:
    print(f"   ❌ FAILED: {str(e)[:150]}")

# Test 3: gemini-pro
print("\n3. Testing: gemini-pro")
try:
    response = client.models.generate_content(
        model="gemini-pro",
        contents="Say hello in one word"
    )
    print(f"   ✅ SUCCESS: {response.text}")
except Exception as e:
    print(f"   ❌ FAILED: {str(e)[:150]}")
