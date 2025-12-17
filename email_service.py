import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid
from datetime import datetime
from database import ensure_customer, email_sent, threads
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
    references: str | None = None
) -> bool:
    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject

        if reply_to:
            msg["Reply-To"] = reply_to
        if msg_id:
            msg["Message-ID"] = msg_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()

        logger.info(f"Email sent → {to_email} | subject={subject}")
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
def send_reply_from_admin_to_customer(visitor_email: str, text: str) -> bool:
    visitor_email = (visitor_email or "").strip().lower()
    if not visitor_email:
        return False

    cust = ensure_customer(visitor_email)
    tb1_id = cust["tb1_id"]

    thread = threads.find_one({"visitor_email": visitor_email})
    admin_msgid = thread.get("admin_msgid") if thread else None

    cust_msgid = make_msgid(domain="mini-crisp")

    subject = "Reply from support"
    body = f"Support:\n\n{text}"

    sent = _send_raw(
        to_email=visitor_email,
        subject=subject,
        body=body,
        msg_id=cust_msgid,
        reply_to=SENDER_EMAIL,
        in_reply_to=admin_msgid,
        references=admin_msgid
    )

    email_sent.insert_one({
        "tb1_id": tb1_id,
        "email": visitor_email,
        "content": text,
        "customer_msgid": cust_msgid,
        "timestamp": datetime.utcnow()
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
