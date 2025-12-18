# gmail_reader.py
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import re
import logging
import os
from database import threads, email_received, get_email_accounts_with_secrets, fs

logger = logging.getLogger("gmail_reader")
logger.setLevel(logging.INFO)

IMAP_EMAIL = os.environ.get("IMAP_EMAIL", "ai.intern@cetl.in")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "samikshajagne7@gmail.com")
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "qxsmvqolhuprpkwh")
IMAP_HOST = "imap.gmail.com"
IMAP_FOLDER = "INBOX"


def _decode_mime_words(s):
    if not s:
        return ""
    parts = decode_header(s)
    out = ""
    for txt, enc in parts:
        if isinstance(txt, bytes):
            out += txt.decode(enc or "utf-8", errors="ignore")
        else:
            out += txt
    return out


def _extract_body(msg, content_type="text/plain"):
    """
    Extracts content of a specific type from the message.
    """
    if msg.is_multipart():
        # Iterate over parts
        for part in msg.walk():
            if part.get_content_type() == content_type:
                try:
                    return part.get_payload(decode=True).decode(errors="ignore")
                except:
                    continue
    # Fallback to single part if matches
    try:
        if msg.get_content_type() == content_type:
            return msg.get_payload(decode=True).decode(errors="ignore")
    except:
        return ""
    return ""


def _strip_quoted_text(body):
    """Removes reply chains like 'On ... wrote:', 'From: ...', etc."""
    patterns = [
        r"On\s.*\s?wrote:.*",                         # Gmail reply
        r"From:\s.*",                                 # Forwarded or nested reply
        r"Sent:\s.*",                                 # Outlook style
        r"Subject:\s.*",                              # Subject block
        r"-{2,}\s?Forwarded message\s?-{2,}.*",       # ---- Forwarded message ----
        r"^\s*>.*$",                                  # Quoted lines (standard email quote)
    ]
    
    cleaned = []
    # Only skip lines *after* the first match of a reply header
    in_reply_block = False
    
    for line in body.splitlines():
        line_clean = line.strip()
        
        # Check if this line marks the start of a reply block
        if not in_reply_block:
            for p in patterns:
                if re.match(p, line_clean, flags=re.IGNORECASE):
                    in_reply_block = True
                    break
        
        if not in_reply_block:
            cleaned.append(line)
    
    return "\n".join(cleaned).strip()



def _save_attachment(part, msg_id):
    """
    Saves an attachment part to GridFS and returns metadata.
    """
    filename = part.get_filename()
    if not filename:
        return None

    filename = _decode_mime_words(filename)
    
    try:
        content = part.get_payload(decode=True)
        if not content:
            return None

        # Store in GridFS
        file_id = fs.put(
            content,
            filename=filename,
            content_type=part.get_content_type(),
            metadata={"message_id": msg_id}
        )
            
        return {
            "filename": filename,
            "url": f"/api/attachments/{file_id}",
            "content_type": part.get_content_type(),
            "file_id": str(file_id)
        }
    except Exception as e:
        logger.error(f"Failed to save attachment {filename}: {e}")
        return None

