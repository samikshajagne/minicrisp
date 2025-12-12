# gmail_reader.py
import imaplib
import email
from email.header import decode_header
import re
import logging
import os

# Logging
logger = logging.getLogger("gmail_reader")
logger.setLevel(logging.INFO)

# CONFIG
IMAP_EMAIL = os.environ.get("IMAP_EMAIL", "ai.intern@cetl.in")
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "qxsmvqolhuprpkwh")  # your app password
IMAP_HOST = "imap.gmail.com"
IMAP_FOLDER = "INBOX"


# -------------------------------------------------
# Helpers
# -------------------------------------------------

def _decode_mime_words(s):
    if not s:
        return ""
    parts = decode_header(s)
    out = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(part)
    return "".join(out)


def _extract_plain_text(msg):
    """Extract plain text content from email."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8",
                        errors="ignore"
                    )
                except:
                    return ""
        return ""
    else:
        try:
            return msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8",
                errors="ignore"
            )
        except:
            return ""


def _strip_quoted_text(body):
    """Remove quoted text from replies."""
    if not body:
        return ""

    body = body.replace("\r", "").replace("\r\n", "\n")

    # Remove lines starting with '>'
    lines = [ln for ln in body.split("\n") if not ln.strip().startswith(">")]
    body = "\n".join(lines)

    # Remove common separators
    separators = [
        r"On .* wrote:",
        r"From:",
        r"Sent:",
        r"-----Original Message-----",
    ]

    for sep in separators:
        parts = re.split(sep, body, flags=re.IGNORECASE)
        if len(parts) > 1:
            body = parts[0]
            break

    return body.strip()


# -------------------------------------------------
# MAIN FUNCTION
# -------------------------------------------------

def fetch_unread_replies():
    """Fetch unread Gmail replies (now using ALL messages but skipping SEEN)."""

    results = []

    if not IMAP_PASSWORD:
        logger.error("IMAP_PASSWORD missing — Gmail sync will NOT work.")
        return results

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_EMAIL, IMAP_PASSWORD)
        logger.info("IMAP login successful")

        mail.select(IMAP_FOLDER)

        # ⭐ READ ALL EMAILS (Solution B)
        typ, data = mail.search(None, 'ALL')
        if typ != "OK":
            logger.info("No messages found")
            mail.logout()
            return results

        for num in data[0].split():
            try:
                # Check flags to avoid processing already-seen messages
                typ, flags_data = mail.fetch(num, '(FLAGS)')
                if b'\\Seen' in flags_data[0]:
                    continue  # already processed earlier

                typ, msg_data = mail.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = _decode_mime_words(msg.get("Subject", ""))
                frm = _decode_mime_words(msg.get("From", ""))
                in_reply_to = (msg.get("In-Reply-To") or msg.get("References") or "").strip()

                body_raw = _extract_plain_text(msg)
                body_clean = _strip_quoted_text(body_raw)

                results.append({
                    "in_reply_to": in_reply_to,
                    "subject": subject,
                    "from": frm,
                    "body": body_clean.strip()
                })

                # Mark as SEEN so we don't process again
                mail.store(num, "+FLAGS", "\\Seen")

            except Exception as e_inner:
                logger.exception(f"Error processing message {num}: {e_inner}")
                continue

        mail.logout()

    except Exception as e:
        logger.exception(f"IMAP error: {e}")

    return results
