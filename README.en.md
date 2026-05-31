# 🏠 ThéoOS

> Home operating system — family financial control, smart shopping list, and AI-powered receipt scanning.

---

## 📌 About

**ThéoOS** is a home management system built for daily family use. The name is a tribute to Théo — and the "OS" reflects exactly what the system does: it runs the household.

Built as a portfolio project during my career transition into tech, with a focus on Systems Analysis and Development (FIAP).

The system runs locally on a home network, with a Telegram bot as the mobile interface — allowing family members to add items to the shopping list by voice, text, or receipt photo directly from their phones.

---

## 🧠 Features

- **Smart shopping list** — add items via the dashboard, free text, or voice messages through the Telegram bot
- **AI receipt scanning** — send a photo of a receipt on Telegram → Gemini Vision automatically extracts all items, prices, and categories
- **Bill tracking** — manage bills payable and receivable with automatic due-date alerts via Telegram
- **Budget control** — set monthly limits per category and receive alerts when 80% of the limit is reached
- **Price Detective** — track the price history of any product with a min/max price comparator across purchases
- **Financial reports** — consolidated view of all recorded data with charts and period filters
- **Receipt deduplication** — MD5 hash prevents the same receipt from being registered twice

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3 |
| Web Framework | Flask + Jinja2 |
| Database | SQLite (Flask-SQLAlchemy) |
| AI | Google Gemini 2.5 Flash (Vision + NLP) |
| Bot | pyTelegramBotAPI |
| Frontend | HTML + CSS + JavaScript (vanilla) |
| Windows Service | WinSW (theoos-bot.xml / theoos-web.xml) |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- Telegram bot created via [@BotFather](https://t.me/BotFather)
- [Google AI Studio](https://aistudio.google.com/) API key

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/simoesleandro/theoos-app.git
cd theoos-app

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Edit .env with your credentials
```

### Environment Variables

```env
# Telegram
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

# Google Gemini
GEMINI_API_KEY=

# Flask
SECRET_KEY=
```

### Running

```bash
# Web dashboard
python app.py

# Telegram bot (separate terminal)
python bot.py
```

Access the dashboard at `http://localhost:5000`

### Running as Windows Services (optional)

The `theoos-web.xml` and `theoos-bot.xml` files allow installing the dashboard and bot as native Windows services via [WinSW](https://github.com/winsw/winsw), starting automatically with the system.

---

## 📂 Project Structure

```
theoos-app/
├── app.py               # Flask app — routes, models and core logic
├── bot.py               # Telegram bot with Gemini NLP and Vision
├── requirements.txt
├── theoos-web.xml       # WinSW config — dashboard service
├── theoos-bot.xml       # WinSW config — bot service
├── .env.example
├── .gitignore
├── templates/           # Jinja2 templates
│   ├── base.html
│   ├── index.html
│   ├── lista.html
│   ├── contas.html
│   ├── orcamento.html
│   ├── pesquisa.html
│   ├── relatorios.html
│   └── upload_nota.html
└── static/              # CSS, JS and uploads
```

---

## 💡 Architecture Decisions

**Why Flask instead of Django or FastAPI?**
The system runs on a local home network machine with limited resources. Flask has a minimal footprint with no complex ORM overhead or ASGI server — ideal for a personal project that needs to be simple to maintain and restart.

**Why SQLite instead of PostgreSQL?**
Local database, exclusively family use, no need for concurrent access by multiple simultaneous users. SQLite eliminates the need for a separate database server — zero configuration, zero maintenance.

**Why MD5 hash for receipt deduplication?**
The same receipt can be photographed more than once. The MD5 hash of the image bytes ensures the same fiscal note is never registered twice — without needing to store the original image.

**Why WinSW for local deployment?**
The system needs to start automatically with Windows and survive reboots. WinSW turns Python scripts into native Windows services — no open terminal or task scheduler required.

---

## 👤 Author

**Leandro Simões** — Developer transitioning into tech, studying Systems Analysis and Development (FIAP 2026).

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Leandro%20Sim%C3%B5es-blue?logo=linkedin)](https://www.linkedin.com/in/leandro-sim%C3%B5es-7a0b3537b/)
[![GitHub](https://img.shields.io/badge/GitHub-simoesleandro-black?logo=github)](https://github.com/simoesleandro)

---

## ⚠️ Notice

This project was built for personal and family use. Financial data is private and not shared with third parties.
