from database import get_email_accounts_with_secrets
import pprint

msg = get_email_accounts_with_secrets()
print("--- Accounts in DB ---")
if not msg:
    print("No accounts found in DB.")
else:
    for acc in msg:
        # Hide password partial
        acc['app_password'] = acc['app_password'][:4] + "****" if acc.get('app_password') else "N/A"
        pprint.pprint(acc)
