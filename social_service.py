import logging
import httpx
import os
from datetime import datetime, timezone
from database import social_accounts, ensure_customer

logger = logging.getLogger("social_service")
logger.setLevel(logging.INFO)
fh = logging.FileHandler("debug_log.txt")
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)

GRAPH_VERSION = "v18.0"
FACEBOOK_GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

async def send_social_message(account_id: str, recipient_id: str, text: str, platform: str):
    """
    Sends a message to Instagram or Facebook Messenger.
    """
    account = social_accounts.find_one({"account_id": account_id})
    if not account:
        logger.error(f"Social account {account_id} not found.")
        return False

    access_token = account["access_token"]
    url = f"{FACEBOOK_GRAPH_URL}/{account_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            logger.info(f"{platform.capitalize()} message sent to {recipient_id} via {account_id}")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"{platform.capitalize()} API error: {e.response.text}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error sending {platform}: {e}")
            return False

def process_social_payload(payload):
    """
    Parses Facebook Messenger and Instagram Direct webhook payloads.
    """
    try:
        entries = payload.get("entry", [])
        if not entries:
            return None
            
        entry = entries[0]
        account_id = entry.get("id") # Page ID or Instagram Business Account ID
        messaging = entry.get("messaging", [])
        if not messaging:
            return None
            
        event = messaging[0]
        sender_id = event.get("sender", {}).get("id")
        recipient_id = event.get("recipient", {}).get("id")
        message = event.get("message", {})
        
        if not message or "text" not in message:
            return None
            
        text = message.get("text", "")
        message_id = message.get("mid")
        ts_raw = event.get("timestamp")
        timestamp = datetime.fromtimestamp(ts_raw / 1000.0, tz=timezone.utc) if ts_raw else datetime.now(timezone.utc)
        
        # Determine platform based on payload structure or account_id lookup
        # Typically, Instagram payloads have 'instagram_id' or similar, but Page ID lookup is safer.
        account = social_accounts.find_one({"account_id": account_id})
        platform = account.get("platform", "facebook") if account else "facebook"

        return {
            "account_id": account_id,
            "sender_id": sender_id,
            "text": text,
            "message_id": message_id,
            "timestamp": timestamp,
            "platform": platform,
            "source": platform
        }
    except Exception as e:
        logger.error(f"Failed to parse social payload: {e}")
        return None
