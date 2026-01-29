
from flask import Flask, send_from_directory, jsonify, request
import os
import pandas as pd
import csv
import time
import json
import smtplib
import imaplib
import email
from email.header import decode_header
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

#Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# SMTP Configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# IMAP Configuration
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")

MODEL_NAME = "gemini-2.5-flash"




app = Flask(__name__, static_url_path='')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_CSV = os.path.join(BASE_DIR, 'master.csv')
TEMP_DIR = os.path.join(BASE_DIR, 'uploads')
SENT_EMAILS_FILE = os.path.join(BASE_DIR, 'sent_emails.json')
REPLIES_FILE = os.path.join(BASE_DIR, 'replies.json')

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)


# Ensure master.csv exists with standard headers if not present
STANDARD_HEADERS = [
    "Company Name", "Latitude", "Longitude", "Address", "City", "State", 
    "Country", "Industry", "Company Type", "Product Category", 
    "Product Name", "Revenue", "Potential", "Website", "Phone", "Email", "Employee Details"
]

if not os.path.exists(MASTER_CSV):
    df_empty = pd.DataFrame(columns=STANDARD_HEADERS)
    df_empty.to_csv(MASTER_CSV, index=False)
    print("Created new master.csv")

# Helper to read CSV with multiple encodings
def read_csv_robust(filepath):
    encodings = ['utf-8', 'latin1', 'cp1252', 'ISO-8859-1']
    for enc in encodings:
        try:
            return pd.read_csv(filepath, encoding=enc)
        except UnicodeDecodeError:
            continue
    # If all fail, try again with errors='replace' to force it
    return pd.read_csv(filepath, encoding='utf-8', errors='replace')

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(BASE_DIR, filename)

@app.route('/api/master-data', methods=['GET'])
def get_master_data():
    try:
        if os.path.exists(MASTER_CSV):
            # Read CSV and fill NaNs to be JSON compatible
            df = read_csv_robust(MASTER_CSV).fillna('')
            data = df.to_dict(orient='records')
            return jsonify(data)
        else:
            return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Email History Helpers ---
def load_json_file(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_json_file(filepath, data):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def log_sent_email(recipients, subject, body):
    sent_emails = load_json_file(SENT_EMAILS_FILE)
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Try to extract company name from the first recipient if possible
    # This is a heuristic; ideally we'd pass company name if known
    company_name = "Unknown Company"
    # We could look up the email in master.csv to find the company name
    try:
        if os.path.exists(MASTER_CSV):
             df = read_csv_robust(MASTER_CSV)
             # Basic lookup: check if any recipient email matches 'Email' column
             for email_addr in recipients:
                 match = df[df['Email'] == email_addr]
                 if not match.empty:
                     company_name = match.iloc[0]['Company Name']
                     break
    except:
        pass

    entry = {
        "id": str(int(time.time() * 1000)),
        "type": "sent",
        "recipients": recipients,
        "subject": subject,
        "company": company_name,
        "timestamp": timestamp,
        "body": body, # Store full body
        "body_preview": body[:100] + "..." if len(body) > 100 else body
    }
    
    sent_emails.append(entry)
    save_json_file(SENT_EMAILS_FILE, sent_emails)

def decode_mime_header(header_value):
    if not header_value:
        return ""
    decoded_list = decode_header(header_value)
    decoded_text = ""
    for token, encoding in decoded_list:
        if isinstance(token, bytes):
            if encoding:
                try:
                    decoded_text += token.decode(encoding)
                except:
                    decoded_text += token.decode('utf-8', errors='ignore')
            else:
                decoded_text += token.decode('utf-8', errors='ignore')
        else:
            decoded_text += str(token)
    return decoded_text

def get_email_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get("Content-Disposition"))
            # skip attachments
            if "attachment" in cdispo:
                continue
            if ctype == "text/plain":
                 return part.get_payload(decode=True).decode('utf-8', errors='ignore')
    else:
        return msg.get_payload(decode=True).decode('utf-8', errors='ignore')
    return ""

