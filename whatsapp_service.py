import logging
import httpx
import os
from datetime import datetime, timezone
from database import whatsapp_accounts, ensure_customer

logger = logging.getLogger("whatsapp_service")
logger.setLevel(logging.INFO)
fh = logging.FileHandler("debug_log.txt") # Log to same file for convenience
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)

WHATSAPP_VERSION = "v18.0"
FACEBOOK_GRAPH_URL = f"https://graph.facebook.com/{WHATSAPP_VERSION}"

async def send_whatsapp_text(business_phone_number_id: str, to_phone: str, text: str):
    """
    Sends a text message using the WhatsApp Business Cloud API.
    """
    account = whatsapp_accounts.find_one({"phone_number_id": business_phone_number_id})
    if not account:
        logger.error(f"WhatsApp account {business_phone_number_id} not found in database.")
        return False

    access_token = account["access_token"]
    url = f"{FACEBOOK_GRAPH_URL}/{business_phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "text",
        "text": {"body": text}
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            logger.info(f"WhatsApp message sent to {to_phone} via {business_phone_number_id}")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"WhatsApp API error: {e.response.text}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error sending WhatsApp: {e}")
            return False

async def upload_media(business_phone_number_id: str, file_content: bytes, mime_type: str, filename: str) -> str:
    """
    Uploads media to WhatsApp Cloud API and returns the Media ID.
    """
    account = whatsapp_accounts.find_one({"phone_number_id": business_phone_number_id})
    if not account:
        logger.error(f"WhatsApp account {business_phone_number_id} not found.")
        return None

    access_token = account["access_token"]
    url = f"{FACEBOOK_GRAPH_URL}/{business_phone_number_id}/media"
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    # Messaging Product must be passed as form data
    data = {
        "messaging_product": "whatsapp"
    }
    
    files = {
        "file": (filename, file_content, mime_type)
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()
            return response.json().get("id")
        except Exception as e:
            logger.error(f"Failed to upload media to WhatsApp: {e}")
            if hasattr(e, "response"):
                logger.error(f"Meta Reponse: {e.response.text}")
            return None

async def send_whatsapp_media(business_phone_number_id: str, to_phone: str, media_type: str, media_id: str, caption: str = None):
    """
    Sends a media message (image, document, audio, video).
    """
    account = whatsapp_accounts.find_one({"phone_number_id": business_phone_number_id})
    if not account: return False

    access_token = account["access_token"]
    url = f"{FACEBOOK_GRAPH_URL}/{business_phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Map mime-types/internal types to WhatsApp types
    # Allowed: image, document, audio, video, sticker
    if media_type not in ["image", "document", "audio", "video", "sticker"]:
        media_type = "document" # Fallback

    media_obj = {"id": media_id}
    if caption:
        media_obj["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": media_type,
        media_type: media_obj
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            logger.info(f"WhatsApp media ({media_type}) sent to {to_phone}")
            return True
        except Exception as e:
            logger.error(f"WhatsApp Media Send Error: {e}")
            if hasattr(e, "response"):
                logger.error(f"Meta Response: {e.response.text}")
            return False

async def download_media_bytes(media_id: str, access_token: str):
    """
    Downloads media binary from WhatsApp Cloud API.
    """
    async with httpx.AsyncClient() as client:
        try:
            # 1. Get Media URL
            url_res = await client.get(f"{FACEBOOK_GRAPH_URL}/{media_id}", headers={"Authorization": f"Bearer {access_token}"})
            url_res.raise_for_status()
            media_url = url_res.json().get("url")
            
            if not media_url: return None, None
            
            # 2. Download Content
            media_res = await client.get(media_url, headers={"Authorization": f"Bearer {access_token}"})
            media_res.raise_for_status()
            
            return media_res.content, media_res.headers.get("Content-Type")
        except Exception as e:
            logger.error(f"Error downloading media {media_id}: {e}")
            return None, None

def verify_webhook(hub_mode, hub_token, hub_challenge):
    """
    Verifies the webhook subscription with Meta.
    """
    # In a real app, this verify token should be stored in .env
    VERIFY_TOKEN = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "my_secure_token")
    
    if hub_mode == "subscribe" and hub_token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully.")
        return int(hub_challenge)
    return None

def process_whatsapp_payload(payload):
    """
    Production-grade parser for Meta's WhatsApp Cloud API webhook payloads.
    Captures phone_number_id and display_phone_number automatically.
    """
    try:
        # 1. Drill down to the 'value' object which contains the juice
        entries = payload.get("entry", [])
        if not entries:
            return None
            
        entry = entries[0]
        changes = entry.get("changes", [])
        if not changes:
            return None
            
        value = changes[0].get("value", {})
        
        # 2. Extract Business Metadata (Source of True ID)
        metadata = value.get("metadata", {})
        business_number_id = metadata.get("phone_number_id")
        display_phone_number = metadata.get("display_phone_number")
        
        # 3. Check for messages (ignore status updates like 'delivered' for now)
        if "messages" not in value:
            return None

        message = value["messages"][0]
        contact = value.get("contacts", [{}])[0]
        
        # 4. Extract Visitor / Message Details
        visitor_phone = message.get("from")
        visitor_name = contact.get("profile", {}).get("name", visitor_phone)
        message_id = message.get("id")
        
        # Convert timestamp
        ts_raw = message.get("timestamp")
        timestamp = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc) if ts_raw else datetime.now(timezone.utc)
        
        # 5. Extract Content
        text = ""
        attachments = []
        msg_type = message.get("type", "text")
        
        if msg_type == "text":
            text = message.get("text", {}).get("body", "")
            
        elif msg_type in ["image", "video", "audio", "document", "sticker"]:
            node = message.get(msg_type, {})
            media_id = node.get("id")
            caption = node.get("caption", "")
            mime_type = node.get("mime_type", "")
            # Document has filename
            filename = node.get("filename", f"{msg_type}_{media_id}.{mime_type.split('/')[-1]}")
            
            # For images/video/sticker, assume generic extension if not present
            if "." not in filename:
                ext = mime_type.split('/')[-1]
                filename = f"{msg_type}_{media_id}.{ext}"

            attachments.append({
                "whatsapp_id": media_id,
                "filename": filename,
                "mime_type": mime_type,
                "caption": caption
            })
            text = caption or f"[{msg_type.upper()}]"

        elif msg_type == "button":
            text = message.get("button", {}).get("text", "[Button Click]")
        elif msg_type == "interactive":
            # Handle list replies or button replies
            inter = message.get("interactive", {})
            if inter.get("type") == "button_reply":
                text = inter.get("button_reply", {}).get("title", "")
            elif inter.get("type") == "list_reply":
                text = inter.get("list_reply", {}).get("title", "")
        else:
            text = f"[Media/System Message: {msg_type}]"

        # Return a clean dictionary for consumption
        return {
            "business_number_id": business_number_id,
            "display_phone_number": display_phone_number,
            "visitor_phone": visitor_phone,
            "visitor_name": visitor_name,
            "message_id": message_id,
            "timestamp": timestamp,
            "text": text,
            "attachments_info": attachments, # Metadata to be processed
            "source": "whatsapp"
        }
    except Exception as e:
        logger.error(f"Failed to parse WhatsApp payload: {e}")
        return None
