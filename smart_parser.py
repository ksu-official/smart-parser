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

# Replace these with your real values in .env or directly here
API_ID    = int(os.getenv("API_ID",    "YOUR_API_ID_HERE"))
API_HASH  =     os.getenv("API_HASH",  "YOUR_API_HASH_HERE")
DEEPL_KEY =     os.getenv("DEEPL_KEY", "YOUR_DEEPL_API_KEY_HERE")

TARGET_CHAT_ID = -1000000000000   # Replace with your target chat ID
TARGET_TOPIC_ID = 123456          # Replace with your topic/thread ID
MEMORY_DAYS = 7                   # How many days to keep project history

SOURCE_CHANNELS = [
    "-----------------",
    "---------------",
    "-------------",
    "-----------",
    "--------",
]

client = TelegramClient("aggregator_session", API_ID, API_HASH)
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
    """Extract a clean project name from raw text."""
    garbage_words = {"NEW", "THE", "A", "AN", "THIS", "JUST", "MOST"}

    # Pattern: [Something] ProjectName ...
    m = re.match(r"

\[.*?\]

\s+([A-Za-z0-9][A-Za-z0-9\.\-]{1,25})", text)
    if m:
        candidate = m.group(1).upper()
        if candidate not in garbage_words:
            return candidate

    # Pattern: ProjectName:
    m = re.match(r"([A-Za-z0-9\-]{2,30})\s*[:\-]", text)
    if m:
        candidate = m.group(1).upper()
        if candidate not in garbage_words:
            return candidate

    # Pattern: [ProjectName]
    m = re.search(r"

\[([A-Za-z0-9\-\s]{2,40})\]

", text)
    if m:
        name = m.group(1).strip().upper()
        garbage_phrases = {"----", "-----", "-----", "-----", "-----", "-------"}
        if not any(g in name for g in garbage_phrases):
            return name

    # Fallback: first word
    first = text.split()[0].strip(",.:!#[]()").upper()
    if 2 <= len(first) <= 20 and first.isalnum() and first not in garbage_words:
        return first

    return "UNKNOWN"


def protect_and_translate(text: str) -> str:
    """Translate text using DeepL while protecting project names."""
    ignore = {"---", "---", "---", "---", "---", "---", "---", "---", "--", "--"}

    names = sorted(
        [n for n in set(re.findall(r'\b[A-Z][A-Za-z0-9]{2,}\b', text)) if n not in ignore],
        key=len,
        reverse=True,
    )

    placeholders = {}
    temp = text

    for i, name in enumerate(names):
        key = f"__PH_{i}__"
        placeholders[key] = name
        temp = temp.replace(name, key)

    try:
        translated = translator_deepl.translate_text(temp, target_lang="RU").text
    except Exception as e:
        print(f"⚠️ DeepL error: {e}, fallback → Google Translate")
        translated = GoogleTranslator(source="auto", target="ru").translate(temp)

    for key, name in placeholders.items():
        translated = translated.replace(key, name)

    return translated


def extract_twitter(text: str):
    m = re.search(r'(https?://(?:x\.com|twitter\.com)/\S+)', text)
    return m.group(1) if m else None


def format_single(project: str, en: str, ru: str) -> str:
    """Format a single update."""
    tw = extract_twitter(en)
    tw_line = f"\n\n🔗 [Twitter]({tw})" if tw else ""
    return (
        f"🚀 **{project}**\n\n"
        f"🔤 **EN:**\n{en.strip()}\n\n"
        f"📝 **RU:**\n{ru.strip()}"
        f"{tw_line}"
    )


def format_updated(project: str, en_blocks: list, ru_blocks: list) -> str:
    """Format a multi-update post."""
    tw = extract_twitter("\n".join(en_blocks))
    tw_line = f"\n\n🔗 [Twitter]({tw})" if tw else ""

    parts = []
    for i, (e, r) in enumerate(zip(en_blocks, ru_blocks), 1):
        parts.append(
            f"📌 **Update #{i}**\n"
            f"🔤 {e.strip()}\n\n"
            f"📝 {r.strip()}"
        )

    body = "\n\n─────────────\n\n".join(parts)
    return f"🚀 **{project}**\n\n{body}{tw_line}"


# === MAIN HANDLER ===

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event) -> None:
    if not event.message.text:
        return

    raw = event.message.text
    project = extract_project_name(raw)
    cleaned_en = re.sub(r"t\.me/\S+|@\S+", "", raw).strip()

    if len(cleaned_en) < 5:
        return

    print(f"📥 [{project}] New message received")
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
                print(f"🚫 Duplicate for {project}, skipping")
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
                print(f"🔄 Updated post: {project} ({len(new_en_blocks)} updates)")

            except (MessageNotModifiedError, MessageIdInvalidError) as e:
                print(f"⚠️ edit_message failed ({e}), sending new post")
                sent = await client.send_message(
                    TARGET_CHAT_ID, full, reply_to=TARGET_TOPIC_ID, link_preview=False
                )
                db.execute(
                    "UPDATE buffer SET msg_id=?, info_en=?, info_ru=?, timestamp=CURRENT_TIMESTAMP WHERE project=?",
                    (sent.id, new_en, new_ru, project),
                )
                db.commit()

        else:
            full = format_single(project, cleaned_en, translated_ru)
            sent = await client.send_message(
                TARGET_CHAT_ID, full, reply_to=TARGET_TOPIC_ID, link_preview=False
            )
            db.execute(
                "INSERT OR REPLACE INTO buffer (project, info_en, info_ru, msg_id) VALUES (?, ?, ?, ?)",
                (project, cleaned_en, translated_ru, sent.id),
            )
            db.commit()
            print(f"🆕 New project: {project}")


# === AUTO CLEAN DB ===

async def auto_clean_db() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            db.execute(
                "DELETE FROM buffer WHERE timestamp < datetime('now', ?)",
                (f"-{MEMORY_DAYS} days",),
            )
            db.commit()
            print("🧹 Database cleaned")
        except Exception as e:
            print(f"⚠️ DB cleanup error: {e}")


# === QR LOGIN ===

async def sign_in_with_qr() -> None:
    qr_login = await client.qr_login()
    last = None

    while not qr_login.is_logged_in():
        if qr_login.url != last:
            qr = qrcode.QRCode()
            qr.add_data(qr_login.url)
            qr.print_ascii(invert=True)
            print("\nScan this QR in Telegram → Devices → Link Desktop")
            last = qr_login.url
        try:
            await qr_login.wait(timeout=15)
            break
        except asyncio.TimeoutError:
            qr_login = await client.qr_login()


# === MAIN ===

async def main() -> None:
    await client.connect()

    if not await client.is_user_authorized():
        try:
            await sign_in_with_qr()
        except SessionPasswordNeededError:
            pw = input("Enter your 2FA password: ")
            await client.sign_in(password=pw)

    print(
        f"\n🚀 BOT STARTED\n"
        f"   • Each message = separate post\n"
        f"   • Same project = post editing\n"
        f"   • Duplicates ignored\n"
        f"   • Memory: {MEMORY_DAYS} days\n"
    )
    asyncio.create_task(auto_clean_db())

    try:
        await client.run_until_disconnected()
    finally:
        db.close()
        print("🛑 Bot stopped, DB closed")


if __name__ == "__main__":
    client.loop.run_until_complete(main())