def fetch_replies_from_imap():
    if not SMTP_USER or not SMTP_PASSWORD or not IMAP_HOST:
        print("IMAP not configured")
        return

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(SMTP_USER, SMTP_PASSWORD)
        mail.select("inbox")

        # Search for all emails (or filter by date/sender if needed to optimize)
        # For simplicity, let's look at recent ones or all UNSEEN? 
        # But we want to see replies even if read elsewhere.
        # Let's search for emails FROM our known contacts.
        
        # Optimization: Just fetch last N emails? Or search by sender from sent_emails?
        # A simpler approach for this prototype: Fetch ALL emails from today/yesterday 
        # OR just search for *all* and filter in python (slow for large inboxes)
        
        # Better approach: We only care about replies to our sent emails.
        # But we don't have message-ids threaded perfectly.
        # Let's just fetch all emails and check if the sender matches any company in our master.csv
        
        known_emails = set()
        if os.path.exists(MASTER_CSV):
             df = read_csv_robust(MASTER_CSV)
             if 'Email' in df.columns:
                 known_emails = set(df['Email'].dropna().unique())
        
        # Search for emails from these senders? 
        # If the list is huge, that's impossible.
        # Let's just fetch the last 50 emails.
        
        status, messages = mail.search(None, 'ALL')
        if status != 'OK':
            return
            
        msg_ids = messages[0].split()
        # Look at last 50 messages
        latest_ids = msg_ids[-50:] 
        
        replies = load_json_file(REPLIES_FILE)
        existing_ids = {r['msg_id'] for r in replies if 'msg_id' in r}
        
        new_replies_found = False

        for msg_id in reversed(latest_ids):
            msg_id_str = msg_id.decode()
            if msg_id_str in existing_ids:
                continue
                
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK": 
                continue
                
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    if not msg: continue
                    
                    sender = decode_mime_header(msg.get("From"))
                    subject = decode_mime_header(msg.get("Subject"))
                    date_str = msg.get("Date")
                    
                    # Extract email address from sender "Name <email@example.com>"
                    import re
                    email_match = re.search(r'<(.+?)>', sender)
                    sender_email = email_match.group(1) if email_match else sender
                    
                    # Check if this sender is a "Company" (in our known list) OR just log all?
                    # Providing a way to see ALL replies is safer.
                    # We will log it.
                    
                    # Try to map sender to Company Name
                    company_name = sender.split('<')[0].strip()
                    if sender_email in known_emails:
                        # Ensure we use the company name from CSV if available
                         if os.path.exists(MASTER_CSV):
                             df = read_csv_robust(MASTER_CSV)
                             match = df[df['Email'] == sender_email]
                             if not match.empty:
                                 company_name = match.iloc[0]['Company Name']

                    body = get_email_body(msg) or "No text content"
                    
                    new_reply = {
                        "id": str(int(time.time() * 1000)) + "_" + msg_id_str, # unique internal id
                        "msg_id": msg_id_str,
                        "type": "reply",
                        "sender_email": sender_email,
                        "sender_name": sender,
                        "company": company_name,
                        "subject": subject,
                        "timestamp": date_str, # Use raw date string or parse it
                        "body": body, #  Store full body
                        "body_preview": body[:100] + "...",
                        "viewed": False
                    }
                    
                    replies.append(new_reply)
                    new_replies_found = True
        
        if new_replies_found:
            save_json_file(REPLIES_FILE, replies)
            
        mail.close()
        mail.logout()
        
    except Exception as e:
        print(f"IMAP Error: {e}")

