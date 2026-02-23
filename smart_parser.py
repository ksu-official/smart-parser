import asyncio
import sqlite3
import re
import qrcode
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from googletrans import Translator
from rapidfuzz import fuzz

# === CONFIGURATION (PLACEHOLDERS FOR GITHUB) ===
API_ID = 123456
API_HASH = "your_api_hash_here"

SOURCES = [
    "rootdatalabs",
    "CryptorankFundraisingSniper",
    "ico_analytic",
    "crypto_fundraising",
    "just_ksu0000"
]

TARGET_CHAT_ID = 0        # replace with your real chat ID on server
TOPIC_ID = 0              # replace with your real topic ID on server

client = TelegramClient("session_name", API_ID, API_HASH)
translator = Translator()

# === DATABASE ===
db = sqlite3.connect("buffer.db")
db.execute("CREATE TABLE IF NOT EXISTS buffer (project TEXT, info TEXT)")
db.commit()


async def publish_event(project_name):
    await asyncio.sleep(600)  # 10-minute delay

    cursor = db.execute("SELECT info FROM buffer WHERE project = ?", (project_name,))
    rows = cursor.fetchall()

    if rows:
        unique_facts = []
        for (info,) in rows:
            if not any(fuzz.token_set_ratio(info, existing) > 85 for existing in unique_facts):
                unique_facts.append(info)

        # Translation EN → RU
        translated_facts = []
        for fact in unique_facts:
            try:
                translated = translator.translate(fact, src="en", dest="ru").text
                translated_facts.append(translated)
            except:
                translated_facts.append(fact)

        header = f"🚀 Project update: **{project_name}**\n\n"
        body = "\n\n---\n\n".join(translated_facts)

        try:
            await client.send_message(TARGET_CHAT_ID, header + body, reply_to=TOPIC_ID)
        except Exception as e:
            print(f"Send error: {e}")

        db.execute("DELETE FROM buffer WHERE project = ?", (project_name,))
        db.commit()


@client.on(events.NewMessage(chats=SOURCES))
async def handler(event):
    if not event.message.text:
        return

    text = event.message.text

    # Extract project name
    project_name = text.split()[0].strip(",.:!#").upper()

    # Clean text
    cleaned = re.sub(r"t\.me/\S+|@\S+", "", text).strip()

    # Start timer if first message
    cursor = db.execute("SELECT info FROM buffer WHERE project = ?", (project_name,))
    if not cursor.fetchone():
        asyncio.create_task(publish_event(project_name))

    # Save to DB
    db.execute("INSERT INTO buffer (project, info) VALUES (?, ?)", (project_name, cleaned))
    db.commit()


# === AUTHENTICATION (DO NOT MODIFY) ===
async def sign_in_with_qr():
    print("\n--- QR CODE GENERATION ---")
    qr_login = await client.qr_login()
    last_qr = None

    while True:
        if qr_login.url != last_qr:
            qr = qrcode.QRCode()
            qr.add_data(qr_login.url)
            qr.print_ascii(invert=True)
            print("\nSCAN THIS CODE IN TELEGRAM")
            print("(Settings > Devices > Link Desktop Device)")
            last_qr = qr_login.url

        try:
            return await qr_login.wait(timeout=15)
        except asyncio.TimeoutError:
            await qr_login.recreate()


async def main():
    await client.connect()

    if not await client.is_user_authorized():
        try:
            await sign_in_with_qr()
        except SessionPasswordNeededError:
            print("\n🔑 CLOUD PASSWORD REQUIRED!")
            while True:
                pw = input("Enter your cloud password (2FA): ")
                try:
                    await client.sign_in(password=pw)
                    print("✅ Successfully logged in with password!")
                    break
                except Exception as e:
                    print(f"❌ Error: {e}. Try again.")

    print("\n🚀 BOT STARTED! You can now close the terminal.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
