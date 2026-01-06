import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def test_webhook_verification():
    print("Testing Webhook Verification...")
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "my_secure_token",
        "hub.challenge": "123456789"
    }
    response = requests.get(f"{BASE_URL}/webhook/whatsapp", params=params)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
    assert response.status_code == 200
    assert response.text == "123456789"
    print("Verification Test Passed!\n")

def test_webhook_receiving():
    print("Testing Webhook Receiving...")
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550000000",
                                "phone_number_id": "123456789012345"
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test User"},
                                    "wa_id": "919999999999"
                                }
                            ],
                            "messages": [
                                {
                                    "from": "919999999999",
                                    "id": f"wamid.{int(time.time())}",
                                    "timestamp": str(int(time.time())),
                                    "text": {"body": "Hello from WhatsApp Test!"},
                                    "type": "text"
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }
    
    response = requests.post(f"{BASE_URL}/webhook/whatsapp", json=payload)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    print("Receiving Test Passed!\n")

if __name__ == "__main__":
    try:
        test_webhook_verification()
        test_webhook_receiving()
    except Exception as e:
        print(f"Test failed: {e}")