def extract_filters(user_query: str) -> dict:
    # model = genai.GenerativeModel(MODEL_NAME) # Deprecated
    
    # Using the standard headers defined in server.py
    data_columns_str = ", ".join(STANDARD_HEADERS)

    prompt = f"""
    You are an enterprise data query engine.

    IMPORTANT:
    - The user may provide full sentences OR short keyword-based queries
    - Treat keyword-style input as a valid request
    - Infer intent even if the sentence is incomplete

    STRICT RULES:
    - Return ONLY valid JSON
    - Do NOT explain anything
    - Do NOT add extra text
    - Do NOT infer country, state, or city names from partial substrings.
    - EXAMPLES OF WHAT NOT TO DO:
      - "dia" -> DO NOT match "India" or "Cambodia"
      - "mum" -> DO NOT match "Mumbai"
      - "bengal" -> DO NOT match "West Bengal" (unless "West" is also said)
    - Only extract a location if the user explicitly mentions the COMPLETE name found in standard datasets.
    
    Goal: Extract filters to query a dataset with these columns:
    {data_columns_str}

    The frontend expects a specific JSON structure. Map the user's intent to these keys:
    - "city": (e.g., from "in Mumbai")
    - "state": (e.g., "Gujarat")
    - "country": (e.g., "India") - STRICT EXACT MATCH ONLY
    - "industries": [List of strings] (e.g., ["Pharmaceuticals", "Manufacturing"])
    - "productCategory": (Single string)
    - "productNameKeywords": [List of keywords for partial matching] (e.g., ["methyl", "acid"])
      Extract ANY product-related keywords that should match against product names.
      For example: "companies for methyl" -> ["methyl"]
                   "vinyl and acid products" -> ["vinyl", "acid"]
    
    Return format:
    {{
      "city": "",
      "state": "",
      "country": "",
      "industries": [],
      "productCategory": "",
      "productNameKeywords": []
    }}
    
    User query:
    {user_query}
    """

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0,
                max_output_tokens=300
            )
        )

        if not response or not response.text:
            return {}

        text = response.text.strip()
        # Clean up markdown code blocks if present
        text = text.replace('```json', '').replace('```', '')
        
        start, end = text.find("{"), text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            return {}

        parsed = json.loads(text[start:end + 1])
        return parsed
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {}

@app.route('/api/voice-search', methods=['POST'])
def voice_search():
    try:
        data = request.json
        query = data.get('query', '')
        if not query:
            return jsonify({})
        
        filters = extract_filters(query)
        return jsonify(filters)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/deepgram-config', methods=['GET'])
