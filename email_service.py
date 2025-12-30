import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import make_msgid
from datetime import datetime
from database import ensure_customer, email_sent, threads, email_accounts
import os

logging.basicConfig(
    filename='email_inbox.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger("email_service")

SENDER_EMAIL = os.environ.get("BOT_EMAIL", "ai.intern@cetl.in")
SENDER_PASSWORD = os.environ.get("BOT_APP_PASSWORD", "qxsmvqolhuprpkwh")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "samikshajagne7@gmail.com")


# -------------------------------------------------
# LOW-LEVEL EMAIL SENDER (THREAD SAFE)
# -------------------------------------------------
def _send_raw(
    to_email: str,
    subject: str,
    body: str,
    msg_id: str | None = None,
    reply_to: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    sender_email: str | None = None,
    sender_password: str | None = None,
    html_body: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[dict] | None = None
) -> bool:
    try:
        from_email = sender_email or SENDER_EMAIL
        password = sender_password or SENDER_PASSWORD
        
        # Determine correct MIME type
        if attachments:
            msg = MIMEMultipart("mixed")
            # If we have HTML, we need an alternative part for the body
            body_part = MIMEMultipart("alternative")
            msg.attach(body_part)
        elif html_body:
            msg = MIMEMultipart("alternative")
            body_part = msg # The root IS the alternative part
        else:
            msg = MIMEMultipart()
            body_part = msg

        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject

        # Add CC and BCC headers
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)

        if reply_to:
            msg["Reply-To"] = reply_to
        if msg_id:
            msg["Message-ID"] = msg_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        # Attach plain text version
        body_part.attach(MIMEText(body, "plain"))
        
        # Attach HTML version if provided
        if html_body:
            body_part.attach(MIMEText(html_body, "html"))

        # Process Attachments
        if attachments:
            for attachment in attachments:
                try:
                    filename = attachment.get("filename", "unknown")
                    content = attachment.get("content") # bytes
                    
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(content)
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename="{filename}"'
                    )
                    msg.attach(part)
                except Exception as e:
                    logger.error(f"Failed to attach file {filename}: {e}")

        # Prepare recipient list (to + cc + bcc)
        recipients = [to_email]
        if cc:
            recipients.extend(cc)
        if bcc:
            recipients.extend(bcc)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(from_email, password)
        server.sendmail(from_email, recipients, msg.as_string())
        server.quit()

        logger.info(f"Email sent from {from_email} → {to_email} | subject={subject} | cc={cc} | bcc={bcc}")
        return True
    except Exception as e:
        logger.exception(f"Email send failed → {to_email}: {e}")
        return False


# -------------------------------------------------
# VISITOR → WIDGET MESSAGE (START THREAD)
# -------------------------------------------------
def send_admin_and_customer_notifications(visitor_email: str, text: str, visitor_name: str | None = None) -> dict:
    visitor_email = (visitor_email or "").strip().lower()
    if not visitor_email:
        return {}

    cust = ensure_customer(visitor_email, visitor_name)
    tb1_id = cust["tb1_id"]

    # --- Check for existing thread to reply to ---
    thread = threads.find_one({"visitor_email": visitor_email})
    previous_admin_msgid = thread.get("admin_msgid") if thread else None

    # Generate new ID for this specific message
    new_admin_msgid = make_msgid(domain="mini-crisp")

    # --- Admin notification ---
    admin_subject = f"Conversation with {visitor_email}"
    admin_body = f"You received a new message from {visitor_email}:\n\n{text}"

    sent_admin = _send_raw(
        to_email=ADMIN_EMAIL,
        subject=admin_subject,
        body=admin_body,
        msg_id=new_admin_msgid,
        reply_to=SENDER_EMAIL,
        in_reply_to=previous_admin_msgid,   # THREADING MAGIC
        references=previous_admin_msgid     # THREADING MAGIC
    )

    # --- Customer acknowledgement ---
    cust_subject = "Your conversation with support"
    cust_body = f"You wrote:\n{text}\n\nWe will reply shortly."

    sent_cust = _send_raw(
        to_email=visitor_email,
        subject=cust_subject,
        body=cust_body,
        reply_to=SENDER_EMAIL,
        in_reply_to=new_admin_msgid,
        references=new_admin_msgid
    )

    threads.update_one(
        {"visitor_email": visitor_email},
        {"$set": {
            "visitor_email": visitor_email,
            "tb1_id": tb1_id,
            "admin_msgid": new_admin_msgid,  # Update to latest for next reply
            "updated_at": datetime.utcnow()
        }},
        upsert=True
    )

    email_sent.insert_one({
        "tb1_id": tb1_id,
        "email": visitor_email,
        "content": text,
        "admin_msgid": new_admin_msgid,
        "timestamp": datetime.utcnow()
    })

    return {"sent_admin": sent_admin, "sent_cust": sent_cust}


