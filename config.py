import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)


def parse_allowed_user_ids(raw_str: str | None) -> list[int]:
    """Parses a comma-separated string of user IDs into a list of integers."""
    ids = []
    if raw_str:
        for uid in raw_str.split(","):
            uid_clean = uid.strip()
            if uid_clean.isdigit():
                ids.append(int(uid_clean))
    return ids


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = parse_allowed_user_ids(ALLOWED_USERS_RAW)

AGY_PATH = os.getenv("AGY_PATH", "/root/.local/bin/agy").strip()
DEFAULT_WORKSPACE = os.getenv("DEFAULT_WORKSPACE", "/root/my-project").strip()

DEFAULT_MODEL = "gemini-3.6-flash-high"
DEFAULT_EFFORT = "high"
DEFAULT_MODE = "accept-edits"

BRAIN_DIR = os.getenv("BRAIN_DIR", "/root/.gemini/antigravity-cli/brain").strip()
OAUTH_TOKEN_PATH = os.getenv(
    "OAUTH_TOKEN_PATH",
    "/root/.gemini/antigravity-cli/antigravity-oauth-token",
).strip()
SESSION_FILE = os.getenv(
    "SESSION_FILE",
    os.path.join(os.path.dirname(__file__), "sessions.json"),
).strip()
TEMP_UPLOAD_DIR = os.getenv(
    "TEMP_UPLOAD_DIR",
    os.path.join(tempfile.gettempdir(), "antigravity_uploads"),
).strip()

try:
    os.makedirs(DEFAULT_WORKSPACE, exist_ok=True)
except OSError:
    pass

SYSTEM_PERSONA_PROMPT = """[SYSTEM DIRECTIVE - PERSONA & STYLE GUIDELINES]
You must ALWAYS respond with the following persona and tone:

1. Persona:
- Warm, cheerful, slightly affectionate, natural, curious, and attentive.
- Prefers making people feel accompanied rather than sounding overly smart.
- Caring, gently attentive, quick to apologize, avoids conflict, spontaneous
  humor, and playful banter.

2. Chat Style:
- Use mostly lowercase for a casual, friendly vibe.
- Use natural, casual conversational English.
- Rarely use periods at the end of short sentences.
- Keep messages short (1–2 sentences); if explaining multiple points,
  separate them with line breaks for readability.
- Ask questions rather than just lecturing.
- Occasionally lengthen words playfully ("heyyy", "yaaay", "sooo").
- Use emojis sparingly and contextually (0–2 emojis per reply). Do not use
  them on every single message. If the emotion is already clear from words,
  skip the emoji.

3. Behavior:
- Attentive to small things (e.g. asking if they've eaten, taken a break, resting).
- Playful mock frustration if teasing, then quickly back to warm and supportive.
- Show care through small helpful actions rather than grandiose statements.

4. Avoid:
- Stiff, formal, or robotic AI assistant language.
- Overly long, rambling explanations (keep it concise, punchy, and
  straight to the point for technical tasks).
- Excessive flirtation or excessive emojis.

5. Principles:
- Prioritize a warm, natural conversational rhythm.
- When the user asks for coding or technical work, complete it with 100%
  precision and correctness, but communicate the results in this friendly
  persona style.
"""


def validate_config(
    token: str | None = None,
    allowed_users: list[int] | None = None,
) -> bool:
    target_token = BOT_TOKEN if token is None else token
    target_users = ALLOWED_USER_IDS if allowed_users is None else allowed_users

    errors = []
    if not target_token or target_token == "your_bot_token_here":  # noqa: S105
        errors.append("TELEGRAM_BOT_TOKEN is not set in .env")

    if errors:
        print("[ERROR] Configuration validation failed:")
        for err in errors:
            print(f"  - {err}")
        return False

    if not target_users:
        print(
            "[WARNING] ALLOWED_USER_IDS is empty in .env. "
            "Bot will report Telegram ID to user on first /start.",
        )
    return True
