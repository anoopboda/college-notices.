import os, io, requests, urllib3
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URLS = [
    "https://www.rgukt.ac.in/notices-downloads",
    "https://hub2.rgukt.ac.in/hub/notice/index"
]
STATE_FILE = "seen_notices.txt"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def get_working_model(client):
    preferred = ["gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-2.5-flash"]
    try:
        available = [m.name.replace("models/", "") for m in client.models.list()]
        for p in preferred:
            if p in available:
                return p
        for a in available:
            if "flash" in a and "image" not in a and "tts" not in a:
                return a
    except Exception:
        pass
    return "gemini-3-flash-preview"

def get_latest_notices():
    notices = []
    seen_links = set()

    for base_url in URLS:
        try:
            resp = requests.get(base_url, headers=HEADERS, timeout=25, verify=False)
            soup = BeautifulSoup(resp.text, "html.parser")

            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "javascript:", "mailto:")):
                    continue
                
                full_url = urljoin(base_url, href)
                title = " ".join(a.get_text().split())

                parent = a.find_parent(["li", "tr", "div", "p"])
                context_text = " ".join(parent.get_text().split()) if parent else title

                is_doc = any(k in full_url.lower() for k in [".pdf", "download", "notice", "circular", "attachment", "forms.gle"])
                if is_doc and full_url not in seen_links and len(context_text) > 15:
                    seen_links.add(full_url)
                    clean_title = title if len(title) > 12 else context_text[:120]
                    notices.append((clean_title, full_url, context_text[:1500]))
        except Exception as e:
            print(f"Skipping {base_url}: {e}")

    return notices[:5]

def read_and_summarize(client, model_name, title, link, context_text):
    prompt = (
        f"You are summarizing an official RGUKT college notice.\n"
        f"Notice Title/Context: {context_text}\n\n"
        "Give a clean, short summary with:\n"
        "1. 🎯 Who it applies to (PUC / E1 / E2 / E3 / E4 / Branch)\n"
        "2. 📅 Key Dates & Deadlines\n"
        "3. ✅ Action required by students"
    )

    try:
        r = requests.get(link, headers=HEADERS, timeout=30, verify=False)
        content_type = r.headers.get("Content-Type", "").lower()

        if ".pdf" in link.lower() or "application/pdf" in content_type:
            pdf_file = io.BytesIO(r.content)
            uploaded_doc = client.files.upload(
                file=pdf_file,
                config=types.UploadFileConfig(mime_type="application/pdf")
            )
            response = client.models.generate_content(
                model=model_name,
                contents=[uploaded_doc, prompt]
            )
            return response.text
        else:
            page_text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ", strip=True)[:12000]
            response = client.models.generate_content(
                model=model_name,
                contents=f"{prompt}\n\nFull Page Text:\n{page_text}"
            )
            return response.text
    except Exception:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip().removeprefix("bot")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN secret is empty!")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": message[:4000]})

    # If Chat ID had a typo, auto-detect it from your /start message!
    if resp.status_code != 200:
        print(f"Initial Telegram response ({resp.status_code}): {resp.text}")
        updates = requests.get(f"https://api.telegram.org/bot{token}/getUpdates").json()
        for res in reversed(updates.get("result", [])):
            auto_id = res.get("message", {}).get("chat", {}).get("id")
            if auto_id:
                print(f"Auto-detected Chat ID: {auto_id}. Retrying...")
                resp = requests.post(url, json={"chat_id": auto_id, "text": message[:4000]})
                break

    print(f"Telegram Delivery Status: {resp.status_code} - {resp.text[:200]}")

def main():
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"].strip())
    model_name = get_working_model(client)
    print(f"Using Gemini Model: {model_name}")

    seen = set()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            seen = set(line.strip() for line in f)

    notices = get_latest_notices()
    print(f"Found {len(notices)} notices to check.")
    new_found = False

    for title, link, context_text in reversed(notices):
        if link not in seen:
            print(f"Summarizing: {title}")
            summary = read_and_summarize(client, model_name, title, link, context_text)
            alert_text = f"📢 RGUKT NOTICE:\n{title}\n\n{summary}\n\n🔗 Link: {link}"
            send_telegram(alert_text)
            seen.add(link)
            new_found = True

    if new_found:
        with open(STATE_FILE, "w") as f:
            for item in seen:
                f.write(f"{item}\n")

if __name__ == "__main__":
    main()
