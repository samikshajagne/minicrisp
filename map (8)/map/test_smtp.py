
import os
import smtplib
from dotenv import load_dotenv

def test_smtp():
    print("📧 Testing SMTP Configuration...")
    
    # Reload environment variables
    load_dotenv(override=True)
    
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    
    print(f"\nConfiguration Check:")
    print(f"  HOST: {smtp_host}")
    print(f"  PORT: {smtp_port}")
    print(f"  USER: {smtp_user}")
    print(f"  PASS: {'*' * 8 if smtp_password else 'NOT SET'}")
    
    if not all([smtp_host, smtp_port, smtp_user, smtp_password]):
        print("\n❌ Missing configuration! Please check your .env file.")
        return False
        
    try:
        print(f"\n🔌 Connecting to {smtp_host}:{smtp_port}...")
        server = smtplib.SMTP(smtp_host, int(smtp_port))
        server.starttls()
        
        print("🔐 Logging in...")
        server.login(smtp_user, smtp_password)
        
        print("\n✅ SUCCESS! SMTP credentials are valid.")
        server.quit()
        return True
        
    except Exception as e:
        print(f"\n❌ FAILED: {str(e)}")
        if "Username and Password not accepted" in str(e):
            print("\n💡 TIP: If using Gmail, make sure you are using an 'App Password', not your login password.")
        return False

if __name__ == "__main__":
    test_smtp()
