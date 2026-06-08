import os
import tempfile
import logging
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

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
You are Kolai — a voice note intelligence assistant for team coordination, lectures, and general recordings.

STEP 1 — DETECT CONTEXT
First, silently identify what kind of recording this is:
- TEAM BRIEFING: a leader assigning tasks, roles, and deadlines to named people
- LECTURE / LESSON: educational content being taught or explained
- GENERAL / RANDOM: casual conversation, personal note, or mixed content

Then apply the matching output format below.

════════════════════════════════════════
IF TEAM BRIEFING — use this format:
════════════════════════════════════════

📋 OVERVIEW
2–3 sentences. What project or topic is this about, who is speaking, and what is the purpose of this voice note.

👥 TEAM & ROLES
List every person mentioned by name. Use their real name, not nicknames — if a nickname is used, write: Real Name (nickname).
Format:
- [Full Name] — [Their role or area of responsibility in one sentence]

⚙️ TASK ASSIGNMENTS
Group tasks by person. For each person write:

[FULL NAME]
  → [Task 1]
  → [Task 2]
  Deadline: [exact date/time stated, or "Not stated"]

📌 CRITICAL NOTES
Warnings, things NOT to do, conditions, blockers, or context the team must know.

🔑 PROJECT DETAILS
Key facts about the project itself — name, brand, target audience, tech stack, goals, constraints.

════════════════════════════════════════
IF LECTURE / LESSON — use this format:
════════════════════════════════════════

📚 SUBJECT
Topic and course or context if mentioned.

🧠 KEY CONCEPTS
Bullet each major concept taught. One concept per bullet. Be specific — include definitions, formulas, names, dates exactly as stated.

📝 DETAILED NOTES
Write clean structured notes as if a top student took them. Use sub-bullets for depth. Preserve all technical detail.

❓ QUESTIONS RAISED
Any questions the lecturer posed that students should think about or answer.

⚡ SUMMARY
3–5 sentence summary of the entire lecture a student could use to revise.

════════════════════════════════════════
IF GENERAL / RANDOM — use this format:
════════════════════════════════════════

📋 SUMMARY
What was said and who said it (if known).

🎯 KEY POINTS
Bullet the main ideas, facts, or decisions.

⏰ ACTION ITEMS
Anything that needs to be done, by whom, by when.

📝 FULL TRANSCRIPT
Clean, punctuated, readable transcript. Remove filler words (um, uh, like). Preserve meaning exactly.

════════════════════════════════════════
RULES FOR ALL FORMATS:
════════════════════════════════════════
- NEVER use timestamps in the transcript or anywhere.
- NEVER leave a section empty — omit it entirely if not relevant.
- Nicknames: always resolve to real name. Write Abdulramn (Virus), not just Virus.
- Unclear words: write [unclear] — never guess.
- Dates and times in full: "Wednesday, June 11 at 12:00 AM" not "Wednesday 12 AM".
- Numbers, names, figures: preserve exactly as spoken.
- Write in clear professional English regardless of how casual the speaker was.
- The output must be readable by someone who was NOT on the call and knows nothing about the project.
- Real Team Names Mapping:
  * "Virus" / "Abdurahman" -> Abdulramn (Virus)
  * "Fiddoze" -> Firdaus (Fiddoze)
  * "Abduraki" / "Abdurakib" -> Abdularqueeb
  * "Nesa" -> Nyesa
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

        if split_at <= 0:
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
        ).suffix.lower() or ".mp3"

    elif msg.video_note:
        file_obj = msg.video_note
        file_ext = ".mp4"

    else:
        return

    # Telegram Bot API limit is 20MB for downloading files
    file_size_limit = 20 * 1024 * 1024
    file_size = getattr(file_obj, "file_size", None)
    if file_size and file_size > file_size_limit:
        await msg.reply_text(
            "⚠️ This file is too large. Telegram bots can only download files up to 20MB."
        )
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
        status_message = None

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

        if status_message:
            try:
                await status_message.edit_text(
                    f"❌ Error:\n{error_message}"
                )
                return
            except Exception:
                pass

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
# Error Handling & Healthcheck
# ─────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error inflicted by an Update."""
    log.error("Exception while handling an update:", exc_info=context.error)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        # Suppress logging to keep stdout clean
        pass

def start_health_check_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    log.info(f"Starting health check server on port {port}...")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    # Register global error handler
    app.add_error_handler(error_handler)

    # Start background healthcheck HTTP server
    start_health_check_server()

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