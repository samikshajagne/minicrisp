
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def probe():
    print("--- Probing Deepgram SDK ---")
    
    # 1. Imports
    try:
        from deepgram import DeepgramClient
        print("✅ DeepgramClient found in top level")
    except ImportError:
        print("❌ DeepgramClient NOT found in top level")

    try:
        from deepgram import LiveTranscriptionEvents
        print("✅ LiveTranscriptionEvents found in top level")
    except ImportError:
        print("❌ LiveTranscriptionEvents NOT found in top level")
        # Try submodules
        try:
             from deepgram.clients.live.v1 import LiveTranscriptionEvents
             print("✅ LiveTranscriptionEvents found in deepgram.clients.live.v1")
        except ImportError:
             print("❌ LiveTranscriptionEvents NOT found anywhere known")

    try:
        from deepgram import LiveOptions
        print("✅ LiveOptions found in top level")
    except ImportError:
        print("❌ LiveOptions NOT found in top level")
        try:
             from deepgram.options import LiveOptions
             print("✅ LiveOptions found in deepgram.options")
        except ImportError:
             pass

    # 2. Method Inspection
    try:
        dg = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
        print("\n--- DeepgramClient Inspection ---")
        if hasattr(dg, 'listen'):
            print("Has .listen")
            if hasattr(dg.listen, 'asyncwebsocket'):
                 print("Has .listen.asyncwebsocket")
            else:
                 print(f".listen members: {[x for x in dir(dg.listen) if not x.startswith('_')]}")
            
            if hasattr(dg.listen, 'live'):
                 print("Has .listen.live")
        else:
            print("No .listen attribute")
            
    except Exception as e:
        print(f"Client init error: {e}")

if __name__ == "__main__":
    asyncio.run(probe())
