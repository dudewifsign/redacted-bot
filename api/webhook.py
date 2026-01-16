import os
import requests
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")  # ton groupe -100...
HELIUS_WEBHOOK_SECRET = os.getenv("HELIUS_WEBHOOK_SECRET", "")  # optionnel

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

@app.post("/api/webhook")
async def helius_webhook(req: Request):
    # (optionnel) check signature / secret si tu veux sécuriser
    data = await req.json()

    # Helius webhook = souvent une liste d'events/transactions
    # On fait simple V1 : on print un message brut
    # Ensuite on fera BUY/SELL propre.
    try:
        if isinstance(data, list) and len(data) > 0:
            tx = data[0]
            sig = tx.get("signature", "unknown")
            desc = tx.get("description", "New Solana activity detected")
        else:
            sig = "unknown"
            desc = "New Solana activity detected"

        send_telegram(f"👀 Activity détectée\n{desc}\nSignature: {sig}")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
