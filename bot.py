import os
import tempfile
import logging
from dotenv import load_dotenv
load_dotenv() 


# from pathlib import Pat

from pathlib import Path
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable is not set.")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is not set.")

client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are Kolai — a precision voice note intelligence assistant.

Your job is to listen to a voice note and produce a structured, professional brief that anyone can read and immediately understand — even if they weren't present for the recording.

Output the following sections. Only include a section if there is relevant content for it. Never leave a section empty or write "N/A" — simply omit it.

---

📋 SUMMARY
A 2–4 sentence overview of the entire voice note. What was said, by whom (if mentioned), and what it concerns.

---

🎯 KEY DETAILS
Bullet points covering the core facts, context, decisions, or information shared. Be specific. Preserve names, numbers, places, and figures exactly as spoken.

---

👤 ROLES & RESPONSIBILITIES
If any person or team is assigned a task or responsibility, list them clearly:
  • [Name / Role] → [What they are responsible for]

---

⏰ TASKS & DEADLINES
List every action item or task mentioned:
  • [Task description] — Due: [date/time or "ASAP" or "No deadline stated"]

---

📌 IMPORTANT NOTES
Any warnings, blockers, conditions, caveats, or context that is critical to understanding or executing the above.

---

📝 FULL TRANSCRIPT
A clean, punctuated, readable word-for-word transcript of exactly what was said. Fix filler words ("um", "uh", "like") silently. Preserve the speaker's intent and tone accurately.

---

Rules:
- Be precise. Do not invent or assume anything not spoken in the note.
- If a deadline or name is unclear, flag it with [unclear] rather than guessing.
- Write in clear, professional English regardless of how casually the speaker talked.
- Dates should be written in full: e.g. "Friday, June 13" not "Friday the 13th".
- Keep bullet points concise but complete — one idea per bullet.
""".strip()

# ── Mime type map ─────────────────────────────────────────────────────────────
MIME_MAP = {
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}

# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎙️ *Kolai — Voice Intelligence Bot*\n\n"
        "Send me any voice note and I'll return:\n"
        "• A clear summary\n"
        "• Key details & facts\n"
        "• Roles & responsibilities\n"
        "• Tasks with deadlines\n"
        "• Full clean transcript\n\n"
        "Powered by Gemini 2.5 Flash.",
        parse_mode="Markdown"
    )


async def process_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.voice:
        file_obj = msg.voice
        file_ext = ".ogg"
    elif msg.audio:
        file_obj = msg.audio
        file_ext = Path(msg.audio.file_name or "audio.mp3").suffix or ".mp3"
    elif msg.video_note:
        file_obj = msg.video_note
        file_ext = ".mp4"
    else:
        return

    mime_type = MIME_MAP.get(file_ext.lower(), "audio/ogg")
    status_msg = await msg.reply_text("🎧 Analysing your voice note…")

    tmp_path = None
    try:
        tg_file = await ctx.bot.get_file(file_obj.file_id)
        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(tmp_path)

        log.info(f"Downloaded {file_ext} — {os.path.getsize(tmp_path)} bytes")

        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part(text=SYSTEM_PROMPT),
                types.Part(
                    inline_data=types.Blob(
                        mime_type=mime_type,
                        data=audio_bytes
                    )
                ),
                types.Part(text="Process this voice note according to your instructions.")
            ]
        )

        result = response.text.strip()

        if not result:
            await status_msg.edit_text("⚠️ No speech detected or audio was too unclear.")
            return

        await status_msg.delete()

        if len(result) <= 4096:
            await msg.reply_text(result)
        else:
            chunks = [result[i:i+4000] for i in range(0, len(result), 4000)]
            for i, chunk in enumerate(chunks):
                prefix = f"*[Part {i+1}/{len(chunks)}]*\n\n" if len(chunks) > 1 else ""
                await msg.reply_text(prefix + chunk, parse_mode="Markdown")

        log.info("Voice note processed and delivered.")

    except Exception as e:
        log.exception("Processing failed")
        try:
            await status_msg.edit_text(f"❌ Something went wrong:\n`{str(e)}`", parse_mode="Markdown")
        except Exception:
            await msg.reply_text(f"❌ Error: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def unsupported(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a 🎙️ voice message, 🎵 audio file, or 📹 video note and I'll break it down for you."
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))

    app.add_handler(MessageHandler(filters.VOICE, process_voice))
    app.add_handler(MessageHandler(filters.AUDIO, process_voice))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, process_voice))
    app.add_handler(MessageHandler(filters.ALL, unsupported))

    log.info("Kolai is live. Waiting for voice notes…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()