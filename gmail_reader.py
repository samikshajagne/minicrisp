# gmail_reader.py
import imaplib
import email
from email.header import decode_header
import re
import logging
import os

from database import threads

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


def fetch_unread_replies():
    """Fetch unread Gmail replies and convert them into chat messages."""
    results = []

    if not IMAP_PASSWORD:
        logger.error("IMAP_PASSWORD missing — Gmail sync will NOT work.")
        return results

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_EMAIL, IMAP_PASSWORD)
        
        mail.select(IMAP_FOLDER)

        # Search for ALL messages, we filter by Seen flag manually to be safe or use UNSEEN
        # Using ALL + manual check allows re-processing if needed, but UNSEEN is efficient.
        # User code used ALL, let's stick to UNSEEN for efficiency unless user wants re-scan.
        # Actually, user code had "flags" check logic, so let's respect that flow with UNSEEN for simplicity.
        typ, data = mail.search(None, 'UNSEEN')
        if typ != "OK":
            return results

        # Load all threads for mapping
        thread_map = {
            t["admin_msgid"].strip("<>"): t["visitor_email"]
            for t in threads.find()
            if "admin_msgid" in t
        }

        for num in data[0].split():
            try:
                typ, msg_data = mail.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = _decode_mime_words(msg.get("Subject", ""))
                from_raw = _decode_mime_words(msg.get("From", ""))
                in_reply_to = msg.get("In-Reply-To", "").strip("<>")

                # -----------------------------
                # Extract REAL email address
                # -----------------------------
                if "<" in from_raw:
                    from_email = from_raw.split("<")[-1].split(">")[0].strip().lower()
                else:
                    from_email = from_raw.strip().lower()

                logger.info(f"Processing email: Subject='{subject}', From='{from_email}' In-Reply-To='{in_reply_to}'")

                # CLEAN BODY
                body_raw = _extract_plain_text(msg)
                body_clean = _strip_quoted_text(body_raw)

                # -----------------------------
                # Determine VISITOR email
                # -----------------------------
                visitor = None

                # 1. Try Thread Map
                if in_reply_to in thread_map:
                    visitor = thread_map[in_reply_to]
                    logger.info(f"Matched thread ID {in_reply_to} to visitor {visitor}")

                # 4. Fallback: Sender is visitor (only if NOT admin)
                is_admin = (from_email == IMAP_EMAIL.lower()) or (from_email == ADMIN_EMAIL.lower())
                if not visitor and not is_admin and from_email:
                    visitor = from_email

                if not visitor:
                    logger.warning("Could not identify visitor. Skipping.")
                    continue

                # -----------------------------
                # Determine SENDER
                # -----------------------------
                # If email comes from Admin or Bot -> sender="admin"
                # Else -> sender="visitor"
                sender = "admin" if is_admin else "visitor"
                # -----------------------------
                # HARD BLOCK system / bot identities
                # -----------------------------
                if visitor in {
                    "support",
                    IMAP_EMAIL.lower(),
                    ADMIN_EMAIL.lower()
                }:
                    logger.warning(f"Blocked invalid visitor identity: {visitor}")
                    continue


                results.append({
                    "visitor": visitor,
                    "sender": sender,
                    "body": body_clean.strip(),
                    "source": "imap"
                })

                # Mark processed
                mail.store(num, "+FLAGS", "\\Seen")

            except Exception as e_inner:
                logger.exception(f"Error processing message {num}: {e_inner}")
                continue

        mail.logout()

    except Exception as e:
        logger.exception(f"IMAP error: {e}")

    return results
