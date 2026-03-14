import asyncio
import sqlite3
import re
import qrcode
import deepl
import os
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError,
    MessageNotModifiedError,
    MessageIdInvalidError,
)
from deep_translator import GoogleTranslator
from rapidfuzz import fuzz
from dotenv import load_dotenv

# === CONFIG ===
load_dotenv()

API_ID    = os.getenv("API_ID")
API_HASH  = os.getenv("API_HASH")
DEEPL_KEY = os.getenv("DEEPL_KEY")

TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")
TOPIC_ID       = os.getenv("TOPIC_ID")
MEMORY_DAYS    = int(os.getenv("MEMORY_DAYS", "7"))

SOURCES = os.getenv("SOURCES", "").split(",")

if not API_ID or not API_HASH:
    raise RuntimeError("❌ Missing API_ID or API_HASH in .env")

API_ID = int(API_ID)
TARGET_CHAT_ID = int(TARGET_CHAT_ID) if TARGET_CHAT_ID else None
TOPIC_ID = int(TOPIC_ID) if TOPIC_ID else None

client           = TelegramClient("session_name", API_ID, API_HASH)
translator_deepl = deepl.Translator(DEEPL_KEY)

# === DATABASE ===
db = sqlite3.connect("buffer.db", check_same_thread=False)
db.execute("""
    CREATE TABLE IF NOT EXISTS buffer (
        project   TEXT UNIQUE,
        info_en   TEXT,
        info_ru   TEXT,
        msg_id    INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")
db.execute("CREATE INDEX IF NOT EXISTS idx_project   ON buffer(project)")
db.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON buffer(timestamp)")
db.commit()

lock = asyncio.Lock()


# === HELPERS ===

def extract_project_name(text: str) -> str:
    garbage_words = {"NEW", "THE", "A", "AN", "THIS", "JUST", "MOST"}

    m = re.match(r"

\[.*?\]

\s+([A-Za-z0-9][A-Za-z0-9\.\-]{1,25})", text)
    if m:
        candidate = m.group(1).upper()
        if candidate not in garbage_words:
            return candidate

    m = re.match(r"([A-Za-z0-9\-]{2,30})\s*[:\-]", text)
    if m:
        candidate = m.group(1).upper()
        if candidate not in garbage_words:
            return candidate

    m = re.search(r"

\[([A-Za-z0-9\-\s]{2,40})\]

", text)
    if m:
        name = m.group(1).strip().upper()
        garbage_phrases = {"NEW", "INVESTMENT", "ALERT", "FUNDRAISING", "ROOTDATA", "MOST POPULAR"}
        if not any(g in name for g in garbage_phrases):
            return name

    first = re.sub(r'[^A-Za-z0-9]', '', text.split()[0]).upper()
    if 2 <= len(first) <= 20 and first not in garbage_words:
        return first

    return "UNKNOWN"


def protect_and_translate(text: str) -> str:
    ignore = {"THE", "THIS", "MOST", "NEW", "AND", "FROM", "WITH", "FOR", "IN", "ON"}
    names = sorted(
        [n for n in set(re.findall(r'\b[A-Z][A-Za-z0-9]{2,}\b', text)) if n not in ignore],
        key=len, reverse=True,
    )

    placeholders = {}
    temp = text

    for i, name in enumerate(names):
        key = f"__PH_{i}__"
        placeholders[key] = name
        temp = re.sub(rf'\b{re.escape(name)}\b', key, temp)

    try:
        translated = translator_deepl.translate_text(temp, target_lang="RU").text
    except Exception:
        translated = GoogleTranslator(source="auto", target="ru").translate(temp)

    for key, name in placeholders.items():
        translated = translated.replace(key, name)

    return translated


def extract_twitter(text: str):
    m = re.search(r'(https?://(?:x\.com|twitter\.com|t\.co|mobile\.twitter\.com)/\S+)', text)
    return m.group(1) if m else None


def format_single(project: str, en: str, ru: str) -> str:
    tw = extract_twitter(en)
    tw_line = f"\n\n🔗 [Twitter]({tw})" if tw else ""
    return (
        f"🚀 **{project}**\n\n"
        f"🔤 **EN:**\n{en.strip()}\n\n"
        f"📝 **RU:**\n{ru.strip()}"
        f"{tw_line}"
    )


def format_updated(project: str, en_blocks: list, ru_blocks: list) -> str:
    tw = extract_twitter("\n".join(en_blocks))
    tw_line = f"\n\n🔗 [Twitter]({tw})" if tw else ""

    sources = []
    clean_en_blocks = []
    clean_ru_blocks = []

    for e, r in zip(en_blocks, ru_blocks):
        src_lines = [line for line in e.splitlines() if line.strip().lower().startswith("source:")]
        sources.extend(src_lines)

        body_en = "\n".join(l for l in e.splitlines() if not l.strip().lower().startswith("source:")).strip()
        body_ru = "\n".join(l for l in r.splitlines() if not l.strip().lower().startswith("source:")).strip()

        clean_en_blocks.append(body_en)
        clean_ru_blocks.append(body_ru)

    combined_en = "\n\n---\n\n".join(clean_en_blocks)
    combined_ru = "\n\n---\n\n".join(clean_ru_blocks)

    seen = set()
    unique_sources = []
    for s in sources:
        if s not in seen:
            seen.add(s)
            unique_sources.append(s)

    sources_block = ("\n\n📎 **Sources:**\n" + "\n".join(unique_sources)) if unique_sources else ""

    return (
        f"🚀 **{project}**\n\n"
        f"🔤 **EN:**\n{combined_en}\n\n"
        f"📝 **RU:**\n{combined_ru}"
        f"{sources_block}"
        f"{tw_line}"
    )


# === MAIN HANDLER ===

@client.on(events.NewMessage(chats=SOURCES))
async def handler(event):
    if not event.message.text:
        return

    raw = event.message.text
    project = extract_project_name(raw)
    cleaned_en = re.sub(r"t\.me/\S+|@\S+", "", raw).strip()

    if len(cleaned_en) < 5:
        return

    translated_ru = protect_and_translate(cleaned_en)

    async with lock:
        cursor = db.execute(
            "SELECT info_en, info_ru, msg_id FROM buffer "
            "WHERE project = ? AND timestamp > datetime('now', ?)",
            (project, f"-{MEMORY_DAYS} days"),
        )
        row = cursor.fetchone()

        if row:
            old_en, old_ru, msg_id = row

            if fuzz.token_set_ratio(cleaned_en, old_en) > 93:
                return

            old_en_blocks = old_en.split("\n\n---\n\n")
            old_ru_blocks = old_ru.split("\n\n---\n\n")

            new_en_blocks = old_en_blocks + [cleaned_en]
            new_ru_blocks = old_ru_blocks + [translated_ru]

            new_en = "\n\n---\n\n".join(new_en_blocks)
            new_ru = "\n\n---\n\n".join(new_ru_blocks)

            full = format_updated(project, new_en_blocks, new_ru_blocks)

            try:
                await client.edit_message(TARGET_CHAT_ID, msg_id, full, link_preview=False)
                db.execute(
                    "UPDATE buffer SET info_en=?, info_ru=?, timestamp=CURRENT_TIMESTAMP WHERE msg_id=?",
                    (new_en, new_ru, msg_id),
                )
                db.commit()

            except (MessageNotModifiedError, MessageIdInvalidError):
                sent = await client.send_message(
                    TARGET_CHAT_ID, full, reply_to=TOPIC_ID, link_preview=False
                )
                db.execute(
                    "UPDATE buffer SET msg_id=?, info_en=?, info_ru=?, timestamp=CURRENT_TIMESTAMP WHERE project=?",
                    (sent.id, new_en, new_ru, project),
                )
                db.commit()

        else:
            full = format_single(project, cleaned_en, translated_ru)
            sent = await client.send_message(
                TARGET_CHAT_ID, full, reply_to=TOPIC_ID, link_preview=False
            )
            db.execute(
                "INSERT OR REPLACE INTO buffer (project, info_en, info_ru, msg_id) VALUES (?, ?, ?, ?)",
                (project, cleaned_en, translated_ru, sent.id),
            )
            db.commit()


# === AUTO CLEAN DB ===

async def auto_clean_db():
    while True:
        await asyncio.sleep(3600)
        try:
            db.execute(
                "DELETE FROM buffer WHERE timestamp < datetime('now', ?)",
                (f"-{MEMORY_DAYS} days",),
            )
            db.execute("VACUUM")
            db.commit()
        except Exception:
            pass


# === QR LOGIN ===

async def sign_in_with_qr():
    qr_login = await client.qr_login()
    last = None

    while True:
        if qr_login.url != last:
            qr = qrcode.QRCode()
            qr.add_data(qr_login.url)
            qr.print_ascii(invert=True)
            last = qr_login.url
        try:
            await qr_login.wait(timeout=15)
            break
        except asyncio.TimeoutError:
            qr_login = await client.qr_login()
        except SessionPasswordNeededError:
            raise
        except Exception:
            break


# === MAIN ===

async def main():
    await client.connect()

    if not await client.is_user_authorized():
        try:
            await sign_in_with_qr()
        except SessionPasswordNeededError:
            pw = input("Enter 2FA password: ")
            await client.sign_in(password=pw)

    asyncio.create_task(auto_clean_db())

    try:
        await client.run_until_disconnected()
    finally:
        db.close()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
    
