try:
    from openai import OpenAI
    print("✅ OpenAI library is successfully imported.")
except ImportError as e:
    print(f"❌ OpenAI library import FAILED: {e}")
except Exception as e:
    print(f"❌ An error occurred during import: {e}")
