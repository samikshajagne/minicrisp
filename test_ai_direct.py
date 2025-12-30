import os
from groq import Groq
from dotenv import load_dotenv

def test_direct_groq():
    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("❌ GROQ_API_KEY not found in .env")
        return

    print(f"Testing direct Groq API with key starting with {api_key[:8]}...")
    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": "Hello, say 'AI is working' if you can read this."}
            ]
        )
        print("\n✅ Groq API SUCCESS!")
        print(f"Response: {completion.choices[0].message.content}")
    except Exception as e:
        print(f"\n❌ Groq API ERROR: {e}")

if __name__ == "__main__":
    test_direct_groq()
