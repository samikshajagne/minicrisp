from fastapi.testclient import TestClient
from main import app, login_required
import email_service
from unittest.mock import MagicMock
import sys

sys.stdout = open('verify_output.txt', 'w', encoding='utf-8')
sys.stderr = sys.stdout

client = TestClient(app)

# Override auth
def mock_login_required():
    return "testuser@example.com"

app.dependency_overrides[login_required] = mock_login_required

from unittest.mock import patch

def test_send_attachment():
    with patch('main.send_reply_from_admin_to_customer') as mock_send:
        mock_send.return_value = True

        # Simulate FormData
        files = [
            ('files', ('test.txt', b'Hello World Content', 'text/plain'))
        ]
        data = {
            'visitor_email': 'visitor@example.com',
            'text': 'Here is a file',
            'subject': 'Test Attachment'
        }
        
        print("Sending request to /api/reply...")
        response = client.post("/api/reply", data=data, files=files)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 200:
            # Verify mock call
            print("Verifying email service call...")
            if mock_send.call_args:
                args, kwargs = mock_send.call_args
                
                # Verify 'attachments' argument
                # Note: kwargs might be empty if args were used. 
                # Our function signature has keyword args, but we called it with positional args in main.py? 
                # Let's check main.py call.
                # send_reply_from_admin_to_customer(visitor_email, text, account_email=..., ...)
                # So first 2 are positional, others keyword.
                
                attachments = kwargs.get('attachments')
                if attachments:
                    print("SUCCESS: Attachments received in service!")
                    for att in attachments:
                        print(f" - Filename: {att['filename']}")
                        print(f" - Content Type: {att['content_type']}")
                        print(f" - Content Length: {len(att['content'])}")
                else:
                    print(f"FAILURE: No attachments in service call. Args: {args}, Kwargs: {kwargs.keys()}")
            else:
                print("FAILURE: Service was not called.")
        else:
            print("FAILURE: API request failed.")

import traceback

if __name__ == "__main__":
    try:
        test_send_attachment()
    except Exception as e:
        traceback.print_exc()
