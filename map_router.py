
import os
import json
import time
import smtplib
from typing import List, Optional
from datetime import datetime
import pandas as pd
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException, BackgroundTasks, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import google.generativeai as genai
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

router = APIRouter()

# --- Config & Constants ---
MASTER_CSV = "d:/anticrisp/master.csv"
TEMP_DIR = "d:/anticrisp/uploads"
SENT_EMAILS_FILE = "d:/anticrisp/sent_emails.json"
REPLIES_FILE = "d:/anticrisp/replies.json"

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Ensure sentinel files exist
if not os.path.exists(SENT_EMAILS_FILE):
    with open(SENT_EMAILS_FILE, 'w') as f:
        json.dump([], f)
if not os.path.exists(REPLIES_FILE):
    with open(REPLIES_FILE, 'w') as f:
        json.dump([], f)

# Gemini Config
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-2.5-flash"

# Deepgram
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "c554b2d7b8a11dbd610656d1bb951c27a2dc7901") # Fallback to key seen in config.js

# SMTP (simulated or env)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

STANDARD_HEADERS = [
    "Company Name", "Latitude", "Longitude", "Address", "City", "State", 
    "Country", "Industry", "Company Type", "Product Category", 
    "Product Name", "Revenue", "Potential", "Website", "Phone", "Email", "Employee Details"
]

# --- Helpers ---
def read_csv_robust(filepath):
    encodings = ['utf-8', 'latin1', 'cp1252', 'ISO-8859-1']
    for enc in encodings:
        try:
            return pd.read_csv(filepath, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(filepath, encoding='utf-8', errors='replace')

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
    company_name = "Unknown Company"
    # Basic lookup
    try:
        if os.path.exists(MASTER_CSV):
             df = read_csv_robust(MASTER_CSV)
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
        "body": body,
        "body_preview": body[:100] + "..." if len(body) > 100 else body
    }
    sent_emails.append(entry)
    save_json_file(SENT_EMAILS_FILE, sent_emails)

# --- Routes ---

@router.get("/api/master-data")
async def get_master_data():
    try:
        if os.path.exists(MASTER_CSV):
            df = read_csv_robust(MASTER_CSV).fillna('')
            data = df.to_dict(orient='records')
            return data
        else:
            return []
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

class VoiceSearchRequest(BaseModel):
    query: str

@router.post("/api/voice-search")
async def voice_search(data: VoiceSearchRequest):
    query = data.query
    if not query:
        return {}
    
    # Extract filters using Gemini
    data_columns_str = ", ".join(STANDARD_HEADERS)
    prompt = f"""
    You are an enterprise data query engine.
    Goal: Extract filters to query a dataset with these columns:
    {data_columns_str}

    The frontend expects a specific JSON structure:
    {{
      "city": "",
      "state": "",
      "country": "",
      "industries": [],
      "productCategory": "",
      "productNameKeywords": []
    }}
    
    User query: {query}
    Return ONLY valid JSON.
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        text = response.text.strip()
        # Clean markdown
        if text.startswith("```json"): text = text[7:]
        if text.endswith("```"): text = text[:-3]
        return json.loads(text)
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {}

@router.get("/api/deepgram-config")
async def get_deepgram_config():
    return {
        "apiKey": DEEPGRAM_API_KEY,
        "settings": {
            "language": "en-IN",
            "model": "nova-2",
            "smart_format": True,
            "punctuate": True,
            "interim_results": True
        }
    }

@router.get("/api/smtp-config")
async def get_smtp_config():
    is_configured = bool(SMTP_USER and SMTP_PASSWORD)
    return {
        "configured": is_configured,
        "senderEmail": SMTP_USER if is_configured else None,
        "userEmail": SMTP_USER if is_configured else None
    }

@router.post("/api/send-email")
async def send_email(request: Request):
    # Handle both JSON and Form data manually for flexibility
    content_type = request.headers.get("content-type", "")
    recipients = []
    subject = ""
    body = ""
    attachments = []

    if "application/json" in content_type:
        data = await request.json()
        recipients = data.get("recipients", [])
        subject = data.get("subject", "")
        body = data.get("body", "")
    elif "multipart/form-data" in content_type:
        form = await request.form()
        recipients_raw = form.get("recipients")
        recipients = json.loads(recipients_raw) if recipients_raw else []
        subject = form.get("subject", "")
        body = form.get("body", "")
        # Attachments not fully implemented in this port for brevity, but placeholders exist
    
    if not SMTP_USER or not SMTP_PASSWORD:
        return JSONResponse(status_code=400, content={"error": "SMTP not configured"})

    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        
        success_count = 0
        failed_recipients = []
        
        for recipient in recipients:
            try:
                msg['To'] = recipient
                server.sendmail(SMTP_USER, recipient, msg.as_string())
                success_count += 1
                del msg['To']
            except Exception as e:
                failed_recipients.append({"email": recipient, "error": str(e)})
                if 'To' in msg: del msg['To']
        
        server.quit()
        
        log_sent_email(recipients, subject, body)
        
        if success_count == 0:
            return JSONResponse(status_code=500, content={"error": "Failed to send to all", "failed": failed_recipients})
        
        return {
            "message": f"Sent {success_count} emails",
            "success_count": success_count,
            "failed": failed_recipients
        }
    except Exception as e:
         return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/api/generate-email")
async def generate_email(data: dict):
    command = data.get("command")
    if not command: return {}
    
    prompt = f"""
    Generate a professional email based on: "{command}"
    Return JSON: {{ "subject": "...", "body": "..." }}
    """
    model = genai.GenerativeModel(MODEL_NAME)
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    return json.loads(response.text)

@router.post("/api/generate-subject")
async def generate_subject(data: dict):
    body = data.get("body", "")
    if not body: return {}
    prompt = f"Generate a subject line for: {body}. Return only text."
    model = genai.GenerativeModel(MODEL_NAME)
    response = model.generate_content(prompt)
    return {"subject": response.text.strip().replace('"', '')}

@router.post("/api/append-email")
async def append_email(data: dict):
    command = data.get("command")
    existing = data.get("existingBody")
    prompt = f"""
    Modify this email: "{existing}"
    Based on request: "{command}"
    Return JSON: {{ "modifiedBody": "..." }}
    """
    model = genai.GenerativeModel(MODEL_NAME)
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    text = response.text.replace('```json', '').replace('```', '')
    parsed = json.loads(text)
    return {"appendedBody": parsed.get("modifiedBody")}

@router.get("/api/email-history")
async def get_email_history():
    sent = load_json_file(SENT_EMAILS_FILE)
    replies = load_json_file(REPLIES_FILE)
    # Simplify for list
    combined = []
    for s in sent:
        s["viewed"] = True
        combined.append(s)
    combined.extend(replies)
    # Sort by timestamp desc
    combined.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return combined