def get_deepgram_config():
    """Serve Deepgram API configuration from environment variables"""
    try:
        deepgram_key = os.getenv("DEEPGRAM_API_KEY")
        if not deepgram_key:
            return jsonify({"error": "Deepgram API key not configured"}), 500
        
        return jsonify({
            "apiKey": deepgram_key,
            "settings": {
                "language": "en-IN",
                "model": "nova-2",
                "smart_format": True,
                "punctuate": True,
                "interim_results": True
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/upload-csv', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file:
        filepath = os.path.join(TEMP_DIR, 'temp_upload.csv')
        file.save(filepath)
        
        try:
            # Read headers and detection sample
            df = read_csv_robust(filepath)
            headers = df.columns.tolist()
            # Simple column detection suggestions could be done here or in frontend
            return jsonify({"headers": headers, "filename": "temp_upload.csv"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/api/append-data', methods=['POST'])
def append_data():
    try:
        data = request.json
        mapping = data.get('mapping') # { 'Standard Field': 'CSV Header' }
        filename = data.get('filename') # 'temp_upload.csv'
        
        filepath = os.path.join(TEMP_DIR, filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "Temp file not found"}), 404
        
        df_new = read_csv_robust(filepath)
        df_master = read_csv_robust(MASTER_CSV) if os.path.exists(MASTER_CSV) else pd.DataFrame(columns=STANDARD_HEADERS)
        
        # Create a new dataframe with standard headers, pulling data from mapped columns
        df_to_append = pd.DataFrame()
        
        for std_col, csv_col in mapping.items():
            if csv_col and csv_col in df_new.columns:
                df_to_append[std_col] = df_new[csv_col]
            else:
                df_to_append[std_col] = "" # Fill missing with empty string
        
        # Ensure all standard headers exist
        for col in STANDARD_HEADERS:
            if col not in df_to_append.columns:
                df_to_append[col] = ""
                
        # Filter for valid lat/lon if those columns were mapped
        if "Latitude" in df_to_append.columns and "Longitude" in df_to_append.columns:
             # Basic cleaning: drop rows where lat/lon is NaN or not convertible
             df_to_append['Latitude'] = pd.to_numeric(df_to_append['Latitude'], errors='coerce')
             df_to_append['Longitude'] = pd.to_numeric(df_to_append['Longitude'], errors='coerce')
             df_to_append = df_to_append.dropna(subset=['Latitude', 'Longitude'])
        
        # Append and save
        df_combined = pd.concat([df_master, df_to_append], ignore_index=True)
        # Append and save with Retry Logic for Permission Issues
        max_retries = 3
        for attempt in range(max_retries):
            try:
                df_combined.to_csv(MASTER_CSV, index=False)
                break # Success
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(1) # Wait 1s and retry
                    continue
                else:
                    return jsonify({"error": "Permission denied: 'master.csv' is open in another program. Please close it and try again."}), 500
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        return jsonify({"message": f"Successfully appended {len(df_to_append)} rows", "total_rows": len(df_combined)})

    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/smtp-config', methods=['GET'])
def get_smtp_config():
    """Check if SMTP is configured"""
    is_configured = bool(SMTP_USER and SMTP_PASSWORD)
    return jsonify({
        "configured": is_configured,
        "senderEmail": SMTP_USER if is_configured else None,
        "userEmail": SMTP_USER if is_configured else None  # Add user email for display
    })

@app.route('/api/send-email', methods=['POST'])
def send_email():
    """Send email to recipients via SMTP"""
    try:
        # Check SMTP configuration
        if not SMTP_USER or not SMTP_PASSWORD:
            return jsonify({
                "error": "SMTP not configured. Please add SMTP_USER and SMTP_PASSWORD to .env file."
            }), 400
        
        if request.is_json:
            data = request.get_json(silent=True) or {}
            recipients = data.get('recipients', [])
            subject = data.get('subject', '')
            body = data.get('body', '')
        else:
            # Handle multipart/form-data (FormData from frontend)
            recipients_raw = request.form.get('recipients')
            recipients = json.loads(recipients_raw) if recipients_raw else []
            subject = request.form.get('subject', '')
            body = request.form.get('body', '')
        
        if not recipients:
            return jsonify({"error": "No recipients specified"}), 400
        
        if not subject:
            return jsonify({"error": "Subject is required"}), 400
        
        if not body:
            return jsonify({"error": "Email body is required"}), 400
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['Subject'] = subject
        
        # Add body
        msg.attach(MIMEText(body, 'html'))
        
        # Handle attachments
        if 'attachments' in request.files:
            files = request.files.getlist('attachments')
            from email.mime.base import MIMEBase
            from email import encoders
            
            for file in files:
                if file.filename:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(file.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename="{file.filename}"'
                    )
                    msg.attach(part)
        
        # Track success and failures
        success_count = 0
        failed_recipients = []
        
        # Connect to SMTP server
        try:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            
            # Send to each recipient individually for better error tracking
            for recipient in recipients:
                try:
                    msg['To'] = recipient
                    server.sendmail(SMTP_USER, recipient, msg.as_string())
                    success_count += 1
                    # Clear the 'To' header for next iteration
                    if 'To' in msg:
                        del msg['To']
                except Exception as e:
                    failed_recipients.append({"email": recipient, "error": str(e)})
                    if 'To' in msg:
                        del msg['To']
            
            server.quit()
            
        except smtplib.SMTPAuthenticationError:
            return jsonify({
                "error": "SMTP authentication failed. Check your email and password in .env file. For Gmail, use an App Password."
            }), 401
        except smtplib.SMTPConnectError:
            return jsonify({
                "error": f"Could not connect to SMTP server {SMTP_HOST}:{SMTP_PORT}"
            }), 500
        except Exception as e:
            return jsonify({"error": f"SMTP error: {str(e)}"}), 500
        
        # Return results
        if success_count == 0:
            return jsonify({
                "error": "Failed to send to all recipients",
                "failed": failed_recipients
            }), 500
        elif failed_recipients:
            log_sent_email(recipients, subject, body) # Log partial success
            return jsonify({
                "message": f"Sent {success_count} email(s), {len(failed_recipients)} failed",
                "success_count": success_count,
                "failed": failed_recipients
            }), 207  # Multi-Status
        else:
            log_sent_email(recipients, subject, body) # Log full success
            return jsonify({
                "message": f"Successfully sent {success_count} email(s)",
                "success_count": success_count
            })
            
    except Exception as e:
        print(f"Send email error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/generate-subject', methods=['POST'])
def generate_subject():
    """Generate a subject line using Gemini based on the message body"""
    try:
        data = request.get_json(silent=True) or {}
        body = data.get('body', '')

        if not body:
            return jsonify({"error": "Message body is required to generate a subject"}), 400

        prompt = f"""
        Generate a single professional, concise, and engaging email subject line for the following message body.
        Return ONLY the subject line text, no quotes or additional words.

        Email Body:
        {body}
        """

        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt)

        subject = response.text.strip()
        # Clean up any quotes Gemini might have added
        if subject.startswith('"') and subject.endswith('"'):
            subject = subject[1:-1]
        if subject.startswith("'") and subject.endswith("'"):
            subject = subject[1:-1]

        return jsonify({"subject": subject})

    except Exception as e:
        print(f"Subject generation error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/generate-email', methods=['POST'])
def generate_email():
    """Generate email body and subject using Gemini based on user's voice command"""
    try:
        data = request.get_json(silent=True) or {}
        voice_command = data.get('command', '')

        if not voice_command:
            return jsonify({"error": "Voice command is required"}), 400

        prompt = f"""
        You are a professional email writer. Based on the user's voice command, generate a complete professional email.
        
        RULES:
        - Generate a professional, polite, and well-structured email body
        - The email should be ready to send (complete with greeting and sign-off)
        - Use "[Your Name]" as placeholder for the sender's name
        - Use "[Company Name]" as placeholder if company name is needed
        - Keep it concise but professional
        - Also generate an appropriate subject line
        
        User's voice command: "{voice_command}"
        
        Return your response in this exact JSON format:
        {{
            "subject": "The email subject line",
            "body": "The complete email body with greeting and sign-off"
        }}
        
        Return ONLY the JSON, no additional text.
        """

        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=1000
            )
        )

        if not response or not response.text:
            return jsonify({"error": "Failed to generate email"}), 500

        text = response.text.strip()
        # Clean up markdown code blocks if present
        text = text.replace('```json', '').replace('```', '').strip()
        
        # Parse JSON response
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            # Fallback: return raw text as body
            return jsonify({
                "subject": "Inquiry",
                "body": text
            })
        
        parsed = json.loads(text[start:end + 1])
        return jsonify(parsed)

    except Exception as e:
        print(f"Email generation error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/append-email', methods=['POST'])
def append_email():
    """Modify existing email content using Gemini based on user's voice command"""
    try:
        data = request.get_json(silent=True) or {}
        voice_command = data.get('command', '')
        existing_body = data.get('existingBody', '')

        if not voice_command:
            return jsonify({"error": "Voice command is required"}), 400

        if not existing_body:
            return jsonify({"error": "No existing message to modify. Use 'Generate' first."}), 400

        prompt = f"""
        You are a professional email editor. The user wants to make changes to their existing email.
        
        RULES:
        - Modify the existing email based on the user's request
        - Keep the overall structure and tone of the email
        - Apply the requested changes while maintaining professionalism
        - If asked to add something, add it in the appropriate place
        - If asked to remove something, remove it
        - If asked to change tone, rewrite accordingly
        - If asked to shorten, make it more concise
        - If asked to expand, add more detail
        - Return the COMPLETE modified email, not just the changes
        
        Existing email content:
        {existing_body}
        
        User's requested changes: "{voice_command}"
        
        Return your response in this exact JSON format:
        {{
            "modifiedBody": "The complete modified email content"
        }}
        
        Return ONLY the JSON, no additional text.
        """

        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=1000
            )
        )

        if not response or not response.text:
            return jsonify({"error": "Failed to generate content"}), 500

        text = response.text.strip()
        text = text.replace('```json', '').replace('```', '').strip()
        
        # Parse JSON response
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            modified_body = text
        else:
            parsed = json.loads(text[start:end + 1])
            modified_body = parsed.get('modifiedBody', text)
        
        return jsonify({"appendedBody": modified_body})

    except Exception as e:
        print(f"Modify email error: {e}")
        return jsonify({"error": str(e)}), 500

# --- New Endpoints for History & Replies ---

@app.route('/api/email-history', methods=['GET'])
def get_email_history():
    """Combine sent emails and replies into a single sorted timeline"""
    sent = load_json_file(SENT_EMAILS_FILE)
    replies = load_json_file(REPLIES_FILE)
    
    # Normalize data for frontend
    combined = []
    
    for s in sent:
        combined.append({
            "id": s.get("id"),
            "type": "sent",
            "company": s.get("company", "Unknown"),
            "subject": s.get("subject", "No Subject"),
            "timestamp": s.get("timestamp"),
            "body_preview": s.get("body_preview"),
            "recipients": s.get("recipients", []),
            "viewed": True # Sent items are always "viewed"
        })
        
    for r in replies:
        combined.append({
            "id": r.get("id"),
            "type": "reply",
            "company": r.get("company", "Unknown"),
            "subject": r.get("subject", "No Subject"),
            "timestamp": r.get("timestamp"),
            "body_preview": r.get("body_preview"),
            "sender_email": r.get("sender_email"),
            "viewed": r.get("viewed", False)
        })
    
    # Group messages by email address (conversation partner)
    conversations = {}
    
    # Process sent emails
    for s in sent:
        recipients = s.get('recipients', [])
        for recipient in recipients:
            recipient_lower = recipient.lower() if recipient else ""
            if not recipient_lower: continue

            if recipient_lower not in conversations:
                conversations[recipient_lower] = {
                    'email': recipient, # Keep original casing for display if needed
                    'company': s.get('company', 'Unknown'),
                    'messages': [],
                    'unread_count': 0,
                    'has_replies': False
                }
            conversations[recipient_lower]['messages'].append({
                'type': 'sent',
                'timestamp': s.get('timestamp'),
                'subject': s.get('subject', 'No Subject'),
                'body_preview': s.get('body_preview', ''),
                'id': s.get('id')
            })
    
    # Process replies
    for r in replies:
        sender_email = r.get('sender_email', '')
        if not sender_email:
            continue
        
        sender_email_lower = sender_email.lower()
            
        if sender_email_lower not in conversations:
            conversations[sender_email_lower] = {
                'email': sender_email,
                'company': r.get('company', sender_email),
                'messages': [],
                'unread_count': 0,
                'has_replies': False
            }
        conversations[sender_email_lower]['messages'].append({
            'type': 'reply',
            'timestamp': r.get('timestamp'),
            'subject': r.get('subject', 'No Subject'),
            'body_preview': r.get('body_preview', ''),
            'id': r.get('id')
        })
        conversations[sender_email_lower]['has_replies'] = True  # Mark that this conversation has replies
        if not r.get('viewed', False):
            conversations[sender_email_lower]['unread_count'] += 1
    
    # Create thread list
    threads = []
    for email_addr, conv in conversations.items():
        # Sort messages by timestamp to get the latest
        def parse_date(date_str):
            if not date_str: return 0
            try:
                return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").timestamp()
            except:
                try:
                    from email.utils import parsedate_to_datetime
                    return parsedate_to_datetime(date_str).timestamp()
                except:
                    return 0
        
        try:
            conv['messages'].sort(key=lambda x: parse_date(x['timestamp']), reverse=True)
        except:
            pass
        
        if len(conv['messages']) == 0:
            continue
            
        latest = conv['messages'][0]
        
        # Safety check: ensure latest has required fields
        if not latest:
            continue
        
        threads.append({
            'type': 'conversation',
            'email': email_addr,
            'company': conv['company'],
            'subject': latest.get('subject', 'No Subject'),
            'message_count': len(conv['messages']),
            'unread_count': conv.get('unread_count', 0),
            'has_replies': conv.get('has_replies', False),
            'timestamp': latest.get('timestamp', ''),
            'body_preview': latest.get('body_preview', ''),
            'viewed': conv.get('unread_count', 0) == 0,
            'id': latest.get('id', str(hash(email_addr))),
            'recipients': [email_addr] if email_addr else []
        })
    
    # Sort by latest message timestamp
    def parse_date(date_str):
        if not date_str: return 0
        try:
            return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").timestamp()
        except:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(date_str).timestamp()
            except:
                return 0
    
    try:
        threads.sort(key=lambda x: parse_date(x['timestamp']), reverse=True)
    except:
        pass
    
    return jsonify(threads)

@app.route('/api/mark-conversation-viewed', methods=['POST'])
def mark_conversation_viewed():
    """Mark all replies from a specific email address as viewed"""
    data = request.json
    email = data.get('email')
    
    if not email:
        return jsonify({"error": "Email required"}), 400
    
    replies = load_json_file(REPLIES_FILE)
    updated = False
    for r in replies:
        if r.get('sender_email') == email and not r.get('viewed', False):
            r['viewed'] = True
            updated = True
    
    if updated:
        save_json_file(REPLIES_FILE, replies)
    
    return jsonify({"success": True, "updated": updated})

@app.route('/api/check-replies', methods=['GET'])
def check_replies():
    """Trigger a manual IMAP check"""
    # Run in the main thread for now (might block for a few seconds)
    fetch_replies_from_imap()
    return jsonify({"message": "Checked for replies"})

@app.route('/api/mark-viewed', methods=['POST'])
def mark_viewed():
    data = request.json
    reply_id = data.get('id')
    
    replies = load_json_file(REPLIES_FILE)
    updated = False
    for r in replies:
        if r.get('id') == reply_id:
            r['viewed'] = True
            updated = True
            break
            
    if updated:
        save_json_file(REPLIES_FILE, replies)
        return jsonify({"success": True})
    return jsonify({"error": "Reply not found"}), 404

@app.route('/api/get-conversation', methods=['GET'])
def get_conversation():
    """Fetch conversation thread for a specific email/company"""
    email_addr = request.args.get('email')
    if not email_addr:
        return jsonify({"error": "Email is required"}), 400
        
    sent = load_json_file(SENT_EMAILS_FILE)
    replies = load_json_file(REPLIES_FILE)
    
    messages = []
    
    # 1. Sent emails to this recipient
    for s in sent:
        # Check if email_addr is in recipients list (case-insensitive)
        recipients = [r.lower() for r in s.get("recipients", [])]
        if email_addr.lower() in recipients:
            messages.append({
                "id": s.get("id"),
                "type": "sent",
                "content": s.get("body") or s.get("body_preview") or "No Content", 
                "timestamp": s.get("timestamp"),
                "subject": s.get("subject")
            })
            
    # 2. Replies from this sender
    for r in replies:
         if r.get("sender_email", "").lower() == email_addr.lower():
             messages.append({
                "id": r.get("id"),
                "type": "received",
                "content": r.get("body") or r.get("body_preview") or "No Content", 
                "timestamp": r.get("timestamp"),
                "subject": r.get("subject")
            })
            
    # Sort
    def parse_date(date_str):
        if not date_str: return 0
        try:
             return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").timestamp()
        except:
             pass
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str).timestamp()
        except:
            return 0
            
    messages.sort(key=lambda x: parse_date(x['timestamp']))
    
    return jsonify(messages)


if __name__ == '__main__':
    print("Starting Flask server at http://localhost:5000")
    if SMTP_USER:
        print(f"SMTP configured for: {SMTP_USER}")
    else:
        print("Warning: SMTP not configured. Add SMTP_USER and SMTP_PASSWORD to .env to enable email sending.")
    app.run(port=5000, debug=True)
