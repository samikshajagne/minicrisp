
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add current directory to path so we can import app modules
sys.path.append(os.getcwd())

# --- MOCK DEPENDENCIES BEFORE IMPORT ---
# We need to mock pymongo because it might not be installed in the test env
# and 'database.py' imports it at top level.
mock_pymongo = MagicMock()
sys.modules["pymongo"] = mock_pymongo
sys.modules["pymongo.errors"] = MagicMock()
sys.modules["pymongo.mongo_client"] = MagicMock()

# We also need to mock database.py itself if we want to avoid its imports
# But email_service imports specific things from it.
# Let's let database be imported but ensure its dependencies are mocked.

from email_service import send_admin_and_customer_notifications

class TestEmailThreading(unittest.TestCase):

    @patch('email_service.smtplib')
    @patch('email_service.threads')
    @patch('email_service.ensure_customer')
    @patch('email_service.email_sent')
    def test_threading_logic(self, mock_email_sent, mock_ensure_customer, mock_threads, mock_smtplib):
        # Setup mocks
        mock_ensure_customer.return_value = {"tb1_id": "test_tb1_id"}
        
        # Mock DB state
        db_state = {} 
        
        def find_one_side_effect(query):
            email = query.get("visitor_email")
            return db_state.get(email)

        def update_one_side_effect(query, update, upsert=False):
            email = query.get("visitor_email")
            if "$set" in update:
                if email not in db_state:
                    db_state[email] = {}
                db_state[email].update(update["$set"])

        mock_threads.find_one.side_effect = find_one_side_effect
        mock_threads.update_one.side_effect = update_one_side_effect

        # Mock SMTP server
        mock_server = MagicMock()
        mock_smtplib.SMTP.return_value = mock_server

        visitor_email = "test@example.com"
        
        # --- 1. First Message ---
        print("\nSending first message...")
        send_admin_and_customer_notifications(visitor_email, "Hello 1")

        # Verify first email sent to admin
        # We need to inspect the call args to validte headers
        # call_args_list[0] is login, [1] is sendmail for admin, [2] is sendmail for customer (approx, depends on implementation details)
        
        # Let's just capture the arguments passed to sendmail
        self.assertTrue(mock_server.sendmail.called)
        first_call_args = mock_server.sendmail.call_args_list[0] # Admin email
        msg_string_1 = first_call_args[0][2]
        
        # Parse the message string to check headers
        # It's a bit strict to parse string, let's just check raw string presence for simplistic verification or use email parser
        from email import message_from_string
        msg_1 = message_from_string(msg_string_1)
        
        print(f"Msg 1 ID: {msg_1['Message-ID']}")
        print(f"Msg 1 In-Reply-To: {msg_1.get('In-Reply-To')}")

        self.assertIsNone(msg_1['In-Reply-To'])
        first_msg_id = msg_1['Message-ID']
        
        # Verify DB was updated
        self.assertEqual(db_state[visitor_email]['admin_msgid'], first_msg_id)

        # --- 2. Second Message ---
        print("\nSending second message...")
        send_admin_and_customer_notifications(visitor_email, "Hello 2")
        
        # Get the new admin email
        # The mock server calls accumulate. 
        # calls: [1st_admin, 1st_cust, 2nd_admin, 2nd_cust]
        third_call_args = mock_server.sendmail.call_args_list[2] # 2nd Admin email
        msg_string_2 = third_call_args[0][2]
        msg_2 = message_from_string(msg_string_2)

        print(f"Msg 2 ID: {msg_2['Message-ID']}")
        print(f"Msg 2 In-Reply-To: {msg_2.get('In-Reply-To')}")

        # VERIFICATION: The second message should reply to the first message ID
        self.assertEqual(msg_2['In-Reply-To'], first_msg_id)
        self.assertEqual(msg_2['References'], first_msg_id)
        
        # Verify DB updated with NEW ID
        self.assertNotEqual(db_state[visitor_email]['admin_msgid'], first_msg_id)
        self.assertEqual(db_state[visitor_email]['admin_msgid'], msg_2['Message-ID'])
        
        print("\nSUCCESS: Threading logic verified!")

if __name__ == '__main__':
    unittest.main()
