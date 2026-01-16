from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, List

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from db import init_db, upsert_wallet, remove_wallet, list_wallets, set_last_signature
from helius import HeliusClient

SOL_MINT = "So11111111111111111111111111111111111111112"
WALLET_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")  # base58 (approx)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "15"))

if not BOT_TOKEN or not HELIUS_API_KEY or not CHANNEL_ID:
    raise RuntimeError("Manque BOT_TOKEN / HELIUS_API_KEY / CHANNEL_ID dans .env")

helius = HeliusClient(HELIUS_API_KEY)

def fmt_user(update: Update) -> str:
    u = update.effective_user
    if not u:
        return "@unknown"
    if u.username:
        return f"@{u.username}"
    return u.full_name

def short_sig(sig: str) -> str:
    return sig[:6] + "..." + sig[-6:]

def extract_swap_summary(tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    On essaye de repérer un SWAP et d’extraire :
      - direction (buy/sell) du token vs SOL
      - token symbol, token amount
      - sol amount
    Les payloads Enhanced de Helius contiennent des champs de haut niveau (transactionType, events, tokenTransfers, nativeTransfers, etc.)
    Comme ça peut varier selon la source, on fait une extraction "best effort".
    """
    tx_type = tx.get("type") or tx.get("transactionType")
    if tx_type and str(tx_type).upper() not in {"SWAP", "UNKNOWN"}:
        # On ne garde que les swaps (ou unknown qu'on inspectera via tokenTransfers).
        pass

    token_transfers: List[Dict[str, Any]] = tx.get("tokenTransfers") or []
    native_transfers: List[Dict[str, Any]] = tx.get("nativeTransfers") or []
    events = tx.get("events") or {}

    # 1) Si Helius donne un event swap clair
    swap = events.get("swap") if isinstance(events, dict) else None
    if isinstance(swap, dict):
        # Champs typiques: nativeInput/nativeOutput, tokenInputs/tokenOutputs, etc.
        # On fait un parsing tolérant.
        native_in = swap.get("nativeInput")
        native_out = swap.get("nativeOutput")

        token_in = None
        token_out = None

        ti = swap.get("tokenInputs")
        to = swap.get("tokenOutputs")
        if isinstance(ti, list) and ti:
            token_in = ti[0]
        if isinstance(to, list) and to:
            token_out = to[0]

        # Si on a SOL d’un côté et token de l’autre :
        # - Achat: on "dépense" SOL (nativeInput) et on "reçoit" token (tokenOutputs)
        # - Vente: on "reçoit" SOL (nativeOutput) et on "dépense" token (tokenInputs)
        if native_in and token_out:
            return {
                "side": "BUY",
                "token_symbol": token_out.get("symbol") or "TOKEN",
                "token_amount": token_out.get("amount"),
                "sol_amount": (native_in.get("amount") / 1e9) if isinstance(native_in.get("amount"), (int, float)) else None,
            }
        if native_out and token_in:
            return {
                "side": "SELL",
                "token_symbol": token_in.get("symbol") or "TOKEN",
                "token_amount": token_in.get("amount"),
                "sol_amount": (native_out.get("amount") / 1e9) if isinstance(native_out.get("amount"), (int, float)) else None,
            }

    # 2) Fallback: on tente avec tokenTransfers + nativeTransfers
    # Heuristique : si tx contient un transfert SOL sortant + transfert token entrant => BUY
    #              si tx contient transfert token sortant + SOL entrant => SELL
    # Pour du “vrai swap”, ça marche souvent.
    sol_out_lamports = 0
    sol_in_lamports = 0
    for nt in native_transfers:
        amt = nt.get("amount")
        if not isinstance(amt, int):
            continue
        # Helius met souvent "fromUserAccount"/"toUserAccount"
        # On ne connaît pas ici l’owner, donc on ne peut pas dire si c’est IN/OUT sans contexte.
        # Donc on ne conclut pas à 100% en fallback.
        # -> on se contente de détecter qu'il y a du SOL qui bouge + un tokenTransfer unique.
        # (Le message sera “swap détecté” si incertain.)
        pass

    # Si un seul token transfer et un label swap-like
    if token_transfers:
        tt = token_transfers[0]
        symbol = tt.get("symbol") or "TOKEN"
        amount = tt.get("tokenAmount") or tt.get("amount")  # dépend des payloads
        return {
            "side": "SWAP",
            "token_symbol": symbol,
            "token_amount": amount,
            "sol_amount": None,
        }

    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Redacted BOT 👀\n\n"
        "Commandes:\n"
        "/register <wallet_solana>\n"
        "/unregister\n"
        "/list\n"
        "/chart <token_address>\n\n"
        "Je surveille les swaps et je poste dans le channel."
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /register <wallet_solana>")
        return

    wallet = context.args[0].strip()
    if not WALLET_RE.match(wallet):
        await update.message.reply_text("Ça ne ressemble pas à une adresse Solana valide (base58).")
        return

    user = update.effective_user
    if not user:
        await update.message.reply_text("Impossible de lire ton user Telegram.")
        return

    username = user.username or user.full_name
    upsert_wallet(user.id, username, wallet)
    await update.message.reply_text(f"✅ Wallet enregistré pour {fmt_user(update)} : `{wallet}`", parse_mode="Markdown")

async def unregister(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    remove_wallet(user.id)
    await update.message.reply_text("🗑️ Wallet supprimé.")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    rows = list_wallets()
    if not rows:
        await update.message.reply_text("Aucun wallet enregistré.")
        return
    lines = ["Wallets suivis :"]
    for _uid, username, wallet, _last in rows:
        at = f"@{username}" if username and not username.startswith("@") else (username or "@unknown")
        lines.append(f"- {at} → `{wallet}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    V1: on envoie un lien DexScreener + pools trouvées via l’API DexScreener token-pairs.
    Endpoint DexScreener docs: /token-pairs/v1/{chainId}/{tokenAddress}. :contentReference[oaicite:4]{index=4}
    """
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /chart <token_address>")
        return
    token = context.args[0].strip()
    if not WALLET_RE.match(token):
        await update.message.reply_text("Adresse de token invalide.")
        return

    import requests
    url = f"https://api.dexscreener.com/token-pairs/v1/solana/{token}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        pairs = r.json()
    except Exception:
        await update.message.reply_text("Erreur en récupérant DexScreener.")
        return

    if not pairs:
        await update.message.reply_text("Aucune pool trouvée sur DexScreener pour ce token.")
        return

    # Prend la première pool (souvent la plus pertinente, mais on améliorera plus tard)
    p = pairs[0]
    pair_url = p.get("url")
    dex = p.get("dexId")
    base = (p.get("baseToken") or {}).get("symbol") or "TOKEN"
    quote = (p.get("quoteToken") or {}).get("symbol") or "???"
    price = p.get("priceUsd")

    msg = (
        f"📊 {base}/{quote} sur {dex}\n"
        f"Prix (USD): {price}\n"
        f"Lien: {pair_url}"
    )
    await update.message.reply_text(msg)

async def poll_once_and_post(app, telegram_user_id: int, username: str, wallet: str, last_sig: Optional[str]) -> Optional[str]:
    """
    Récupère les dernières tx de ce wallet.
    Poste celles qui sont nouvelles (par rapport à last_sig).
    Retourne le nouveau last_sig.
    """
    try:
        txs = helius.get_transactions_by_address(wallet, limit=20)
    except Exception:
        return last_sig

    if not txs:
        return last_sig

    # Helius renvoie du plus récent -> plus ancien (en général)
    newest_sig = txs[0].get("signature")
    if not newest_sig:
        return last_sig

    # Si on n’a jamais rien vu, on initialise juste le curseur (pour éviter spam au démarrage)
    if not last_sig:
        return newest_sig

    # Collecte toutes les nouvelles jusqu’à tomber sur last_sig
    new_txs: List[Dict[str, Any]] = []
    for tx in txs:
        sig = tx.get("signature")
        if sig == last_sig:
            break
        new_txs.append(tx)

    # On poste de l’ancien vers le récent
    for tx in reversed(new_txs):
        sig = tx.get("signature") or ""
        swap_info = extract_swap_summary(tx)
        if not swap_info:
            continue

        at = f"@{username}" if username and not username.startswith("@") else (username or "@unknown")

        side = swap_info["side"]
        token_symbol = swap_info["token_symbol"]
        token_amount = swap_info.get("token_amount")
        sol_amount = swap_info.get("sol_amount")

        if side in ("BUY", "SELL") and token_amount is not None and sol_amount is not None:
            verb = "acheté" if side == "BUY" else "vendu"
            text = f"🔥 {at} vient d’avoir {verb} {token_amount} ${token_symbol} pour {sol_amount} SOL\n(sig {short_sig(sig)})"
        else:
            text = f"👀 Swap détecté pour {at}: {token_symbol} (détails partiels)\n(sig {short_sig(sig)})"

        await app.bot.send_message(chat_id=CHANNEL_ID, text=text)

    return newest_sig

async def poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    app = context.application
    rows = list_wallets()
    for telegram_user_id, username, wallet, last_sig in rows:
        new_last = await poll_once_and_post(app, telegram_user_id, username, wallet, last_sig)
        if new_last and new_last != last_sig:
            set_last_signature(telegram_user_id, new_last)

def main() -> None:
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("unregister", unregister))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("chart", chart))

    # Job de polling
    app.job_queue.run_repeating(poll_job, interval=POLL_SECONDS, first=5)

    print("Redacted BOT lancé.")
    app.add_error_handler(error_handler)
    app.run_polling()


if __name__ == "__main__":
    main()

import logging
from telegram.ext import Application

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

async def error_handler(update, context):
    logger.exception("Exception while handling an update:", exc_info=context.error)
