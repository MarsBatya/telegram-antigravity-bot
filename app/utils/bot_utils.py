import re
from typing import Any

from aiogram import Bot
from aiogram.types import BotCommand, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from app.ui.keyboards import get_main_reply_keyboard
from app.utils.helpers import _chunk_text_safely, balance_html_chunks


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
