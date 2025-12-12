import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid

logging.basicConfig(filename='email_inbox.log', level=logging.INFO, format='%(asctime)s - %(message)s')
console_logger = logging.getLogger()
console_logger.setLevel(logging.INFO)

SENDER_EMAIL = "ai.intern@cetl.in"
SENDER_PASSWORD = "qxsmvqolhuprpkwh"
RECEIVER_EMAIL = "ai.intern@cetl.in"

# Store conversation thread IDs
THREAD_IDS = {}  # { visitor_key: "<thread-id@mini-crisp>" }


class EmailService:

    @staticmethod
    def send_notification(visitor: str, message: str, sender: str):
        """
        Sends Gmail-threaded email with correct headers.
        """
        if not visitor:
            visitor = "Anonymous Visitor"

        log_msg = f"{sender.capitalize()} -> {visitor}: {message}"
        logging.info(log_msg)
        console_logger.info(log_msg)

        if not SENDER_PASSWORD:
            return False

        # Create thread ID ONCE per visitor (for Gmail threading)
        if visitor not in THREAD_IDS:
            THREAD_IDS[visitor] = make_msgid(domain="mini-crisp-thread")

        thread_id = THREAD_IDS[visitor]       # thread anchor (FIXED)
        message_id = make_msgid(domain="mini-crisp-msg")  # unique per email

        # Email object
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = RECEIVER_EMAIL

        # IMPORTANT: SUBJECT MUST NOT CHANGE
        msg["Subject"] = f"Conversation with {visitor}"

        # Correct Gmail threading headers:
        msg["Message-ID"] = message_id          # unique per email ✔
        msg["In-Reply-To"] = thread_id          # fixed per conversation ✔
        msg["References"] = thread_id           # fixed per conversation ✔

        # Body
        body = (
            f"{sender.capitalize()} says:\n"
            f"{message}\n\n"
            f"---\nMini Crisp Chat"
        )

        msg.attach(MIMEText(body, "plain"))

        # Send email
        try:
            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
            server.quit()
            console_logger.info(f"Threaded email sent for visitor {visitor}")
            return True

        except Exception as e:
            console_logger.error(f"Email error: {e}")
            return False
