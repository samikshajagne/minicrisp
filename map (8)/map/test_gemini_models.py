import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("Listing available Gemini models...")
try:
    # List available models
    models = client.models.list()
    print("\nAvailable models:")
    for model in models:
        print(f"  - {model.name}")
        if hasattr(model, 'supported_generation_methods'):
            print(f"    Supported methods: {model.supported_generation_methods}")
except Exception as e:
    print(f"Error listing models: {e}")

# Test if we can generate content with gemini-1.5-flash
print("\n\nTesting gemini-1.5-flash...")
try:
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents="Say hello"
    )
    print(f"✅ Success! Response: {response.text}")
except Exception as e:
    print(f"❌ Error: {e}")
