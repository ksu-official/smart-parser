# smart-parser
A simple and efficient Telegram bot built with Telethon to aggregate, filter, and translate crypto news from multiple sources into a single topic.

## Key Features:
* **Monitoring:** Watches multiple sources (RootData, CryptoRank, etc.).
* **Anti-Spam/Grouping:** If multiple channels report on the same project, the bot waits 10 minutes (or 5, depending on settings) to combine all facts into one post.
* **Deduplication:** Uses `rapidfuzz` to filter out similar or duplicate messages.
* **Translation:** Automatically translates news into Russian using the Google Translate engine (no API key required).

## Installation:
1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
Configure your API_ID, API_HASH, TARGET_CHAT_ID, and TOPIC_ID in smart_parser.py.

Run the bot:

Bash
python3 smart_parser.py
Why this bot?
It's completely free to run. It doesn't require expensive translation API keys for basic news aggregation, making it a reliable "set it and forget it" tool.
