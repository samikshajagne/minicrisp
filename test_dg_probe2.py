
import os
import sys

def probe():
    # Check Imports
    found_events = False
    try:
        from deepgram.clients.live.v1 import LiveTranscriptionEvents
        print("EVENTS: deepgram.clients.live.v1")
        found_events = True
    except ImportError:
        pass

    if not found_events:
        try:
            from deepgram import LiveTranscriptionEvents
            print("EVENTS: top_level")
        except ImportError:
            print("EVENTS: Not found")

    # Check Client
    try:
        from deepgram import DeepgramClient
        # Mock init
        try:
            dg = DeepgramClient(api_key="test")
            print("CLIENT: Init Success")
            
            if hasattr(dg, 'listen'):
                l = dg.listen
                print(f"LISTEN_DIR: {[x for x in dir(l) if not x.startswith('_')]}")
                
                if hasattr(l, 'asyncwebsocket'):
                    print("ASYNC: asyncwebsocket")
                elif hasattr(l, 'asynclive'):
                     print("ASYNC: asynclive")
                elif hasattr(l, 'live'):
                     print("ASYNC: live")
            else:
                print("CLIENT: No listen attribute")
                
        except Exception as e:
            print(f"CLIENT: Init Error: {e}")
            
    except ImportError:
        print("CLIENT: Import Error")

if __name__ == "__main__":
    probe()
