import sys
from unittest.mock import MagicMock, patch

# Mock smtplib to prevent actual email sending
sys.modules["smtplib"] = MagicMock()

# Mock database to prevent actual DB writes
mock_db = MagicMock()
sys.modules["pymongo"] = MagicMock()
sys.modules["database"] = MagicMock()
sys.modules["database"].ensure_customer.return_value = {"tb1_id": 123}

# Import the service to test
from email_service import forward_visitor_message_to_admin

def test_forwarding():
    print("Testing forward_visitor_message_to_admin...")
    with patch("email_service._send_raw", return_value=True) as mock_send:
        result = forward_visitor_message_to_admin("visitor@example.com", "Hello Admin")
        
        if result:
            print("SUCCESS: Function returned True")
        else:
            print("FAILURE: Function returned False")
            
        # Verify arguments
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        print(f"Called _send_raw with: {kwargs}")

if __name__ == "__main__":
    test_forwarding()
