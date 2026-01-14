import os
import asyncio
from deepgram import DeepgramClient
from dotenv import load_dotenv

load_dotenv()

async def inspect():
    try:
        dg = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
        print("DeepgramClient created")
        print(f"dg.listen type: {type(dg.listen)}")
        print(f"dg.listen dir: {[m for m in dir(dg.listen) if not m.startswith('_')]}")
        
        if hasattr(dg.listen, 'asyncwebsocket'):
             print("Has asyncwebsocket")
             print(f"asyncwebsocket dir: {[m for m in dir(dg.listen.asyncwebsocket) if not m.startswith('_')]}")
        elif hasattr(dg.listen, 'asynclive'):
             print("Has asynclive")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(inspect())
