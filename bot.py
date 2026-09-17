import functools
import html
import os
import re
import sys
import threading
import time
import traceback

import psutil
import telebot
from telebot import types

import agent_runner
import config
import formatter
import stream_runner

_bot_token = config.BOT_TOKEN if (config.BOT_TOKEN and ":" in config.BOT_TOKEN) else "123456:TEST_DUMMY_TOKEN"
bot = telebot.TeleBot(_bot_token, parse_mode="HTML")


class PathMapper:
    """Maps long absolute paths to short tokens to keep callback_data well under Telegram's 64-byte limit"""

    def __init__(self):
        self._to_token = {}
        self._to_path = {}
        self._counter = 0

    def encode(self, path: str) -> str:
        norm = os.path.abspath(path)
        if norm in self._to_token:
            return self._to_token[norm]
        self._counter += 1
        token = f"p{self._counter}"
        self._to_token[norm] = token
        self._to_path[token] = norm
        return token

    def decode(self, token: str) -> str:
        return self._to_path.get(token)


path_mapper = PathMapper()


def register_telegram_commands(target_bot=None):
    """Registers ALL 18 slash commands into Telegram UI dropdown autocomplete menu"""
    active_bot = target_bot or bot
    commands = [
        types.BotCommand("start", "🚀 Show main menu & bot guide"),
        types.BotCommand("model", "🤖 Switch Model (Gemini/Claude/GPT-OSS)"),
        types.BotCommand("effort", "🎯 Set Reasoning Effort (Low/Medium/High)"),
        types.BotCommand("mode", "⚙️ Switch Mode (Accept Edits / Plan Mode)"),
        types.BotCommand("resume", "▶️ Select & resume AI conversation session"),
        types.BotCommand("new", "🔄 Reset & start new AI session"),
        types.BotCommand("stop", "🛑 Stop/cancel active AI execution"),
        types.BotCommand("tree", "🌳 File & Folder Explorer (VPS navigation)"),
        types.BotCommand("workspace", "📂 Change server working directory (synced to AI)"),
        types.BotCommand("usage", "📊 Live Models & Quota + Token Usage"),
        types.BotCommand("status", "💻 Check CPU, RAM, Disk VPS & AI status"),
        types.BotCommand("rename", "✏️ Rename active conversation session"),
        types.BotCommand("delete", "🗑️ Delete conversation session from history"),
        types.BotCommand("smash", "💥 Smash bug mode & force fix until complete"),
        types.BotCommand("goal", "🎯 Execute specific task / goal until complete"),
        types.BotCommand("plan", "📋 Planning mode (Plan Mode)"),
        types.BotCommand("logs", "📜 View activity logs & bot systemd logs"),
        types.BotCommand("help", "❓ Full command list & help"),
    ]
    try:
        active_bot.set_my_commands(commands)
        print("✅ ALL 18 Telegram Slash Commands registered successfully into dropdown menu!")
        return True
    except Exception as e:
        print(f"[WARNING] Failed to register slash commands with Telegram: {e}")
        return False


def make_progress_bar(percent: float, length: int = 10) -> str:
    filled = int(round(length * percent / 100))
    filled = max(0, min(length, filled))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent:.1f}%"


