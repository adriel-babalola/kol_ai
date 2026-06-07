# 🎙️ Kolai — Voice Intelligence Bot

Sends voice notes → returns structured briefs with summary, key details, roles, tasks, deadlines, and full transcript. Powered by Gemini 2.5 Flash.

---

## Setup

### 1. Get a Telegram Bot Token
- Message **@BotFather** on Telegram → `/newbot` → copy the token

### 2. Get a Gemini API Key
- Go to https://aistudio.google.com/app/apikey
- Free tier is generous — plenty for personal use

### 3. Install
```bash
pip install -r requirements.txt
```

### 4. Set credentials
```bash
export TELEGRAM_TOKEN="your_telegram_token"
export GEMINI_API_KEY="your_gemini_key"
```

### 5. Run
```bash
python bot.py
```

---

## What the bot returns for every voice note

| Section | What it contains |
|---|---|
| 📋 Summary | 2–4 sentence overview |
| 🎯 Key Details | Facts, names, numbers, decisions |
| 👤 Roles & Responsibilities | Who is doing what |
| ⏰ Tasks & Deadlines | Every action item with due date |
| 📌 Important Notes | Warnings, blockers, caveats |
| 📝 Full Transcript | Clean word-for-word text |

---

## Keep running 24/7
Deploy free on **Railway** or **Render** — just set the two environment variables and push the code.
# kol_ai
