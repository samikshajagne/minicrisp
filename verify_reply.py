import requests

def verify_reply():
    url = "http://127.0.0.1:8000/api/reply"
    
    # Mock data
    data = {
        "visitor_email": "test@example.com",
        "text": "Hello this is a test with attachment",
        "subject": "Test Attachment Verification",
        "html_content": "<p>Hello this is a <b>test</b> with attachment</p>"
    }
    
    # Create a dummy file
    files = [
        ('files', ('test.txt', b'Hello world attachment', 'text/plain'))
    ]
    
    print(f"Sending POST to {url} with attachment...")
    try:
        response = requests.post(url, data=data, files=files)
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify_reply()
