
import websockets
import inspect

try:
    sig = inspect.signature(websockets.connect)
    print(f"Signature: {sig}")
except Exception as e:
    print(f"Error: {e}")
