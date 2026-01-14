from deepgram import DeepgramClient
import asyncio

def test_sync():
    dg = DeepgramClient(api_key='key')
    try:
        # Check if we can use it as a context manager
        socket = dg.listen.v1.connect()
        print(f"Socket object: {socket}")
        print(f"Socket members: {[m for m in dir(socket) if not m.startswith('_')]}")
    except Exception as e:
        print(f"Connect failed: {e}")

if __name__ == "__main__":
    test_sync()
