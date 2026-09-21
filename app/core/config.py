import os
import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
env_path = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=env_path)


def parse_allowed_user_ids(raw_str: str | None) -> list[int]:
    """Parses a comma-separated string of user IDs into a list of integers."""
    if not raw_str:
        return []
    return [int(u.strip()) for u in raw_str.split(",") if u.strip().isdigit()]


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = parse_allowed_user_ids(ALLOWED_USERS_RAW)


def normalize_proxy_url(proxy_url: str | None) -> str | None:
    """Normalizes a proxy URL, ensuring it has a scheme prefix."""
    if not proxy_url:
        return None
    cleaned = proxy_url.strip()
    if not cleaned:
        return None
    if not cleaned.startswith(("http://", "https://", "socks5://", "socks4://")):
        cleaned = f"http://{cleaned}"
    return cleaned


def get_http_proxy() -> str | None:
    """Reads HTTP proxy settings from environment variables."""
    raw = (
        os.getenv("HTTP_PROXY")
        or os.getenv("http_proxy")
        or os.getenv("HTTPS_PROXY")
        or os.getenv("https_proxy")
    )
    return normalize_proxy_url(raw)


HTTP_PROXY = get_http_proxy()


def _get_default_agy_path() -> str:
    env_val = os.getenv("AGY_PATH")
    if env_val and env_val.strip():
        return env_val.strip()
    which = shutil.which("agy")
    if which:
        return which

    if sys.platform == "win32":
        candidates = [
            str(Path.home() / "AppData" / "Roaming" / "npm" / "agy.cmd"),
            str(Path.home() / "AppData" / "Roaming" / "npm" / "agy.exe"),
            str(Path.home() / "AppData" / "Local" / "Programs" / "agy" / "agy.exe"),
            str(Path.home() / ".local" / "bin" / "agy.exe"),
            str(Path.home() / ".local" / "bin" / "agy.cmd"),
            str(Path.home() / ".local" / "bin" / "agy"),
        ]
        for cand in candidates:
            if os.path.exists(cand):
                return cand
        return "agy.cmd"

    user_bin = str(Path.home() / ".local" / "bin" / "agy")
    return user_bin if os.path.exists(user_bin) else "/root/.local/bin/agy"


AGY_PATH = _get_default_agy_path()
DEFAULT_WORKSPACE = os.getenv(
    "DEFAULT_WORKSPACE",
    str(Path.home() / "my-project"),
).strip()

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-3.8-flash-high").strip()
DEFAULT_EFFORT = "high"
DEFAULT_MODE = "accept-edits"

BRAIN_DIR = os.getenv(
    "BRAIN_DIR",
    str(Path.home() / ".gemini" / "antigravity-cli" / "brain"),
).strip()
OAUTH_TOKEN_PATH = os.getenv(
    "OAUTH_TOKEN_PATH",
    str(Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"),
).strip()
CLOUDCODE_BASE_URL = (
    os.getenv(
        "CLOUDCODE_BASE_URL",
        "https://daily-cloudcode-pa.googleapis.com",
    )
    .strip()
    .rstrip("/")
)
SESSION_FILE = os.getenv(
    "SESSION_FILE",
    str(PROJECT_ROOT / "sessions.json"),
).strip()
TEMP_UPLOAD_DIR = os.getenv(
    "TEMP_UPLOAD_DIR",
    str(Path(tempfile.gettempdir()) / "antigravity_uploads"),
).strip()

try:
    Path(DEFAULT_WORKSPACE).mkdir(parents=True, exist_ok=True)
except OSError:
    pass

SYSTEM_PERSONA_PROMPT = """[SYSTEM DIRECTIVE - STYLE GUIDELINES]

1. Chat Style:
- Keep messages short (1–2 sentences); if explaining multiple points,
  separate them with line breaks for readability.
- Use emojis sparingly and contextually (0–2 emojis per reply). Do not use
  them on every single message. If the emotion is already clear from words,
  skip the emoji.

2. Avoid:
- Overly long, rambling explanations (keep it concise, punchy, and
  straight to the point for technical tasks).
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
