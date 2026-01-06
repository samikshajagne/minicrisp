import os
from dotenv import load_dotenv
from openai import OpenAI
import json

load_dotenv(override=True)
api_key = os.environ.get("OPENAI_API_KEY")

if not api_key:
    print("OPENAI_API_KEY is missing from environment.")
else:
    # Print masked key for verification
    masked_key = api_key[:8] + "..." + api_key[-4:]
    print(f"Key found: {masked_key}")
    
    try:
        client = OpenAI(api_key=api_key)
        print("Attempting a simple completion call...")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Say hello!"}],
            max_tokens=5
        )
        print("SUCCESS! Response received.")
        print(f"Content: {response.choices[0].message.content}")
    except Exception as e:
        print(f"FAILED: {str(e)}")
