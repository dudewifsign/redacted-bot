import sqlite3
from typing import Optional, List, Tuple

DB_PATH = "bot.db"

def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS wallets (
        telegram_user_id INTEGER PRIMARY KEY,
        username TEXT,
        wallet TEXT NOT NULL,
        last_signature TEXT
    )
    """)
    conn.commit()
    conn.close()

def upsert_wallet(telegram_user_id: int, username: str, wallet: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO wallets (telegram_user_id, username, wallet, last_signature)
    VALUES (?, ?, ?, NULL)
    ON CONFLICT(telegram_user_id) DO UPDATE SET
        username=excluded.username,
        wallet=excluded.wallet
    """, (telegram_user_id, username, wallet))
    conn.commit()
    conn.close()

def remove_wallet(telegram_user_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM wallets WHERE telegram_user_id=?", (telegram_user_id,))
    conn.commit()
    conn.close()

def list_wallets() -> List[Tuple[int, str, str, Optional[str]]]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT telegram_user_id, username, wallet, last_signature FROM wallets")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_last_signature(telegram_user_id: int) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT last_signature FROM wallets WHERE telegram_user_id=?", (telegram_user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def set_last_signature(telegram_user_id: int, signature: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE wallets SET last_signature=? WHERE telegram_user_id=?", (signature, telegram_user_id))
    conn.commit()
    conn.close()
