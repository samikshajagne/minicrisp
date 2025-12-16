
import sys
import os
from unittest.mock import MagicMock

sys.path.append(os.getcwd())

# MOCK EVERYTHING
mock_pymongo = MagicMock()
sys.modules["pymongo"] = mock_pymongo
sys.modules["pymongo.errors"] = MagicMock()
sys.modules["pymongo.mongo_client"] = MagicMock()

try:
    import database
    print("Database imported successfully")
except Exception as e:
    print(f"Database import failed: {e}")
    import traceback
    traceback.print_exc()

try:
    import email_service
    print("Email Service imported successfully")
except Exception as e:
    print(f"Email Service import failed: {e}")
    import traceback
    traceback.print_exc()
