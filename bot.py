import os, io, smtplib, requests
from email.mime.text import MIMEText
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

# 1. Your College Notice Page URL
COLLEGE_URL = "https://your-college-website.ac.in/notices"
STATE_FILE = "seen_notices.txt"

def get_latest_notices():
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(COLLEGE_URL, headers=headers, timeout=20)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    notices = []
    # Grabs links that point to PDFs or notice pages
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text().split())
        link = urljoin(COLLEGE_URL, a["href"])
        if len(title) > 5 and (".pdf" in link.lower() or "notice" in link.lower() or "circular" in link.lower()):
            notices.append((title, link))
    return notices[:5] # Check top 5 latest notices

def read_and_summarize(title, link):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = (
        f"Read this college notice titled '{title}'. "
        "Provide a clean, short summary with:\n"
        "1. Who it applies to (Branch/Year)\n"
        "2. Key dates or deadlines\n"
        "3. Exact action required by students."
    )
    
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(link, headers=headers, timeout=30)
    content_type = r.headers.get("Content-Type", "").lower()

    # If the notice is a PDF, upload and read inside the PDF
    if ".pdf" in link.lower() or "application/pdf" in content_type:
        pdf_file = io.BytesIO(r.content)
        uploaded_doc = client.files.upload(
            file=pdf_file,
            config=types.UploadFileConfig(mime_type="application/pdf")
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[uploaded_doc, prompt]
        )
    else:
        # If the notice is a webpage, extract the text inside it
        page_text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ", strip=True)[:15000]
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{prompt}\n\nNotice Content:\n{page_text}"
        )
    return response.text

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message})

def send_email(subject, body):
    sender = os.environ.get("EMAIL_ADDRESS")
    password = os.environ.get("EMAIL_APP_PASSWORD")
    if sender and password:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"📢 College Notice: {subject[:50]}"
        msg["From"] = sender
        msg["To"] = sender
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.send_message(msg)

def main():
    seen = set()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            seen = set(line.strip() for line in f)

    notices = get_latest_notices()
    new_found = False

    for title, link in reversed(notices):
        if link not in seen:
            summary = read_and_summarize(title, link)
            alert_text = f"📢 NEW NOTICE: {title}\n\n{summary}\n\n🔗 Link: {link}"
            
            send_telegram(alert_text)
            send_email(title, alert_text)
            
            seen.add(link)
            new_found = True

    if new_found:
        with open(STATE_FILE, "w") as f:
            for item in seen:
                f.write(f"{item}\n")

if __name__ == "__main__":
    main()
