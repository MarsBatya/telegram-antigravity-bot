import html
import os
from pathlib import Path

import psutil
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.core import config
from app.core.storage import SessionStorage
from app.runner import agent_runner
from app.ui.keyboards import get_main_reply_keyboard
from app.utils.bot_utils import (
    reply_safe,
    send_long_message,
)
from app.utils.helpers import (
    make_progress_bar,
    mask_proxy_url,
)

router = Router(name="commands")


@router.message(Command(commands=["start", "help"]))
@router.message(F.text == "❓ Help")
async def send_welcome(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    chat_id = message.chat.id
    user_ws = session_storage.get_workspace(chat_id)
    cur_model = session_storage.get_setting(
        chat_id,
        "model",
        config.DEFAULT_MODEL,
    )
    cur_effort = session_storage.get_setting(
        chat_id,
        "effort",
        config.DEFAULT_EFFORT,
    )
    cur_mode = session_storage.get_setting(
        chat_id,
        "mode",
        config.DEFAULT_MODE,
    )

    help_text = (
        "🧠 <b>Antigravity AI Agent Bot (v3.0 AGY Feature Parity & Sleek UX)</b>\n\n"
        "Type <code>/</code> in the message input to view the "
        "**Complete Command Dropdown Menu**:\n\n"
        "<b>Core Engine Commands:</b>\n"
        "🤖 <code>/model</code> - Switch Model (Gemini / Claude / GPT-OSS)\n"
        "🎯 <code>/effort</code> - Switch Effort (Low / Medium / High)\n"
        "⚙️ <code>/mode</code> - Switch Mode (Accept Edits / Plan Mode)\n"
        "▶️ <code>/resume [instruction]</code> - Choose or resume AI session\n"
        "🔄 <code>/new</code> - Reset & start fresh AI session from scratch\n"
        "🛑 <code>/stop</code> or <code>/cancel</code> - Stop active AI execution\n"
        "🌳 <code>/tree</code> - Interactive File Explorer & VPS Browser\n"
        "📂 <code>/workspace [path]</code> - AI Synced Target Workspace\n"
        "📊 <code>/usage</code> - Live Models & Quota + Token Usage\n"
        "💻 <code>/status</code> - Check RAM, Disk, CPU & AI status\n"
        "📜 <code>/logs</code> - View activity logs & bot service logs\n"
        "💥 <code>/smash &lt;description&gt;</code> - Smash bug mode until done\n"
        "🎯 <code>/goal &lt;description&gt;</code> - Execute specific task / goal\n"
        "📋 <code>/plan &lt;description&gt;</code> - Plan mode (Plan Mode)\n\n"
        f"⚙️ <b>Chat Configuration Dashboard:</b>\n"
        f"• 🤖 Model: <code>{cur_model}</code>\n"
        f"• 🎯 Effort: <code>{cur_effort}</code>\n"
        f"• ⚙️ Mode: <code>{cur_mode}</code>\n"
        f"📍 <b>Workspace:</b> <code>{html.escape(user_ws)}</code>\n\n"
        "💡 <i>Type a message, send an error screenshot, or voice note. "
        "AI will execute instructions automatically!</i>"
    )
    await reply_safe(bot, message, help_text, reply_markup=get_main_reply_keyboard())


@router.message(Command(commands=["logs"]))
async def show_bot_logs(message: Message, bot: Bot) -> None:
    logs = agent_runner.fetch_bot_logs(lines_count=25)
    clean_logs = html.escape(logs)
    await send_long_message(
        bot,
        message.chat.id,
        f"📜 <b>Recent Bot Service Activity Logs:</b>\n"
        f"<pre><code>{clean_logs}</code></pre>",
    )


@router.message(Command(commands=["stop", "cancel"]))
async def handle_cancel_command(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    if session_storage.cancel_chat_process(message.chat.id):
        await reply_safe(
            bot,
            message,
            "🛑 <b>Antigravity AI Execution Successfully Cancelled!</b>",
        )
    else:
        await reply_safe(
            bot,
            message,
            "ℹ️ No AI execution process is currently running.",
        )


@router.message(Command(commands=["status"]))
async def send_status(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    chat_id = message.chat.id
    try:
        cpu_pct = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        user_ws = session_storage.get_workspace(chat_id)
        target_disk = (
            user_ws
            if (user_ws and os.path.exists(user_ws))
            else (str(Path.cwd().anchor) if Path.cwd().anchor else "/")
        )
        disk = psutil.disk_usage(target_disk)
        usage = session_storage.get_token_usage(chat_id)
        cur_model = session_storage.get_setting(
            chat_id,
            "model",
            config.DEFAULT_MODEL,
        )
        cur_effort = session_storage.get_setting(
            chat_id,
            "effort",
            config.DEFAULT_EFFORT,
        )

        cpu_bar = make_progress_bar(cpu_pct)
        ram_bar = make_progress_bar(ram.percent)
        disk_bar = make_progress_bar(disk.percent)

        ram_used_str = f"{ram.used // (1024**2)} MB"
        ram_total_str = f"{ram.total // (1024**2)} MB"
        disk_used_str = f"{disk.used // (1024**3)} GB"
        disk_total_str = f"{disk.total // (1024**3)} GB"

        session = getattr(bot, "session", None)
        session_proxy = getattr(session, "proxy", None) if session is not None else None
        if not session_proxy and config.HTTP_PROXY:
            session_proxy = config.HTTP_PROXY

        masked_proxy = mask_proxy_url(str(session_proxy)) if session_proxy else ""
        proxy_line = (
            f"\n🌐 <b>Telegram Proxy:</b> <code>{html.escape(masked_proxy)}</code>"
            if session_proxy
            else ""
        )

        status_text = (
            "📊 <b>Server & AI Engine Status</b>\n\n"
            f"💻 <b>CPU Usage:</b>\n<code>{cpu_bar}</code>\n\n"
            f"🧠 <b>RAM Usage:</b>\n<code>{ram_bar}</code> "
            f"({ram_used_str} / {ram_total_str})\n\n"
            f"💾 <b>Disk Usage:</b>\n<code>{disk_bar}</code> "
            f"({disk_used_str} / {disk_total_str})\n\n"
            f"🤖 <b>Active Model:</b> <code>{cur_model}</code>\n"
            f"🎯 <b>Effort Level:</b> <code>{cur_effort}</code>\n"
            f"📈 <b>Session Context:</b> {usage['session_tokens']:,} Tokens\n"
            f"📊 <b>Total Tokens:</b> {usage['total_tokens']:,} Tokens\n"
            f"🚀 <b>AGY Executable:</b> <code>{config.AGY_PATH}</code>\n"
            f"📂 <b>Workspace Active:</b> <code>{html.escape(user_ws)}</code>"
            f"{proxy_line}"
        )
        await reply_safe(bot, message, status_text)
    except Exception as e:
        await reply_safe(bot, message, f"❌ Error status: {html.escape(str(e))}")


@router.message(Command(commands=["usage"]))
@router.message(F.text == "📊 Status & Usage")
async def send_usage(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    chat_id = message.chat.id
    live_quota_card = agent_runner.fetch_live_user_quota_summary()

    usage = session_storage.get_token_usage(chat_id)
    sess_tok = usage["session_tokens"]
    tot_tok = usage["total_tokens"]

    max_context = 1_000_000
    remaining_ctx = max(0, max_context - sess_tok)
    pct_used = min(100.0, (sess_tok / max_context) * 100)
    bar_ctx = make_progress_bar(pct_used)

    usage_text = (
        f"{live_quota_card}\n\n"
        f"───────────────────────────────\n"
        f"📈 <b>Active Conversation Session Capacity:</b>\n"
        f"<code>{bar_ctx}</code>\n"
        f"• Used Context: <b>{sess_tok:,}</b> / {max_context:,} "
        f"Tokens ({pct_used:.2f}%)\n"
        f"• Remaining Context: <b>{remaining_ctx:,}</b> Tokens\n"
        f"• Total Accumulated: <b>{tot_tok:,}</b> Tokens\n\n"
        "💡 <i>Type <code>/new</code> to start a new session and "
        "reset context capacity to 100%.</i>"
    )
    await reply_safe(bot, message, usage_text)