def fetch_account_emails(account_config, criteria="UNSEEN"):
    """Fetch emails for a SINGLE account config."""
    results = []
    
    email_addr = account_config.get("email")
    password = account_config.get("app_password")
    host = account_config.get("imap_host", "imap.gmail.com")
    
    if not password:
        return []

    try:
        mail = imaplib.IMAP4_SSL(host)
        mail.login(email_addr, password)
        
        # Determine folders to scan
        folders_to_scan = ["INBOX"]
        
        # Try to identify Sent folder
        sent_folder = None
        list_typ, list_data = mail.list()
        if list_typ == "OK":
            for f in list_data:
                decoded = f.decode()
                match = re.search(r'\((?P<flags>.*?)\) "(?P<delim>.*?)" (?P<name>.*)', decoded)
                if match:
                    name_raw = match.group("name")
                    name = name_raw.strip('"')
                    
                    if "Sent" in name and "Trash" not in name:
                         if "Gmail" in name or name == "Sent":
                             sent_folder = name
        
        if sent_folder:
            folders_to_scan.append(sent_folder)
        else:
             if "[Gmail]/Sent Mail" not in folders_to_scan:
                 folders_to_scan.append("[Gmail]/Sent Mail")


        # Load all threads for mapping
        thread_map = {
            t["admin_msgid"].strip("<>"): t["visitor_email"]
            for t in threads.find()
            if "admin_msgid" in t
        }

        for folder in folders_to_scan:
            try:
                if " " in folder and not folder.startswith('"'):
                    folder_quoted = f'"{folder}"'
                else:
                    folder_quoted = folder

                rv, _ = mail.select(folder_quoted)
                if rv != "OK":
                    continue

                typ, data = mail.search(None, criteria)
                if typ != "OK":
                    continue
                
                msg_nums = data[0].split()
                if not msg_nums:
                    continue

                for num in msg_nums:
                    try:
                        typ, msg_data = mail.fetch(num, "(RFC822)")
                        if typ != "OK":
                            continue

                        raw = msg_data[0][1]
                        msg = email.message_from_bytes(raw)

                        msg_id = msg.get("Message-ID", "").strip()

                        email_date = None
                        try:
                            date_header = msg.get("Date")
                            if date_header:
                                email_date = parsedate_to_datetime(date_header)
                        except Exception:
                            pass

                        # 🛑 DEDUPLICATION / UPDATE CHECK
                        existing_doc = email_received.find_one({"message_id": msg_id})
                        
                        # Parse body & attachments FIRST to see if we have new info
                        subject = _decode_mime_words(msg.get("Subject", ""))
                        from_raw = _decode_mime_words(msg.get("From", ""))
                        to_raw = _decode_mime_words(msg.get("To", ""))
                        in_reply_to = msg.get("In-Reply-To", "").strip("<>")

                        if "<" in from_raw:
                            from_email = from_raw.split("<")[-1].split(">")[0].strip().lower()
                        else:
                            from_email = from_raw.strip().lower()

                        # BODY & ATTACHMENTS extraction
                        body_parts = []
                        html_parts = []
                        attachments = []
                        
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get("Content-Disposition"))
                                filename = part.get_filename()

                                if filename:
                                     filename = _decode_mime_words(filename) # Decode filename here too
                                     is_attachment = "attachment" in content_disposition or "inline" in content_disposition
                                     if not is_attachment and filename:
                                         if content_type not in ["text/plain", "text/html"]:
                                             is_attachment = True
                                     
                                     if is_attachment:
                                        att = _save_attachment(part, msg_id)
                                        if att:
                                            # Capture Content-ID for inline images
                                            cid = part.get("Content-ID")
                                            if cid:
                                                att["content_id"] = cid.strip()
                                            attachments.append(att)
                                
                                if content_type == "text/plain" and "attachment" not in content_disposition:
                                    try:
                                        body_parts.append(part.get_payload(decode=True).decode(errors="ignore"))
                                    except:
                                        pass
                                
                                # Capture HTML if available
                                if content_type == "text/html" and "attachment" not in content_disposition:
                                     try:
                                        html = part.get_payload(decode=True).decode(errors="ignore")
                                        # Basic check to avoid empty html parts overriding
                                        if html and len(html) > 10: 
                                            html_parts.append(html)
                                     except:
                                         pass

                        else:
                            try:
                                payload = msg.get_payload(decode=True).decode(errors="ignore")
                                body_parts.append(payload)
                                if msg.get_content_type() == "text/html":
                                    html_parts.append(payload)
                            except:
                                pass
                        
                        full_body = "\n".join(body_parts)
                        full_html = "".join(html_parts) if html_parts else None

                        # Rewrite CID images in HTML
                        if full_html and attachments:
                            for att in attachments:
                                cid = att.get("content_id")
                                if cid and cid.startswith('<') and cid.endswith('>'):
                                    cid = cid[1:-1] # strip angle brackets
                                
                                if cid:
                                    # Replace cid:header_value with /api/attachments/file_id
                                    # Regex to catch src="cid:..." ignoring quotes/spaces variations slightly
                                    # Simple replacement for now
                                    full_html = full_html.replace(f'cid:{cid}', att["url"])


                        body_clean = _strip_quoted_text(full_body)

                        # Logic: If existing doc, UPDATE it with attachments if missing
                        if existing_doc:
                            # Update DB if attachments found OR account_email missing OR html missing
                            update_fields = {}
                            if attachments:
                                update_fields["attachments"] = attachments
                            if "account_email" not in existing_doc:
                                update_fields["account_email"] = email_addr
                            if full_html and "html_content" not in existing_doc:
                                update_fields["html_content"] = full_html
                            
                            if update_fields:
                                email_received.update_one(
                                    {"_id": existing_doc["_id"]},
                                    {"$set": update_fields}
                                )
                                logger.info(f"Updated existing msg {msg_id} with {update_fields.keys()}")
                            continue # Move to next email (don't re-insert)

                        logger.info(f"[{email_addr}/{folder}] Subj='{subject}', From='{from_email}'")


                        # Determine SENDER
                        is_admin = (from_email == email_addr.lower())
                        sender = "admin" if is_admin else "visitor"

                        # Determine VISITOR email
                        visitor = None
                        if in_reply_to in thread_map:
                            visitor = thread_map[in_reply_to]
                        
                        if not visitor:
                            match = re.search(r"Conversation with\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", subject, re.IGNORECASE)
                            if match:
                                visitor = match.group(1).lower()

                        if not visitor and is_admin:
                             if "<" in to_raw:
                                 to_email = to_raw.split("<")[-1].split(">")[0].strip().lower()
                             else:
                                 to_email = to_raw.strip().lower()
                             
                             if to_email != email_addr.lower() and "support" not in to_email:
                                 visitor = to_email

                        if not visitor and not is_admin and from_email:
                            visitor = from_email

                        if not visitor or (visitor == email_addr.lower()):
                            continue

                        results.append({
                            "visitor": visitor,
                            "sender": sender,
                            "body": body_clean.strip(),
                            "source": "imap",
                            "message_id": msg_id,
                            "timestamp": email_date,
                            "timestamp": email_date,
                            "attachments": attachments,
                            "account_email": email_addr,
                            "html_content": full_html
                        })

                        mail.store(num, "+FLAGS", "\\Seen")

                    except Exception as e_inner:
                        logger.exception(f"Error processing message {num}: {e_inner}")
                        continue
            except Exception as e_folder:
                 logger.error(f"Error accessing folder {folder}: {e_folder}")
                 continue

        mail.logout()
    except Exception as e:
        logger.error(f"IMAP error for {email_addr}: {e}")
    
    return results


def fetch_emails(criteria="UNSEEN"):
    """Fetch emails from ALL configured accounts."""
    all_results = []
    
    # 1. Fetch from DB accounts
    db_accounts = get_email_accounts_with_secrets()
    for acc in db_accounts:
        all_results.extend(fetch_account_emails(acc, criteria))
        
    # 2. Fetch from ENV account (legacy support)
    if IMAP_EMAIL and IMAP_PASSWORD:
         env_acc = {
             "email": IMAP_EMAIL,
             "app_password": IMAP_PASSWORD,
             "imap_host": IMAP_HOST
         }
         # Avoid duplicate processing if same email is in DB
         if not any(a["email"] == IMAP_EMAIL.lower() for a in db_accounts):
             all_results.extend(fetch_account_emails(env_acc, criteria))

    return all_results


def test_credentials(email_addr, password, host="imap.gmail.com"):
    """
    Verifies if the provided credentials are valid for IMAP access.
    Returns: (bool, str) -> (Success, Error Message)
    """
    try:
        mail = imaplib.IMAP4_SSL(host)
        mail.login(email_addr, password)
        mail.logout()
        return True, None
    except imaplib.IMAP4.error as e:
        return False, f"IMAP authentication failed: {e}"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"
