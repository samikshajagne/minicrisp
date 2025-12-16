# gmail_reader.py
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import re
import logging
import os
from database import threads, email_received, get_email_accounts_with_secrets

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


def _extract_plain_text(msg):
    if msg.is_multipart():
        # Iterate over parts, preferring text/plain
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(errors="ignore")
                except:
                    continue
    # Fallback to single part
    try:
        return msg.get_payload(decode=True).decode(errors="ignore")
    except:
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
        # 1. INBOX
        # 2. Sent Items (try common names)
        folders_to_scan = ["INBOX"]
        
        # Try to identify Sent folder
        sent_folder = None
        list_typ, list_data = mail.list()
        if list_typ == "OK":
            for f in list_data:
                # Parse: (\Flags) "/" "FolderName"
                # Regex to extract name (last quoted or unquoted part)
                decoded = f.decode()
                # Match: (flags) "delim" "name" OR (flags) "delim" name
                match = re.search(r'\((?P<flags>.*?)\) "(?P<delim>.*?)" (?P<name>.*)', decoded)
                if match:
                    name_raw = match.group("name")
                    # Remove surrounding quotes if present
                    name = name_raw.strip('"')
                    
                    if "Sent" in name and "Trash" not in name:
                         # Prefer [Gmail]/Sent Mail or Sent
                         if "Gmail" in name or name == "Sent":
                             sent_folder = name
        
        if sent_folder:
            folders_to_scan.append(sent_folder)
        else:
             # Just add [Gmail]/Sent Mail if we couldn't find it dynamically, 
             # but check if it already exists to avoid duplication
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
                # Quote folder if it contains spaces and isn't already quoted
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

                        # Extract Message-ID
                        msg_id = msg.get("Message-ID", "").strip()

                        # Extract Date
                        email_date = None
                        try:
                            date_header = msg.get("Date")
                            if date_header:
                                email_date = parsedate_to_datetime(date_header)
                        except Exception:
                            pass

                        # 🛑 DEDUPLICATION CHECK
                        if email_received.find_one({"message_id": msg_id}):
                            continue

                        subject = _decode_mime_words(msg.get("Subject", ""))
                        from_raw = _decode_mime_words(msg.get("From", ""))
                        to_raw = _decode_mime_words(msg.get("To", ""))
                        in_reply_to = msg.get("In-Reply-To", "").strip("<>")

                        # Extract REAL email address
                        if "<" in from_raw:
                            from_email = from_raw.split("<")[-1].split(">")[0].strip().lower()
                        else:
                            from_email = from_raw.strip().lower()

                        logger.info(f"[{email_addr}/{folder}] Subj='{subject}', From='{from_email}'")

                        # CLEAN BODY
                        body_raw = _extract_plain_text(msg)
                        body_clean = _strip_quoted_text(body_raw)

                        # Determine SENDER
                        is_admin = (from_email == email_addr.lower())
                        sender = "admin" if is_admin else "visitor"

                        # Determine VISITOR email
                        visitor = None

                        # 1. Thread Map
                        if in_reply_to in thread_map:
                            visitor = thread_map[in_reply_to]
                        
                        # 2. Subject Fallback (Re: Conversation with ...)
                        if not visitor:
                            # Regex for "Conversation with <email>"
                            # Matches "Re: Conversation with user@example.com"
                            match = re.search(r"Conversation with\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", subject, re.IGNORECASE)
                            if match:
                                visitor = match.group(1).lower()

                        # 3. 'To' Header Fallback (If Admin sent it)
                        if not visitor and is_admin:
                             # Admin sent it -> To field might be the visitor
                             # But check if To is NOT the bot/self
                             if "<" in to_raw:
                                 to_email = to_raw.split("<")[-1].split(">")[0].strip().lower()
                             else:
                                 to_email = to_raw.strip().lower()
                             
                             if to_email != email_addr.lower() and "support" not in to_email:
                                 visitor = to_email

                        # 4. Fallback: Sender is visitor (only if NOT admin)
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
                            "timestamp": email_date
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
