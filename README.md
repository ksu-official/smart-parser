# 🚀 Smart Crypto Aggregator v2.0

Professional Telegram news engine designed for high-frequency crypto environments. It captures, processes, and intelligently delivers news from multiple sources into a single, organized feed.

### ✨ Key Features:

* **Smart Update Merging**: Instead of cluttering the channel with multiple posts, the engine tracks project developments in real-time and groups updates into single, structured threads.
* **Entity Guard System**: Proprietary logic that protects project names, tickers, and technical terms during translation, ensuring 100% accuracy in crypto-specific terminology.
* **Intelligent Deduplication**: Uses fuzzy logic matching to identify and filter out repetitive information across different sources.
* **Dual-Layer Translation**: Integrated DeepL support with an automatic fallback system to ensure consistent delivery.
* **Automated Data Management**: Features a secure SQLite-based buffer with self-cleaning logic for high-performance monitoring.

### 🛠 Tech Stack:
**Python**, **Telethon**, **SQLite**, **DeepL API**, **RapidFuzz**.

### 📂 Repository Structure:
* `smart_parser.py` — Current production-ready version.
* `/legacy` — Historical milestones and early MVP versions.

---
*Note: This tool is designed as a flexible framework. Users can configure their own data sources and target topics via the configuration section.*
