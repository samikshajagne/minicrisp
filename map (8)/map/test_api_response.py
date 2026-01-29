import requests
import json

# Test the email-history API
response = requests.get('http://localhost:5000/api/email-history')
data = response.json()

print("=" * 50)
print("API Response Test")
print("=" * 50)

if len(data) > 0:
    print(f"\nTotal conversations: {len(data)}")
    print("\nFirst conversation:")
    first = data[0]
    print(json.dumps(first, indent=2))
    
    # Check for has_replies field
    if 'has_replies' in first:
        print("\n✅ has_replies field EXISTS")
        print(f"   Value: {first['has_replies']}")
    else:
        print("\n❌ has_replies field MISSING")
        print("   SERVER NEEDS TO BE RESTARTED!")
    
    # Check other fields
    print(f"\nOther fields:")
    print(f"  - unread_count: {first.get('unread_count', 'MISSING')}")
    print(f"  - message_count: {first.get('message_count', 'MISSING')}")
    print(f"  - email: {first.get('email', 'MISSING')}")
else:
    print("\n❌ NO DATA RETURNED")
