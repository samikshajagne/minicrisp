from pymongo import MongoClient
import os
from database import MONGO_URI, DB_NAME
from passlib.context import CryptContext

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
users = db["users"]

print("Users in DB:")
for u in users.find():
    print(u)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# Verify password
user = users.find_one({"email": "test@admin.com"})
if user:
    print(f"Password 'password123' valid: {pwd_context.verify('password123', user['password_hash'])}")
else:
    print("User test@admin.com not found")
