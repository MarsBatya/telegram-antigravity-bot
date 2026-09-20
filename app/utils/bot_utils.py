import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from aiogram import Bot
from aiogram.types import BotCommand, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from app.core import config
from app.ui.keyboards import get_main_reply_keyboard


class PathMapper:
    """Maps long absolute paths to short tokens to keep callback_data
    well under Telegram's 64-byte limit.
    """

    def __init__(self) -> None:
        self._to_token: dict[str, str] = {}
        self._to_path: dict[str, str] = {}
        self._counter: int = 0

    def encode(self, path: str) -> str:
        norm = os.path.abspath(path)
        if norm in self._to_token:
            return self._to_token[norm]
        self._counter += 1
        token = f"p{self._counter}"
        self._to_token[norm] = token
        self._to_path[token] = norm
        return token

    def decode(self, token: str) -> str | None:
        return self._to_path.get(token)


path_mapper = PathMapper()


def mask_proxy_url(url: str | None) -> str:
    """Masks sensitive password/credentials in proxy URLs for safe logging/display."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        if parts.password:
            user = parts.username or ""
            host = parts.hostname or ""
            port_str = f":{parts.port}" if parts.port else ""
            masked_netloc = f"{user}:***@{host}{port_str}"
            return urlunsplit(
                (parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment),
            )
    except Exception:  # noqa: S110
        pass
    return url


def make_progress_bar(percent: float, length: int = 10) -> str:
    filled = int(round(length * percent / 100))
    filled = max(0, min(length, filled))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent:.1f}%"


def format_file_size(size_bytes: int | float) -> str:
    """Formats bytes into human-readable size string (B, KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{int(size_bytes)} B"
    if size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024, 1)} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{round(size_bytes / (1024 * 1024), 1)} MB"
    return f"{round(size_bytes / (1024 * 1024 * 1024), 1)} GB"


