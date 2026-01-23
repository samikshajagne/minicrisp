import os
import datetime
import json
from fpdf import FPDF
import matplotlib.pyplot as plt
import pandas as pd
from database import get_all_messages_for_customer, get_customer_by_email

DOWNLOADS_DIR = os.path.join("static", "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

class SummaryPDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(80)
        self.cell(30, 10, 'Chat Analysis Report', 0, 0, 'C')
        self.ln(20)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Page ' + str(self.page_no()) + '/{nb}', 0, 0, 'C')

def generate_short_summary_txt(email, summary_text):
    """Generate a downloadable TXT file for a short summary."""
    filename = f"summary_{email.replace('@', '_').replace('.', '_')}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
    filepath = os.path.join(DOWNLOADS_DIR, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"Short Summary for: {email}\n")
        f.write(f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("-" * 40 + "\n\n")
        f.write(summary_text)
    
    return f"/static/downloads/{filename}"

def generate_detailed_summary_pdf(email):
    """Generate a detailed PDF report with charts and analysis."""
    messages = get_all_messages_for_customer(email)
    if not messages:
        return None, "No messages found for this customer."

    # Analysis
    df = pd.DataFrame(messages)
    sent_count = len(df[df['sender'] == 'admin'])
    received_count = len(df[df['sender'] == 'visitor'])
    total_count = len(df)

    # Word analysis (simple)
    all_text = " ".join(df['content'].fillna("").astype(str)).lower()
    words = [w for w in all_text.split() if len(w) > 3] # Skip small words
    word_counts = pd.Series(words).value_counts().head(10)

    # Visualization
    plt.figure(figsize=(10, 6))
    
    # 1. Sent vs Received Pie Chart
    plt.subplot(1, 2, 1)
    plt.pie([sent_count, received_count], labels=['Sent (Admin)', 'Received (Visitor)'], autopct='%1.1f%%', colors=['#4CAF50', '#2196F3'])
    plt.title('Email Volume Distribution')

    # 2. Top Words Bar Chart
    plt.subplot(1, 2, 2)
    word_counts.plot(kind='bar', color='#FF9800')
    plt.title('Top 10 Keywords')
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    chart_filename = f"chart_{email.replace('@', '_')}.png"
    chart_path = os.path.join(DOWNLOADS_DIR, chart_filename)
    plt.savefig(chart_path)
    plt.close()

    # Create PDF
    pdf = SummaryPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font('Arial', '', 12)
    
    cust = get_customer_by_email(email)
    pdf.cell(0, 10, f"Customer: {cust.get('name', 'Unknown')} ({email})", 0, 1)
    pdf.cell(0, 10, f"Analysis Period: {df['timestamp'].min().strftime('%Y-%m-%d')} to {df['timestamp'].max().strftime('%Y-%m-%d')}", 0, 1)
    pdf.ln(10)

    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, "Summary Statistics", 0, 1)
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 10, f"- Total Messages: {total_count}", 0, 1)
    pdf.cell(0, 10, f"- Emails Sent (Admin): {sent_count}", 0, 1)
    pdf.cell(0, 10, f"- Emails Received (Visitor): {received_count}", 0, 1)
    pdf.ln(10)

    # Add Chart
    pdf.image(chart_path, x=10, y=pdf.get_y(), w=190)
    pdf.ln(100) # Space for chart

    # Major Used Words
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, "Keyword Frequency Analysis", 0, 1)
    pdf.set_font('Arial', '', 12)
    for word, count in word_counts.items():
        pdf.cell(0, 10, f"- {word}: {count} occurrences", 0, 1)

    # Final Output
    pdf_filename = f"detailed_summary_{email.replace('@', '_')}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    pdf_path = os.path.join(DOWNLOADS_DIR, pdf_filename)
    pdf.output(pdf_path)
    
    # Cleanup temporary chart
    if os.path.exists(chart_path):
        os.remove(chart_path)
        
    return f"/static/downloads/{pdf_filename}", None