# -------------------------------------------------
# ADMIN → CUSTOMER REPLY (SAME THREAD)
# -------------------------------------------------
def send_reply_from_admin_to_customer(
    visitor_email: str, 
    text: str, 
    account_email: str | None = None,
    html_content: str | None = None,
    subject: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[dict] | None = None
) -> bool:
    visitor_email = (visitor_email or "").strip().lower()
    if not visitor_email:
        return False
    
    # Resolve Sender Credentials
    sender_email = None
    sender_password = None
    
    if account_email:
        # Try finding in DB
        acc = email_accounts.find_one({"email": account_email.lower()})
        if acc:
            sender_email = acc["email"]
            sender_password = acc["app_password"]
    
    # Fallback to Env if not found or not provided
    if not sender_email:
        sender_email = SENDER_EMAIL
        sender_password = SENDER_PASSWORD

    cust = ensure_customer(visitor_email)
    tb1_id = cust["tb1_id"]

    thread = threads.find_one({"visitor_email": visitor_email})
    admin_msgid = thread.get("admin_msgid") if thread else None

    cust_msgid = make_msgid(domain="mini-crisp")

    # Use custom subject or default
    email_subject = subject or f"Re: Conversation with {visitor_email}"
    body = text

    sent = _send_raw(
        to_email=visitor_email,
        subject=email_subject,
        body=body,
        msg_id=cust_msgid,
        reply_to=sender_email,
        in_reply_to=admin_msgid,
        references=admin_msgid,
        sender_email=sender_email,
        sender_password=sender_password,
        html_body=html_content,
        cc=cc,
        bcc=bcc,
        attachments=attachments
    )

    email_sent.insert_one({
        "tb1_id": tb1_id,
        "email": visitor_email,
        "content": text,
        "customer_msgid": cust_msgid,
        "timestamp": datetime.utcnow(),
        "subject": email_subject,
        "html_content": html_content,
        "cc": cc or [],
        "bcc": bcc or [],
        # For DB storage, we only store metadata here, effectively handled by main.py logic before calling this
        # But we can store a trace if needed. The actual file storage logic is usually upstream.
        "has_attachments": bool(attachments)
    })

    return sent


# -------------------------------------------------
# VISITOR EMAIL → ADMIN FORWARD (SAME THREAD)
# -------------------------------------------------
def forward_visitor_message_to_admin(visitor_email: str, text: str) -> bool:
    visitor_email = (visitor_email or "").strip().lower()
    if not visitor_email:
        return False

    thread = threads.find_one({"visitor_email": visitor_email})
    admin_msgid = thread.get("admin_msgid") if thread else None

    admin_subject = f"Conversation with {visitor_email}"
    body = f"Visitor wrote:\n\n{text}"

    sent = _send_raw(
        to_email=ADMIN_EMAIL,
        subject=admin_subject,
        body=body,
        reply_to=SENDER_EMAIL,
        in_reply_to=admin_msgid,
        references=admin_msgid
    )

    return sent