def is_authorized(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return False
    return user_id in config.ALLOWED_USER_IDS


async def register_telegram_commands(target_bot: Bot) -> bool:
    """Registers ALL 18 slash commands into Telegram UI dropdown autocomplete menu"""
    commands = [
        BotCommand(command="start", description="🚀 Show main menu & bot guide"),
        BotCommand(
            command="model",
            description="🤖 Switch Model (Gemini/Claude/GPT-OSS)",
        ),
        BotCommand(
            command="effort",
            description="🎯 Set Reasoning Effort (Low/Medium/High)",
        ),
        BotCommand(
            command="mode",
            description="⚙️ Switch Mode (Accept Edits / Plan Mode)",
        ),
        BotCommand(
            command="resume",
            description="▶️ Select & resume AI conversation session",
        ),
        BotCommand(command="new", description="🔄 Reset & start new AI session"),
        BotCommand(command="stop", description="🛑 Stop/cancel active AI execution"),
        BotCommand(
            command="tree",
            description="🌳 File & Folder Explorer (VPS navigation)",
        ),
        BotCommand(
            command="workspace",
            description="📂 Change server working directory (synced to AI)",
        ),
        BotCommand(
            command="usage",
            description="📊 Live Models & Quota + Token Usage",
        ),
        BotCommand(
            command="status",
            description="💻 Check CPU, RAM, Disk VPS & AI status",
        ),
        BotCommand(
            command="rename",
            description="✏️ Rename active conversation session",
        ),
        BotCommand(
            command="delete",
            description="🗑️ Delete conversation session from history",
        ),
        BotCommand(
            command="smash",
            description="💥 Smash bug mode & force fix until complete",
        ),
        BotCommand(
            command="goal",
            description="🎯 Execute specific task / goal until complete",
        ),
        BotCommand(command="plan", description="📋 Planning mode (Plan Mode)"),
        BotCommand(
            command="logs",
            description="📜 View activity logs & bot systemd logs",
        ),
        BotCommand(command="help", description="❓ Full command list & help"),
    ]
    try:
        await target_bot.set_my_commands(commands)
        print("✅ ALL 18 Telegram Slash Commands registered successfully!")
        return True
    except Exception as e:
        print(f"[WARNING] Failed to register slash commands with Telegram: {e}")
        return False


async def reply_safe(
    bot: Bot,
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None,
    **kwargs: Any,
) -> Message | None:
    """Safely reply to a message, falling back to send_message
    if original message cannot be replied to.
    """
    if reply_markup is None:
        reply_markup = get_main_reply_keyboard()
    try:
        return await message.reply(text, reply_markup=reply_markup, **kwargs)
    except Exception:
        try:
            return await bot.send_message(
                message.chat.id,
                text,
                reply_markup=reply_markup,
                **kwargs,
            )
        except Exception as e:
            print(f"[ERROR] Failed to send message: {e}")
            return None


_HTML_TAG_RE = re.compile(r"<\/?([a-zA-Z0-9-]+)(?:\s+[^>]*?)?\/?>")


def _chunk_text_safely(text: str, max_length: int = 3800) -> list[str]:
    """Splits text into chunks strictly under max_length, breaking oversized lines."""
    raw_lines = text.split("\n")
    lines: list[str] = []
    for line in raw_lines:
        if len(line) <= max_length:
            lines.append(line)
        else:
            for i in range(0, len(line), max_length):
                lines.append(line[i : i + max_length])

    chunks: list[str] = []
    curr_chunk: list[str] = []
    curr_len = 0

    for line in lines:
        added_len = len(line) + (1 if curr_chunk else 0)
        if curr_len + added_len > max_length:
            if curr_chunk:
                chunks.append("\n".join(curr_chunk))
            curr_chunk = [line]
            curr_len = len(line)
        else:
            curr_chunk.append(line)
            curr_len += added_len

    if curr_chunk:
        chunks.append("\n".join(curr_chunk))
    return chunks


def balance_html_chunks(chunks: list[str]) -> list[str]:
    """Ensures each chunk has balanced HTML tags so Telegram parsing never crashes."""
    balanced_chunks: list[str] = []
    open_stack: list[tuple[str, str]] = []

    for chunk in chunks:
        # Re-open any tags carried over from the previous chunk
        prefix = "".join(full_tag for _, full_tag in open_stack)
        current_content = prefix + chunk

        current_stack: list[tuple[str, str]] = []
        for match in _HTML_TAG_RE.finditer(current_content):
            raw_tag = match.group(0)
            tag_name = match.group(1).lower()
            if raw_tag.endswith("/>"):
                continue
            if raw_tag.startswith("</"):
                for i in range(len(current_stack) - 1, -1, -1):
                    if current_stack[i][0] == tag_name:
                        current_stack.pop(i)
                        break
            else:
                current_stack.append((tag_name, raw_tag))

        closing = "".join(f"</{tag}>" for tag, _ in reversed(current_stack))
        balanced_chunks.append(current_content + closing)
        open_stack = current_stack

    return balanced_chunks


async def send_long_message(  # noqa: C901
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None,
) -> Message | None:
    """Sends message cleanly in one bubble if <= 3800 chars,
    or splits safely by lines and balances HTML tags if larger.
    """
    if not text or not text.strip():
        return None

    max_length = 3800
    if len(text) <= max_length:
        try:
            return await bot.send_message(
                chat_id,
                text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except Exception as e:
            print(f"[WARNING] HTML send failed: {e}, falling back to plain text")
            clean_text = re.sub(r"<[^>]+>", "", text)
            try:
                return await bot.send_message(
                    chat_id,
                    clean_text,
                    parse_mode=None,
                    reply_markup=reply_markup,
                )
            except Exception:
                return None

    raw_chunks = _chunk_text_safely(text, max_length=max_length)
    chunks = balance_html_chunks(raw_chunks)

    last_msg: Message | None = None
    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        m_markup = reply_markup if i == len(chunks) - 1 else None
        try:
            last_msg = await bot.send_message(
                chat_id,
                chunk,
                parse_mode="HTML",
                reply_markup=m_markup,
            )
        except Exception:
            clean_chunk = re.sub(r"<[^>]+>", "", chunk)
            try:
                last_msg = await bot.send_message(
                    chat_id,
                    clean_chunk,
                    parse_mode=None,
                    reply_markup=m_markup,
                )
            except Exception as e:
                print(f"[ERROR] Failed to send chunk: {e}")
    return last_msg