def get_main_reply_keyboard():
    """Compact 2x3 Grid Dashboard Keyboard for clean mobile screen layout"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🤖 Model & Effort"),
        types.KeyboardButton("💬 Active Session"),
        types.KeyboardButton("▶️ Resume / Session"),
        types.KeyboardButton("🔄 New Session"),
        types.KeyboardButton("📂 Workspace & Tree"),
        types.KeyboardButton("📊 Status & Usage"),
    )
    return markup


def reply_safe(message, text, **kwargs):
    """Safely reply to a message, falling back to send_message if original message was deleted"""
    if "reply_markup" not in kwargs:
        kwargs["reply_markup"] = get_main_reply_keyboard()
    try:
        return bot.reply_to(message, text, **kwargs)
    except Exception:
        try:
            return bot.send_message(message.chat.id, text, **kwargs)
        except Exception as e:
            print(f"[ERROR] Failed to send message: {e}")
            return None


def is_authorized(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return False
    return user_id in config.ALLOWED_USER_IDS


def check_auth(func):
    """Decorator to enforce security for message handlers"""

    @functools.wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        user_name = message.from_user.username or message.from_user.first_name or "User"
        print(f"[RECV MSG] From User ID: {user_id} (@{user_name}) - Text: {message.text or '<media>'}")

        if not config.ALLOWED_USER_IDS:
            reply_safe(
                message,
                f"👋 <b>Welcome to Antigravity AI Bot!</b>\n\n"
                f"Your Telegram ID is: <code>{user_id}</code>\n\n"
                f"⚠️ <b>Bot has not been configured with your ID yet.</b>\n"
                f"Please open the <code>.env</code> file on the server and add:\n"
                f"<code>ALLOWED_USER_IDS={user_id}</code>\n\n"
                f"Then restart the bot.",
            )
            return
        if not is_authorized(user_id):
            reply_safe(
                message,
                f"⛔ <b>Access Denied!</b>\nYour Telegram ID (<code>{user_id}</code>) is not listed in ALLOWED_USER_IDS in <code>.env</code>.",
            )
            print(f"[SECURITY ALERT] Unauthorized access attempt from User ID: {user_id}")
            return
        return func(message, *args, **kwargs)

    return wrapper


def check_auth_callback(func):
    """Decorator to enforce security for callback queries (button clicks)"""

    @functools.wraps(func)
    def wrapper(call, *args, **kwargs):
        user_id = call.from_user.id
        print(f"[RECV CALLBACK] From User ID: {user_id} - Data: {call.data}")
        if not is_authorized(user_id):
            bot.answer_callback_query(call.id, "⛔ Access denied! Your ID is not registered.", show_alert=True)
            return
        return func(call, *args, **kwargs)

    return wrapper


def send_long_message(chat_id, text, reply_markup=None):
    """Sends message cleanly in one bubble if <= 3800 chars, or splits safely by lines if larger"""
    if not text or not text.strip():
        return

    max_length = 3800
    if len(text) <= max_length:
        try:
            return bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as e:
            print(f"[WARNING] HTML send failed: {e}, falling back to plain text")
            clean_text = re.sub(r"<[^>]+>", "", text)
            try:
                return bot.send_message(chat_id, clean_text, parse_mode=None, reply_markup=reply_markup)
            except Exception:
                return None

    lines = text.split("\n")
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        if current_len + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = len(line)
        else:
            current_chunk.append(line)
            current_len += len(line) + 1

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        m_markup = reply_markup if i == len(chunks) - 1 else None
        try:
            bot.send_message(chat_id, chunk, parse_mode="HTML", reply_markup=m_markup)
        except Exception:
            clean_chunk = re.sub(r"<[^>]+>", "", chunk)
            try:
                bot.send_message(chat_id, clean_chunk, parse_mode=None, reply_markup=m_markup)
            except Exception as e:
                print(f"[ERROR] Failed to send chunk: {e}")
        time.sleep(0.3)


def keep_typing_alive(chat_id, stop_event):
    """Sends 'typing' chat action every 4 seconds to maintain Telegram UI status"""
    while not stop_event.is_set():
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        time.sleep(4)


@bot.message_handler(commands=["start", "help"])
@bot.message_handler(func=lambda msg: msg.text == "❓ Help")
@check_auth
def send_welcome(message):
    user_ws = agent_runner.get_chat_workspace(message.chat.id)
    cur_model = agent_runner.get_chat_setting(message.chat.id, "model", config.DEFAULT_MODEL)
    cur_effort = agent_runner.get_chat_setting(message.chat.id, "effort", config.DEFAULT_EFFORT)
    cur_mode = agent_runner.get_chat_setting(message.chat.id, "mode", config.DEFAULT_MODE)

    help_text = (
        "🧠 <b>Antigravity AI Agent Bot (v3.0 Full AGY Feature Parity & Sleek UX)</b>\n\n"
        "Type <code>/</code> in the message input to view the **Complete Command Dropdown Menu**:\n\n"
        "<b>Core Engine Commands:</b>\n"
        "🤖 <code>/model</code> - Switch Model (Gemini / Claude / GPT-OSS)\n"
        "🎯 <code>/effort</code> - Switch Effort (Low / Medium / High)\n"
        "⚙️ <code>/mode</code> - Switch Mode (Accept Edits / Plan Mode)\n"
        "▶️ <code>/resume [instruction]</code> - Select / load AI conversation session history\n"
        "🔄 <code>/new</code> - Reset & start fresh AI session from scratch\n"
        "🛑 <code>/stop</code> or <code>/cancel</code> - Stop active AI execution\n"
        "🌳 <code>/tree</code> - Interactive File Explorer & VPS Browser\n"
        "📂 <code>/workspace [path]</code> - AI Synced Target Workspace\n"
        "📊 <code>/usage</code> - Live Models & Quota + Token Usage\n"
        "💻 <code>/status</code> - Check RAM, Disk, CPU & AI status\n"
        "📜 <code>/logs</code> - View activity logs & bot service logs\n"
        "💥 <code>/smash &lt;description&gt;</code> - Smash bug mode until complete\n"
        "🎯 <code>/goal &lt;description&gt;</code> - Execute specific task / goal\n"
        "📋 <code>/plan &lt;description&gt;</code> - Activate planning mode (Plan Mode)\n\n"
        f"⚙️ <b>Chat Configuration Dashboard:</b>\n"
        f"• 🤖 Model: <code>{cur_model}</code>\n"
        f"• 🎯 Effort: <code>{cur_effort}</code>\n"
        f"• ⚙️ Mode: <code>{cur_mode}</code>\n"
        f"📍 <b>Workspace:</b> <code>{html.escape(user_ws)}</code>\n\n"
        "💡 <i>Type a message, send an error screenshot, or voice note. AI will execute instructions automatically!</i>"
    )
    reply_safe(message, help_text, reply_markup=get_main_reply_keyboard())


@bot.message_handler(func=lambda msg: msg.text in ["🤖 Model & Effort", "/model"])
@bot.message_handler(commands=["model"])
@check_auth
def show_model_picker(message_or_call):
    chat_id = message_or_call.chat.id if hasattr(message_or_call, "chat") else message_or_call.message.chat.id
    cur_model = agent_runner.get_chat_setting(chat_id, "model", config.DEFAULT_MODEL)

    models = agent_runner.fetch_available_models_live()
    if not models:
        models = [
            {"id": "gemini-3.6-flash-high", "displayName": "Gemini 3.6 Flash (High)"},
            {"id": "gemini-3.6-flash-medium", "displayName": "Gemini 3.6 Flash (Medium)"},
            {"id": "gemini-3.1-pro-high", "displayName": "Gemini 3.1 Pro (High)"},
            {"id": "claude-sonnet-4-6", "displayName": "Claude Sonnet 4.6 (Thinking)"},
            {"id": "claude-opus-4-6-thinking", "displayName": "Claude Opus 4.6 (Thinking)"},
            {"id": "gpt-oss-120b-medium", "displayName": "GPT-OSS 120B (Medium)"},
        ]

    markup = types.InlineKeyboardMarkup(row_width=1)
    for m in models:
        m_id = m["id"]
        name = m.get("displayName") or m_id
        is_active = " ✅ (Active)" if m_id == cur_model else ""
        btn_text = f"🤖 {name}{is_active}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"set_model:{m_id}"))

    btn_eff = types.InlineKeyboardButton("🎯 Change Effort Level (/effort)", callback_data="open_effort_menu")
    markup.add(btn_eff)

    text = (
        "🤖 <b>Antigravity AI Model Selector</b>\n\n"
        f"🎯 <b>Current Active Model:</b> <code>{cur_model}</code>\n\n"
        "Select an AI model below to use in the conversation:"
    )

    if hasattr(message_or_call, "data"):
        try:
            bot.edit_message_text(
                text, chat_id, message_or_call.message.message_id, reply_markup=markup, parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        reply_safe(message_or_call, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "open_effort_menu")
@check_auth_callback
def handle_open_effort_menu(call):
    bot.answer_callback_query(call.id)
    show_effort_picker(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_model:"))
@check_auth_callback
def handle_set_model_callback(call):
    chat_id = call.message.chat.id
    m_id = call.data.split(":", 1)[1]
    agent_runner.set_chat_setting(chat_id, "model", m_id)

    bot.answer_callback_query(call.id, f"Model changed to {m_id}")
    bot.edit_message_text(
        f"✅ <b>AI Model Successfully Changed To:</b>\n<code>{m_id}</code>\n\n"
        f"<i>All subsequent AI executions will use this model!</i>",
        chat_id,
        call.message.message_id,
        parse_mode="HTML",
    )


@bot.message_handler(commands=["effort"])
@check_auth
def show_effort_picker(message_or_call):
    chat_id = message_or_call.chat.id if hasattr(message_or_call, "chat") else message_or_call.message.chat.id
    cur_effort = agent_runner.get_chat_setting(chat_id, "effort", config.DEFAULT_EFFORT)

    efforts = [
        ("low", "🟢 Low - Fast Execution"),
        ("medium", "🟡 Medium - Balanced"),
        ("high", "🔴 High - Deep Reasoning & Force Fix"),
    ]

    markup = types.InlineKeyboardMarkup(row_width=1)
    for eff_key, eff_name in efforts:
        is_active = " ✅ (Active)" if eff_key == cur_effort else ""
        btn_text = f"{eff_name}{is_active}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"set_effort:{eff_key}"))

    text = (
        "🎯 <b>Antigravity Reasoning Effort Level</b>\n\n"
        f"📊 <b>Active Effort Level:</b> <code>{cur_effort}</code>\n\n"
        "Select the AI reasoning depth for task execution:"
    )

    if hasattr(message_or_call, "data"):
        try:
            bot.edit_message_text(
                text, chat_id, message_or_call.message.message_id, reply_markup=markup, parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        reply_safe(message_or_call, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_effort:"))
@check_auth_callback
def handle_set_effort_callback(call):
    chat_id = call.message.chat.id
    eff_key = call.data.split(":", 1)[1]
    agent_runner.set_chat_setting(chat_id, "effort", eff_key)

    bot.answer_callback_query(call.id, f"Effort changed to {eff_key}")
    bot.edit_message_text(
        f"✅ <b>Reasoning Effort Successfully Changed To:</b> <code>{eff_key.upper()}</code>",
        chat_id,
        call.message.message_id,
        parse_mode="HTML",
    )


@bot.message_handler(commands=["mode"])
@check_auth
def show_mode_picker(message_or_call):
    chat_id = message_or_call.chat.id if hasattr(message_or_call, "chat") else message_or_call.message.chat.id
    cur_mode = agent_runner.get_chat_setting(chat_id, "mode", config.DEFAULT_MODE)

    modes = [
        ("accept-edits", "🛠️ Accept Edits Mode (Directly Edit Code)"),
        ("plan", "📋 Plan Mode (Step-by-Step Planning)"),
    ]

    markup = types.InlineKeyboardMarkup(row_width=1)
    for mode_key, mode_name in modes:
        is_active = " ✅ (Active)" if mode_key == cur_mode else ""
        btn_text = f"{mode_name}{is_active}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"set_mode:{mode_key}"))

    text = (
        "⚙️ <b>Antigravity Agent Execution Mode</b>\n\n"
        f"📍 <b>Current Active Mode:</b> <code>{cur_mode}</code>\n\n"
        "Select AI execution mode:"
    )

    if hasattr(message_or_call, "data"):
        try:
            bot.edit_message_text(
                text, chat_id, message_or_call.message.message_id, reply_markup=markup, parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        reply_safe(message_or_call, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_mode:"))
@check_auth_callback
def handle_set_mode_callback(call):
    chat_id = call.message.chat.id
    mode_key = call.data.split(":", 1)[1]
    agent_runner.set_chat_setting(chat_id, "mode", mode_key)

    bot.answer_callback_query(call.id, f"Mode changed to {mode_key}")
    bot.edit_message_text(
        f"✅ <b>Agent Mode Successfully Changed To:</b> <code>{mode_key}</code>",
        chat_id,
        call.message.message_id,
        parse_mode="HTML",
    )


@bot.message_handler(func=lambda msg: msg.text in ["📂 Workspace & Tree", "/tree"])
@bot.message_handler(commands=["tree", "ls"])
@check_auth
def show_tree_explorer(message_or_call):
    chat_id = message_or_call.chat.id if hasattr(message_or_call, "chat") else message_or_call.message.chat.id
    current_ws = agent_runner.get_chat_workspace(chat_id)
    render_file_explorer(message_or_call, current_ws)


def render_file_explorer(message_or_call, path_dir):
    chat_id = message_or_call.chat.id if hasattr(message_or_call, "chat") else message_or_call.message.chat.id
    norm_path = os.path.abspath(path_dir)

    if not os.path.exists(norm_path):
        norm_path = "/root/my-project"

    markup = types.InlineKeyboardMarkup(row_width=1)

    parent = os.path.dirname(norm_path)
    if parent and parent != norm_path:
        up_token = path_mapper.encode(parent)
        markup.add(types.InlineKeyboardButton("⬆️ .. (Parent Directory)", callback_data=f"browse_dir:{up_token}"))

    cur_ws = agent_runner.get_chat_workspace(chat_id)
    if os.path.abspath(norm_path) != os.path.abspath(cur_ws):
        set_token = path_mapper.encode(norm_path)
        markup.add(types.InlineKeyboardButton("📍 Set as AI Target Workspace", callback_data=f"set_ws:{set_token}"))

    try:
        entries = sorted(os.listdir(norm_path))
        dirs = []
        files = []

        for e in entries:
            if e.startswith("."):
                continue
            full_e = os.path.join(norm_path, e)
            if os.path.isdir(full_e):
                dirs.append(e)
            else:
                sz_kb = round(os.path.getsize(full_e) / 1024, 1)
                files.append((e, sz_kb))

        for d in dirs[:10]:
            full_d = os.path.join(norm_path, d)
            token = path_mapper.encode(full_d)
            markup.add(types.InlineKeyboardButton(f"📁 {d}/", callback_data=f"browse_dir:{token}"))

        for fname, sz in files[:10]:
            markup.add(types.InlineKeyboardButton(f"📄 {fname} ({sz} KB)", callback_data=f"info_file:{fname[:20]}"))

    except Exception as e:
        print(f"[ERROR] Listing dir {norm_path}: {e}")

    text = (
        f"🌳 <b>Interactive File Explorer (VPS)</b>\n\n"
        f"📂 <b>Current Path:</b>\n<code>{html.escape(norm_path)}</code>\n\n"
        f"Click a folder to browse or set as target workspace:"
    )

    if hasattr(message_or_call, "data"):
        try:
            bot.edit_message_text(
                text, chat_id, message_or_call.message.message_id, reply_markup=markup, parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        reply_safe(message_or_call, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_dir:"))
@check_auth_callback
def handle_browse_dir_callback(call):
    token = call.data.split(":", 1)[1]
    path_dir = path_mapper.decode(token)
    bot.answer_callback_query(call.id)
    render_file_explorer(call, path_dir)


@bot.message_handler(commands=["logs"])
@check_auth
def show_bot_logs(message):
    logs = agent_runner.fetch_bot_logs(lines_count=25)
    clean_logs = html.escape(logs)
    send_long_message(
        message.chat.id, f"📜 <b>Recent Bot Service Activity Logs:</b>\n<pre><code>{clean_logs}</code></pre>"
    )


@bot.message_handler(commands=["stop", "cancel"])
@check_auth
def handle_cancel_command(message):
    if agent_runner.cancel_chat_process(message.chat.id):
        reply_safe(message, "🛑 <b>Antigravity AI Execution Successfully Cancelled!</b>")
    else:
        reply_safe(message, "ℹ️ No AI execution process is currently running.")


@bot.callback_query_handler(func=lambda call: call.data == "cancel_execution")
@check_auth_callback
def handle_cancel_callback(call):
    chat_id = call.message.chat.id
    if agent_runner.cancel_chat_process(chat_id):
        bot.answer_callback_query(call.id, "Process cancelled!")
        try:
            bot.edit_message_text(
                "🛑 <b>Execution Cancelled by User.</b>", chat_id, call.message.message_id, parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        bot.answer_callback_query(call.id, "No running process.", show_alert=True)


@bot.message_handler(func=lambda msg: msg.text == "💬 Active Session")
@check_auth
def show_active_session_info(message):
    active_conv = agent_runner.active_conversations.get(message.chat.id)
    user_ws = agent_runner.get_chat_workspace(message.chat.id)
    usage = stream_runner.get_token_usage(message.chat.id)
    sess_tok = usage["session_tokens"]

    if isinstance(active_conv, str):
        title = "Active Session"
        sessions = agent_runner.get_recent_sessions(limit=20)
        for s in sessions:
            if s["id"] == active_conv:
                title = s["title"]
                break

        info_text = (
            f"💬 <b>Current Active Conversation Session</b>\n\n"
            f"🏷 <b>Title:</b> <code>{html.escape(title)}</code>\n"
            f"🆔 <b>Session ID:</b> <code>{active_conv}</code>\n"
            f"📈 <b>Session Context:</b> {sess_tok:,} Tokens\n"
            f"📂 <b>AI Target Workspace:</b> <code>{html.escape(user_ws)}</code>\n\n"
            f"💡 <i>Use <code>/rename &lt;new_title&gt;</code> to rename this session, or <code>/new</code> to start a new session.</i>"
        )
    else:
        info_text = (
            f"💬 <b>Conversation Session Status</b>\n\n"
            f"ℹ️ <b>New Session (Not Yet Saved)</b>\n"
            f"📂 <b>AI Target Workspace:</b> <code>{html.escape(user_ws)}</code>\n\n"
            f"💡 <i>Send a message to start a new chat, or press <b>▶️ Resume / Session</b> to load a past session.</i>"
        )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("▶️ Select Another Session", callback_data="select_session_menu"),
        types.InlineKeyboardButton("🔄 New Session (/new)", callback_data="select_session|new"),
    )
    reply_safe(message, info_text, reply_markup=markup)


@bot.message_handler(commands=["resume"])
@bot.message_handler(func=lambda msg: msg.text == "▶️ Resume / Session")
@check_auth
def execute_resume(message):
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and message.text != "▶️ Resume / Session":
        resume_prompt = args[1].strip()
        status_text = "▶️ <b>RESUME MODE!</b>\n🔄 <i>Resuming conversation session from the last context...</i>"
        process_custom_agent_prompt(message, resume_prompt, status_text, runner_func=agent_runner.resume_session)
    else:
        show_session_picker(message)


@bot.callback_query_handler(func=lambda call: call.data == "select_session_menu")
@check_auth_callback
def handle_select_session_menu(call):
    bot.answer_callback_query(call.id)
    show_session_picker(call)


def show_session_picker(message_or_call):
    sessions = agent_runner.get_recent_sessions(limit=6)
    chat_id = message_or_call.chat.id if hasattr(message_or_call, "chat") else message_or_call.message.chat.id

    if not sessions:
        reply_safe(message_or_call, "📜 No conversation session history found on the server.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    active_conv = agent_runner.active_conversations.get(chat_id)

    for sess in sessions:
        is_active = " (Active)" if active_conv == sess["id"] else ""
        btn_text = f"💬 {sess['title']} ({sess['date']}){is_active}"
        btn = types.InlineKeyboardButton(btn_text, callback_data=f"select_session|{sess['id']}")
        markup.add(btn)

    btn_new = types.InlineKeyboardButton("🔄 New Session (/new)", callback_data="select_session|new")
    markup.add(btn_new)

    text = (
        "📜 <b>Select / Resume Conversation Session:</b>\n\n"
        "Click a session below to load conversation history & resume from that context:"
    )

    if hasattr(message_or_call, "data"):
        try:
            bot.edit_message_text(
                text, chat_id, message_or_call.message.message_id, reply_markup=markup, parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        reply_safe(message_or_call, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("select_session|"))
@check_auth_callback
def handle_session_selection(call):
    conv_id = call.data.split("|", 1)[1]
    chat_id = call.message.chat.id

    if conv_id == "new":
        agent_runner.reset_session(chat_id)
        bot.answer_callback_query(call.id, "Starting new session.")
        bot.edit_message_text(
            "🔄 <b>New Conversation Session Started.</b>\nReady to receive new instructions!",
            chat_id,
            call.message.message_id,
            parse_mode="HTML",
        )
    else:
        agent_runner.set_active_session(chat_id, conv_id)
        bot.answer_callback_query(call.id, "Loading session history...")
        show_session_history_card(chat_id, conv_id, message_id=call.message.message_id)


def show_session_history_card(chat_id, conv_id, message_id=None):
    """Displays history turns safely into separate clean messages without HTML parsing crash or getting stuck!"""
    history_turns = agent_runner.get_full_session_history_formatted(conv_id, max_turns=5)

    header = (
        f"✅ <b>Conversation Session Loaded Successfully!</b>\n"
        f"🆔 <b>Session ID:</b> <code>{conv_id}</code>\n"
        f"📊 <b>Summary:</b> Last {len(history_turns)} messages"
    )

    if message_id:
        try:
            bot.edit_message_text(header, chat_id, message_id, parse_mode="HTML")
        except Exception:
            send_long_message(chat_id, header)
    else:
        send_long_message(chat_id, header)

    if not history_turns:
        send_long_message(chat_id, "<i>No chat history in this session yet. Send a message to get started!</i>")
        return

    for i, turn in enumerate(history_turns, 1):
        u_msg = html.escape(turn.get("user", ""))
        raw_ai = turn.get("ai", "")
        a_msg = formatter.markdown_to_telegram_html(raw_ai)

        turn_block = (
            f"👤 <b>User (#{i}):</b> {u_msg}\n\n🤖 <b>Antigravity AI:</b>\n<blockquote expandable>{a_msg}</blockquote>"
        )
        send_long_message(chat_id, turn_block)
        time.sleep(0.2)

    send_long_message(chat_id, "💡 <i>Your next message will continue this conversation session.</i>")


@bot.message_handler(commands=["rename"])
@check_auth
def rename_session_command(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        reply_safe(
            message,
            "✏️ <b>Usage:</b> <code>/rename New Session Title</code>\nExample: <code>/rename Web Scraper Project</code>",
        )
        return

    new_title = args[1].strip()
    active_conv = agent_runner.active_conversations.get(message.chat.id)

    if not isinstance(active_conv, str):
        reply_safe(
            message,
            "⚠️ No active conversation session to rename. Select a session first via <code>/resume</code> or send a new instruction.",
        )
        return

    if agent_runner.rename_session(active_conv, new_title):
        reply_safe(
            message,
            f"✅ <b>Session Name Successfully Changed!</b>\n🆔 <b>Session ID:</b> <code>{active_conv}</code>\n✏️ <b>New Title:</b> <code>{html.escape(new_title)}</code>",
        )
    else:
        reply_safe(message, "❌ Failed to rename conversation session.")


@bot.message_handler(commands=["delete"])
@check_auth
def delete_session_command(message):
    sessions = agent_runner.get_recent_sessions(limit=8)
    if not sessions:
        reply_safe(message, "📜 No conversation session history to delete.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for sess in sessions:
        btn_text = f"🗑️ Delete: {sess['title']} ({sess['date']})"
        btn = types.InlineKeyboardButton(btn_text, callback_data=f"delete_session|{sess['id']}")
        markup.add(btn)

    text = "🗑️ <b>Delete Conversation Session:</b>\n\nClick a session below to permanently delete it from the server:"
    reply_safe(message, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_session|"))
@check_auth_callback
def handle_delete_session_callback(call):
    conv_id = call.data.split("|", 1)[1]
    if agent_runner.delete_session(conv_id):
        if agent_runner.active_conversations.get(call.message.chat.id) == conv_id:
            agent_runner.reset_session(call.message.chat.id)

        bot.answer_callback_query(call.id, "Session deleted successfully.")
        bot.edit_message_text(
            f"✅ <b>Conversation Session <code>{conv_id[:8]}...</code> Deleted Successfully!</b>",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
        )
    else:
        bot.answer_callback_query(call.id, "Failed to delete session.", show_alert=True)


@bot.message_handler(func=lambda msg: msg.text in ["📊 Status & Usage", "/usage"])
@bot.message_handler(commands=["usage"])
@check_auth
def send_usage(message):
    live_quota_card = agent_runner.fetch_live_user_quota_summary()

    usage = stream_runner.get_token_usage(message.chat.id)
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
        f"• Used Context: <b>{sess_tok:,}</b> / {max_context:,} Tokens ({pct_used:.2f}%)\n"
        f"• Remaining Context: <b>{remaining_ctx:,}</b> Tokens\n"
        f"• Total Accumulated: <b>{tot_tok:,}</b> Tokens\n\n"
        "💡 <i>Type <code>/new</code> to start a new session and reset context capacity to 100%.</i>"
    )
    reply_safe(message, usage_text)


@bot.message_handler(func=lambda msg: msg.text in ["📂 Workspace & Tree", "/workspace"])
@bot.message_handler(commands=["workspace"])
@check_auth
def change_workspace(message):
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and message.text not in ["📂 Workspace & Tree"]:
        new_ws = os.path.abspath(args[1].strip())
        if not os.path.exists(new_ws):
            os.makedirs(new_ws, exist_ok=True)

        agent_runner.set_chat_workspace(message.chat.id, new_ws)
        reply_safe(message, f"✅ <b>AI Workspace Changed & Synced To:</b>\n<code>{html.escape(new_ws)}</code>")
    else:
        show_workspace_picker(message)


def show_workspace_picker(message_or_call):
    chat_id = message_or_call.chat.id if hasattr(message_or_call, "chat") else message_or_call.message.chat.id
    current_ws = agent_runner.get_chat_workspace(chat_id)

    base_dir = "/root/my-project"
    available_dirs = [base_dir]

    if os.path.exists(base_dir):
        for entry in sorted(os.listdir(base_dir)):
            full = os.path.join(base_dir, entry)
            if os.path.isdir(full) and not entry.startswith("."):
                available_dirs.append(full)

    markup = types.InlineKeyboardMarkup(row_width=1)
    for d in available_dirs:
        folder_name = os.path.basename(d) or d
        is_active = " (Active)" if os.path.abspath(d) == os.path.abspath(current_ws) else ""
        btn_text = f"📁 {folder_name}{is_active}"
        token = path_mapper.encode(d)
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"set_ws:{token}"))

    btn_tree = types.InlineKeyboardButton("🌳 Interactive File Explorer (/tree)", callback_data="open_tree_explorer")
    markup.add(btn_tree)

    text = (
        f"📂 <b>Interactive Workspace Picker</b>\n\n"
        f"📍 <b>Current Active Workspace (Synced to AI):</b>\n<code>{html.escape(current_ws)}</code>\n\n"
        f"Select a project directory below to switch AI working directory:"
    )

    if hasattr(message_or_call, "data"):
        try:
            bot.edit_message_text(
                text, chat_id, message_or_call.message.message_id, reply_markup=markup, parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        reply_safe(message_or_call, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "open_tree_explorer")
@check_auth_callback
def handle_open_tree_explorer(call):
    bot.answer_callback_query(call.id)
    show_tree_explorer(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_ws:"))
@check_auth_callback
def handle_set_ws_callback(call):
    chat_id = call.message.chat.id
    token = call.data.split(":", 1)[1]
    new_ws = path_mapper.decode(token)

    if not new_ws:
        bot.answer_callback_query(call.id, "Invalid workspace!", show_alert=True)
        return

    os.makedirs(new_ws, exist_ok=True)
    agent_runner.set_chat_workspace(chat_id, new_ws)

    bot.answer_callback_query(call.id, "Workspace synced to AI!")
    bot.edit_message_text(
        f"✅ <b>AI Workspace Successfully Changed & Synced To:</b>\n<code>{html.escape(new_ws)}</code>\n\n"
        f"<i>All subsequent AI analysis, file searches, and executions will target this folder!</i>",
        chat_id,
        call.message.message_id,
        parse_mode="HTML",
    )


@bot.message_handler(commands=["smash"])
@check_auth
def execute_smash(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        reply_safe(
            message,
            "💥 <b>SMASH MODE!</b>\nEnter bug description or task to smash.\nExample: <code>/smash Fix all errors in bot.py and test until working!</code>",
        )
        return

    smash_prompt = args[1].strip()
    status_text = "💥 <b>SMASH MODE ACTIVATED!</b>\n🔨 <i>AI is smashing bugs and executing complete fixes...</i>"
    process_custom_agent_prompt(message, smash_prompt, status_text, runner_func=agent_runner.run_smash_mode)


@bot.message_handler(commands=["new", "reset"])
@bot.message_handler(func=lambda msg: msg.text == "🔄 New Session")
@check_auth
def reset_conversation(message):
    agent_runner.reset_session(message.chat.id)
    reply_safe(message, "🔄 <b>Antigravity AI chat session successfully reset.</b>\nReady to receive new instructions!")


@bot.message_handler(commands=["goal"])
@check_auth
def execute_goal(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        reply_safe(
            message,
            "⚠️ Enter a goal description.\nExample: <code>/goal Implement complete JWT authentication in project-a</code>",
        )
        return

    goal_prompt = f"Goal: {args[1].strip()}. Ensure this task is completed thoroughly and completely."
    process_agent_prompt(message, goal_prompt)


@bot.message_handler(commands=["plan"])
@check_auth
def execute_plan(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        reply_safe(
            message, "⚠️ Enter a planning topic.\nExample: <code>/plan Database architecture plan for e-commerce</code>"
        )
        return

    plan_prompt = f"Create a step-by-step plan for: {args[1].strip()}"
    process_agent_prompt(message, plan_prompt)


@bot.message_handler(commands=["status"])
@check_auth
def send_status(message):
    try:
        cpu_pct = psutil.cpu_percent(interval=0.8)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        usage = stream_runner.get_token_usage(message.chat.id)
        user_ws = agent_runner.get_chat_workspace(message.chat.id)
        cur_model = agent_runner.get_chat_setting(message.chat.id, "model", config.DEFAULT_MODEL)
        cur_effort = agent_runner.get_chat_setting(message.chat.id, "effort", config.DEFAULT_EFFORT)

        cpu_bar = make_progress_bar(cpu_pct)
        ram_bar = make_progress_bar(ram.percent)
        disk_bar = make_progress_bar(disk.percent)

        ram_used_str = f"{ram.used // (1024**2)} MB"
        ram_total_str = f"{ram.total // (1024**2)} MB"
        disk_used_str = f"{disk.used // (1024**3)} GB"
        disk_total_str = f"{disk.total // (1024**3)} GB"

        status_text = (
            "📊 <b>Server & AI Engine Status</b>\n\n"
            f"💻 <b>CPU Usage:</b>\n<code>{cpu_bar}</code>\n\n"
            f"🧠 <b>RAM Usage:</b>\n<code>{ram_bar}</code> ({ram_used_str} / {ram_total_str})\n\n"
            f"💾 <b>Disk Usage:</b>\n<code>{disk_bar}</code> ({disk_used_str} / {disk_total_str})\n\n"
            f"🤖 <b>Active Model:</b> <code>{cur_model}</code>\n"
            f"🎯 <b>Effort Level:</b> <code>{cur_effort}</code>\n"
            f"📈 <b>Session Context:</b> {usage['session_tokens']:,} Tokens\n"
            f"📊 <b>Total Tokens:</b> {usage['total_tokens']:,} Tokens\n"
            f"🚀 <b>AGY Executable:</b> <code>{config.AGY_PATH}</code>\n"
            f"📂 <b>Workspace Active:</b> <code>{html.escape(user_ws)}</code>"
        )
        reply_safe(message, status_text)
    except Exception as e:
        reply_safe(message, f"❌ Error status: {html.escape(str(e))}")


@bot.message_handler(content_types=["photo", "document"])
@check_auth
def handle_media_prompt(message):
    try:
        caption = message.caption or "Analyze this file/photo and help fix any errors if present."
        file_info = None
        file_name = "uploaded_file"

        if message.photo:
            file_info = bot.get_file(message.photo[-1].file_id)
            file_name = f"photo_{int(time.time())}.jpg"
        elif message.document:
            file_info = bot.get_file(message.document.file_id)
            file_name = message.document.file_name or f"doc_{int(time.time())}"

        if file_info:
            downloaded = bot.download_file(file_info.file_path)
            temp_dir = getattr(config, "TEMP_UPLOAD_DIR", "/tmp/antigravity_uploads")
            os.makedirs(temp_dir, exist_ok=True)
            saved_path = os.path.join(temp_dir, file_name)
            with open(saved_path, "wb") as f:
                f.write(downloaded)

            prompt = f"File uploaded at '{saved_path}'. Instructions: {caption}"
            process_agent_prompt(message, prompt)
    except Exception as e:
        reply_safe(message, f"❌ Failed to process file/photo: {html.escape(str(e))}")


@bot.message_handler(func=lambda msg: True, content_types=["text"])
@check_auth
def handle_text_prompt(message):
    prompt = message.text.strip()
    if not prompt:
        return
    process_agent_prompt(message, prompt)


def process_agent_prompt(message, prompt):
    status_text = "<i>thinking...</i>"
    process_custom_agent_prompt(message, prompt, status_text, runner_func=agent_runner.run_antigravity_agent)


def process_custom_agent_prompt(message, prompt, status_text, runner_func):
    cancel_markup = types.InlineKeyboardMarkup()
    cancel_markup.add(types.InlineKeyboardButton("🛑 Cancel / Stop", callback_data="cancel_execution"))

    status_msg = reply_safe(message, status_text, reply_markup=cancel_markup)
    user_ws = agent_runner.get_chat_workspace(message.chat.id)
    cur_model = agent_runner.get_chat_setting(message.chat.id, "model", config.DEFAULT_MODEL)
    cur_effort = agent_runner.get_chat_setting(message.chat.id, "effort", config.DEFAULT_EFFORT)

    def worker():
        stop_typing = threading.Event()
        typing_thread = threading.Thread(target=keep_typing_alive, args=(message.chat.id, stop_typing))
        typing_thread.start()

        def update_progress(text):
            if status_msg:
                try:
                    bot.edit_message_text(
                        text, message.chat.id, status_msg.message_id, parse_mode="HTML", reply_markup=cancel_markup
                    )
                except Exception:
                    pass

        try:
            response, turn_usage, generated_files = runner_func(
                prompt, message.chat.id, user_ws, progress_callback=update_progress
            )

            stop_typing.set()
            typing_thread.join(timeout=1)

            if status_msg:
                try:
                    bot.delete_message(message.chat.id, status_msg.message_id)
                except Exception:
                    pass

            formatted_response = formatter.markdown_to_telegram_html(response)
            header_card = formatter.format_response_header(cur_model, cur_effort, user_ws)

            final_output = header_card + formatted_response
            if turn_usage and turn_usage.get("total_tokens"):
                tot = turn_usage.get("total_tokens", 0)
                inp = turn_usage.get("input_tokens", 0)
                out = turn_usage.get("output_tokens", 0)
                thk = turn_usage.get("thinking_tokens", 0)
                cac = turn_usage.get("cache_read_tokens", 0)
                usage_badge = (
                    f"\n\n───────────────\n"
                    f"📊 <b>Token Used:</b> {tot:,} <i>(In: {inp:,} | Out: {out:,} | Think: {thk:,} | Cache: {cac:,})</i>"
                )
                final_output += usage_badge

            # Quick Action Bar inline keyboard on every response message
            action_bar = types.InlineKeyboardMarkup(row_width=2)
            action_bar.add(
                types.InlineKeyboardButton("🌳 Browse Files", callback_data="open_tree_explorer"),
                types.InlineKeyboardButton("📊 Live Quotas", callback_data="open_quota_info"),
            )

            send_long_message(message.chat.id, final_output, reply_markup=action_bar)

            if generated_files:
                for fpath in generated_files[:3]:
                    if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                        try:
                            ext = os.path.splitext(fpath)[1].lower()
                            with open(fpath, "rb") as doc:
                                if ext in [".png", ".jpg", ".jpeg", ".webp"]:
                                    bot.send_photo(
                                        message.chat.id, doc, caption=f"🖼️ Generated Image: {os.path.basename(fpath)}"
                                    )
                                else:
                                    bot.send_document(
                                        message.chat.id, doc, caption=f"📄 Generated File: {os.path.basename(fpath)}"
                                    )
                        except Exception as e:
                            print(f"[ERROR] Auto-send file failed: {e}")

        except Exception as e:
            stop_typing.set()
            traceback.print_exc()
            err_card = formatter.format_error_card(
                str(e), suggestion="Try typing /new to reset the session or check your server connection."
            )
            reply_safe(message, err_card)

    task_thread = threading.Thread(target=worker, daemon=True)
    task_thread.start()


@bot.callback_query_handler(func=lambda call: call.data == "open_quota_info")
@check_auth_callback
def handle_open_quota_info(call):
    bot.answer_callback_query(call.id)
    send_usage(call.message)


def main():
    if not config.validate_config():
        print("[ERROR] Please configure .env before starting the bot.")
        sys.exit(1)

    register_telegram_commands(bot)

    print("🚀 Starting Antigravity AI Agent Bot (v3.5 Polished UX & Dropdown Menu)...")
    print(f"📂 Default Workspace Dir: {config.DEFAULT_WORKSPACE}")
    print(f"🔒 Allowed User IDs: {config.ALLOWED_USER_IDS}")

    try:
        bot.remove_webhook()
        print("✅ Webhook status cleared.")
    except Exception as e:
        print(f"⚠️ Remove webhook notice: {e}")

    print("🤖 Bot is active & polling for messages...")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)


if __name__ == "__main__":
    main()
