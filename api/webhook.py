import os
import requests
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

# IMPORTANT: route "/" car le fichier webhook.py correspond déjà à /api/webhook
@app.post("/")
async def helius_webhook(req: Request):
    data = await req.json()
    send_telegram(f"👀 Webhook reçu: {str(data)[:800]}")
    return {"ok": True}
