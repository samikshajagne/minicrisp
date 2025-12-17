
import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import traceback

# Add current directory to path
sys.path.append(os.getcwd())

# --- MOCK DEPENDENCIES START ---
mock_pymongo = MagicMock()
sys.modules["pymongo"] = mock_pymongo
sys.modules["pymongo.errors"] = MagicMock()
sys.modules["pymongo.mongo_client"] = MagicMock()
# --- MOCK DEPENDENCIES END ---

try:
    from email_service import send_admin_and_customer_notifications
except Exception:
    traceback.print_exc()
    sys.exit(1)

class TestEmailThreading(unittest.TestCase):

    @patch('email_service.smtplib')
    @patch('email_service.threads')
    @patch('email_service.ensure_customer')
    @patch('email_service.email_sent')
    def test_threading_logic(self, mock_email_sent, mock_ensure_customer, mock_threads, mock_smtplib):
        try:
            # Setup mocks
            mock_ensure_customer.return_value = {"tb1_id": "test_tb1_id"}
            
            # Mock DB state
            db_state = {} 
            
            def find_one_side_effect(query):
                # print(f"DB Find: {query}")
                email = query.get("visitor_email")
                return db_state.get(email)

            def update_one_side_effect(query, update, upsert=False):
                # print(f"DB Update: {query} with {update}")
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
            print("\n>>> Sending first message...")
            result = send_admin_and_customer_notifications(visitor_email, "Hello 1")
            print(f">>> Result 1: {result}")

            self.assertTrue(mock_server.sendmail.called, "sendmail should be called")
            
            # Inspect calls
            # We expect 2 calls: Admin notification, Customer ack
            self.assertEqual(mock_server.sendmail.call_count, 2, f"Expected 2 emails, got {mock_server.sendmail.call_count}")
            
            # Admin email is first call
            # args: (from, to, msg_string)
            first_call_args = mock_server.sendmail.call_args_list[0]
            msg_string_1 = first_call_args[0][2]
            
            # Simple header extraction
            import email
            msg_1 = email.message_from_string(msg_string_1)
            
            print(f"Msg 1 ID: {msg_1['Message-ID']}")
            print(f"Msg 1 In-Reply-To: {msg_1['In-Reply-To']}")

            self.assertIsNone(msg_1['In-Reply-To'], "First message should not have In-Reply-To")
            first_msg_id = msg_1['Message-ID']
            
            # Check DB updated
            self.assertEqual(db_state[visitor_email]['admin_msgid'], first_msg_id)

            # --- 2. Second Message ---
            print("\n>>> Sending second message...")
            result2 = send_admin_and_customer_notifications(visitor_email, "Hello 2")
            print(f">>> Result 2: {result2}")
            
            # Previous calls + 2 new calls = 4
            self.assertEqual(mock_server.sendmail.call_count, 4, f"Expected 4 emails total, got {mock_server.sendmail.call_count}")
            
            # The 3rd call is the Admin notification for the second message
            third_call_args = mock_server.sendmail.call_args_list[2]
            msg_string_2 = third_call_args[0][2]
            msg_2 = email.message_from_string(msg_string_2)

            print(f"Msg 2 ID: {msg_2['Message-ID']}")
            print(f"Msg 2 In-Reply-To: {msg_2['In-Reply-To']}")
            print(f"Msg 2 References: {msg_2['References']}")

            self.assertEqual(msg_2['In-Reply-To'], first_msg_id, "In-Reply-To MUST match previous Message-ID")
            self.assertEqual(msg_2['References'], first_msg_id, "References MUST match previous Message-ID")
            
            # Verify DB updated with NEW ID
            new_id_in_db = db_state[visitor_email]['admin_msgid']
            self.assertNotEqual(new_id_in_db, first_msg_id, "DB should be updated with new ID")
            self.assertEqual(new_id_in_db, msg_2['Message-ID'], "DB should hold the latest Message-ID")
            
            print("\nSUCCESS: All threading verifications passed!")

        except Exception:
            traceback.print_exc()
            raise

if __name__ == '__main__':
    unittest.main()
