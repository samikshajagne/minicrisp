import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERROR: GEMINI_API_KEY not found in .env file")
    exit(1)

print(f"[OK] API Key found: {api_key[:10]}...")

try:
    client = genai.Client(api_key=api_key)
    print("\n[OK] Client initialized successfully")
    
    print("\n[INFO] Attempting to list available models...")
    models = client.models.list()
    
    print("\n" + "="*60)
    print("AVAILABLE GEMINI MODELS:")
    print("="*60)
    
    for model in models:
        print(f"\nModel Name: {model.name}")
        if hasattr(model, 'display_name'):
            print(f"  Display Name: {model.display_name}")
        if hasattr(model, 'description'):
            print(f"  Description: {model.description}")
        if hasattr(model, 'supported_generation_methods'):
            print(f"  Supported Methods: {model.supported_generation_methods}")
    
    print("\n" + "="*60)
    print("\n[TIP] To use a model, update MODEL_NAME in server.py to one of the names above")
    
except Exception as e:
    print(f"\n[ERROR] {e}")
    print("\n[DEBUG] Full error details:")
    import traceback
    traceback.print_exc()
