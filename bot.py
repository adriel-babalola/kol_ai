import os
import tempfile
import logging
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ─────────────────────────────────────────────────────────────
# Environment Variables
# ─────────────────────────────────────────────────────────────

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable is not set.")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is not set.")

# ─────────────────────────────────────────────────────────────
# Gemini Client
# ─────────────────────────────────────────────────────────────

client = genai.Client(api_key=GEMINI_API_KEY)

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are Kolai — a precision voice note intelligence assistant.

Your job is to listen to a voice note and produce a structured, professional brief that anyone can read and immediately understand — even if they weren't present for the recording.

Output the following sections. Only include a section if there is relevant content for it. Never leave a section empty or write "N/A" — simply omit it.

📋 SUMMARY
A 2–4 sentence overview of the entire voice note.

🎯 KEY DETAILS
Bullet points covering the core facts, context, decisions, or information shared.

👤 ROLES & RESPONSIBILITIES
If any person or team is assigned a task or responsibility, list them clearly.

⏰ TASKS & DEADLINES
List every action item or task mentioned.

📌 IMPORTANT NOTES
Warnings, blockers, caveats, assumptions, dependencies, or context.

📝 FULL TRANSCRIPT
A clean, punctuated, readable word-for-word transcript.

Rules:
- Do not invent information.
- If something is unclear, use [unclear].
- Preserve names, figures, dates, and places exactly.
- Use professional English.
""".strip()

# ─────────────────────────────────────────────────────────────
# MIME TYPES
# ─────────────────────────────────────────────────────────────

MIME_MAP = {
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def split_message(text: str, limit: int = 4000):
    """
    Split long Telegram messages safely.
    """

    chunks = []

    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)

        if split_at == -1:
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:]

    chunks.append(text)

    return chunks

# ─────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎙️ Kolai — Voice Intelligence Bot\n\n"
        "Send me:\n"
        "• Voice notes\n"
        "• Audio files\n"
        "• Video notes\n\n"
        "I'll return:\n"
        "• Summary\n"
        "• Key Details\n"
        "• Roles & Responsibilities\n"
        "• Tasks & Deadlines\n"
        "• Full Transcript\n\n"
        "Powered by Gemini 2.5 Flash."
    )

# ─────────────────────────────────────────────────────────────
# Voice Processing
# ─────────────────────────────────────────────────────────────

async def process_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):

    msg = update.message

    if msg.voice:
        file_obj = msg.voice
        file_ext = ".opus"

    elif msg.audio:
        file_obj = msg.audio
        file_ext = Path(
            msg.audio.file_name or "audio.mp3"
        ).suffix.lower()

    elif msg.video_note:
        file_obj = msg.video_note
        file_ext = ".mp4"

    else:
        return

    mime_type = MIME_MAP.get(file_ext, "audio/ogg")

    status_message = await msg.reply_text(
        "🎧 Analysing your voice note..."
    )

    temp_path = None

    try:

        tg_file = await context.bot.get_file(file_obj.file_id)

        with tempfile.NamedTemporaryFile(
            suffix=file_ext,
            delete=False
        ) as temp_file:
            temp_path = temp_file.name

        await tg_file.download_to_drive(temp_path)

        file_size = os.path.getsize(temp_path)

        log.info(
            f"Downloaded {file_ext} file ({file_size:,} bytes)"
        )

        with open(temp_path, "rb") as f:
            audio_bytes = f.read()

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part(text=SYSTEM_PROMPT),
                types.Part(
                    inline_data=types.Blob(
                        mime_type=mime_type,
                        data=audio_bytes,
                    )
                ),
                types.Part(
                    text="Process this voice note according to your instructions."
                ),
            ],
        )

        result = (response.text or "").strip()

        if not result:
            await status_message.edit_text(
                "⚠️ No speech detected or audio was too unclear."
            )
            return

        await status_message.delete()

        chunks = split_message(result)

        if len(chunks) == 1:
            await msg.reply_text(chunks[0])

        else:
            total = len(chunks)

            for index, chunk in enumerate(chunks, start=1):

                await msg.reply_text(
                    f"Part {index}/{total}\n\n{chunk}"
                )

        log.info("Voice note processed successfully.")

    except Exception as e:

        log.exception("Voice processing failed")

        error_message = str(e)

        try:
            await status_message.edit_text(
                f"❌ Error:\n{error_message}"
            )
        except Exception:
            await msg.reply_text(
                f"❌ Error:\n{error_message}"
            )

    finally:

        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

# ─────────────────────────────────────────────────────────────
# Unsupported Messages
# ─────────────────────────────────────────────────────────────

async def unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send a voice note, audio file, or video note and I'll analyse it."
    )

# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("help", start)
    )

    app.add_handler(
        MessageHandler(filters.VOICE, process_voice)
    )

    app.add_handler(
        MessageHandler(filters.AUDIO, process_voice)
    )

    app.add_handler(
        MessageHandler(filters.VIDEO_NOTE, process_voice)
    )

    app.add_handler(
        MessageHandler(filters.ALL, unsupported)
    )

    log.info("Kolai is live and waiting for voice notes...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()