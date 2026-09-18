import asyncio
import contextlib
import html

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import agent_runner
from bot_utils import reply_safe, send_long_message
from callbacks import NavigationCallback, SessionCallback
import formatter
from keyboards import (
    get_session_delete_keyboard,
    get_session_menu_keyboard,
    get_session_picker_keyboard,
)
from storage import SessionStorage

router = Router(name="sessions")


@router.message(F.text == "💬 Active Session")
async def show_active_session_info(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    chat_id = message.chat.id
    active_conv = session_storage.get_active_session(chat_id)
    user_ws = session_storage.get_workspace(chat_id)
    usage = session_storage.get_token_usage(chat_id)
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
            f"💡 <i>Use <code>/rename &lt;new_title&gt;</code> to rename "
            f"this session, or <code>/new</code> to start a new session.</i>"
        )
    else:
        info_text = (
            f"💬 <b>Conversation Session Status</b>\n\n"
            f"ℹ️ <b>New Session (Not Yet Saved)</b>\n"
            f"📂 <b>AI Target Workspace:</b> <code>{html.escape(user_ws)}</code>\n\n"
            f"💡 <i>Send a message to start a new chat, or press "
            f"<b>▶️ Resume / Session</b> to load a past session.</i>"
        )

    markup = get_session_menu_keyboard()
    await reply_safe(bot, message, info_text, reply_markup=markup)


@router.message(Command(commands=["resume"]))
@router.message(F.text == "▶️ Resume / Session")
async def execute_resume(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    text = message.text or ""
    args = text.split(maxsplit=1)
    if len(args) > 1 and text != "▶️ Resume / Session":
        from handlers.agent import process_custom_agent_prompt

        resume_prompt = args[1].strip()
        status_text = (
            "▶️ <b>RESUME MODE!</b>\n"
            "🔄 <i>Resuming conversation session from the last context...</i>"
        )
        await process_custom_agent_prompt(
            bot=bot,
            chat_id=message.chat.id,
            prompt=resume_prompt,
            status_text=status_text,
            runner_func=agent_runner.resume_session,
            reply_to_message_id=message.message_id,
            session_storage=session_storage,
        )
    else:
        await show_session_picker_message(
            message,
            bot,
            session_storage=session_storage,
        )


@router.callback_query(NavigationCallback.filter(F.target == "select_session_menu"))
async def handle_select_session_menu(
    callback: CallbackQuery,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    await show_session_picker_callback(callback, session_storage=session_storage)


async def show_session_picker_message(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    sessions = agent_runner.get_recent_sessions(limit=6)
    if not sessions:
        await reply_safe(
            bot,
            message,
            "📜 No conversation session history found on the server.",
        )
        return

    active_conv = session_storage.get_active_session(message.chat.id)
    markup = get_session_picker_keyboard(sessions, active_conv)
    text = (
        "📜 <b>Select / Resume Conversation Session:</b>\n\n"
        "Click a session below to load conversation history & resume from that context:"
    )
    await reply_safe(bot, message, text, reply_markup=markup)


async def show_session_picker_callback(
    callback: CallbackQuery,
    *,
    session_storage: SessionStorage,
) -> None:
    if callback.message is None:
        return
    sessions = agent_runner.get_recent_sessions(limit=6)
    if not sessions:
        with contextlib.suppress(Exception):
            await callback.message.edit_text(
                "📜 No conversation session history found on the server.",
                parse_mode="HTML",
            )
        return

    active_conv = session_storage.get_active_session(callback.message.chat.id)
    markup = get_session_picker_keyboard(sessions, active_conv)
    text = (
        "📜 <b>Select / Resume Conversation Session:</b>\n\n"
        "Click a session below to load conversation history & resume from that context:"
    )
    with contextlib.suppress(Exception):
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(SessionCallback.filter())
async def handle_session_callback(
    callback: CallbackQuery,
    callback_data: SessionCallback,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    action = callback_data.action
    conv_id = callback_data.session_id

    if action == "new" or conv_id == "new":
        agent_runner.reset_session(chat_id, storage=session_storage)
        await callback.answer("Starting new session.")
        with contextlib.suppress(Exception):
            await callback.message.edit_text(
                "🔄 <b>New Conversation Session Started.</b>\n"
                "Ready to receive new instructions!",
                parse_mode="HTML",
            )
    elif action == "delete":
        if agent_runner.delete_session(conv_id):
            if session_storage.get_active_session(chat_id) == conv_id:
                agent_runner.reset_session(chat_id, storage=session_storage)
            await callback.answer("Session deleted successfully.")
            with contextlib.suppress(Exception):
                await callback.message.edit_text(
                    f"✅ <b>Conversation Session <code>{conv_id[:8]}...</code> "
                    f"Deleted Successfully!</b>",
                    parse_mode="HTML",
                )
        else:
            await callback.answer("Failed to delete session.", show_alert=True)
    elif action == "select":
        agent_runner.set_active_session(chat_id, conv_id, storage=session_storage)
        await callback.answer("Loading session history...")
        await show_session_history_card(
            bot=bot,
            chat_id=chat_id,
            conv_id=conv_id,
            message_id=callback.message.message_id,
        )


async def show_session_history_card(
    bot: Bot,
    chat_id: int,
    conv_id: str,
    message_id: int | None = None,
) -> None:
    """Displays history turns safely into separate clean messages
    without HTML parsing crash or getting stuck.
    """
    history_turns = agent_runner.get_full_session_history_formatted(
        conv_id,
        max_turns=5,
    )

    header = (
        f"✅ <b>Conversation Session Loaded Successfully!</b>\n"
        f"🆔 <b>Session ID:</b> <code>{conv_id}</code>\n"
        f"📊 <b>Summary:</b> Last {len(history_turns)} messages"
    )

    if message_id:
        try:
            await bot.edit_message_text(
                text=header,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
            )
        except Exception:
            await send_long_message(bot, chat_id, header)
    else:
        await send_long_message(bot, chat_id, header)

    if not history_turns:
        await send_long_message(
            bot,
            chat_id,
            "<i>No chat history in this session yet. "
            "Send a message to get started!</i>",
        )
        return

    for i, turn in enumerate(history_turns, 1):
        u_msg = html.escape(turn.get("user", ""))
        raw_ai = turn.get("ai", "")
        a_msg = formatter.markdown_to_telegram_html(raw_ai)

        turn_block = (
            f"👤 <b>User (#{i}):</b> {u_msg}\n\n"
            f"🤖 <b>Antigravity AI:</b>\n"
            f"<blockquote expandable>{a_msg}</blockquote>"
        )
        await send_long_message(bot, chat_id, turn_block)
        await asyncio.sleep(0.2)

    await send_long_message(
        bot,
        chat_id,
        "💡 <i>Your next message will continue this conversation session.</i>",
    )


@router.message(Command(commands=["rename"]))
async def rename_session_command(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    text = message.text or ""
    args = text.split(maxsplit=1)
    if len(args) < 2:
        await reply_safe(
            bot,
            message,
            "✏️ <b>Usage:</b> <code>/rename New Session Title</code>\n"
            "Example: <code>/rename Web Scraper Project</code>",
        )
        return

    storage = session_storage
    new_title = args[1].strip()
    active_conv = storage.get_active_session(message.chat.id)

    if not isinstance(active_conv, str):
        await reply_safe(
            bot,
            message,
            "⚠️ No active conversation session to rename. "
            "Select a session first via <code>/resume</code> "
            "or send a new instruction.",
        )
        return

    if agent_runner.rename_session(active_conv, new_title):
        await reply_safe(
            bot,
            message,
            f"✅ <b>Session Name Successfully Changed!</b>\n"
            f"🆔 <b>Session ID:</b> <code>{active_conv}</code>\n"
            f"✏️ <b>New Title:</b> <code>{html.escape(new_title)}</code>",
        )
    else:
        await reply_safe(bot, message, "❌ Failed to rename conversation session.")


@router.message(Command(commands=["delete"]))
async def delete_session_command(message: Message, bot: Bot) -> None:
    sessions = agent_runner.get_recent_sessions(limit=8)
    if not sessions:
        await reply_safe(bot, message, "📜 No conversation session history to delete.")
        return

    markup = get_session_delete_keyboard(sessions)
    text = (
        "🗑️ <b>Delete Conversation Session:</b>\n\n"
        "Click a session below to permanently delete it from the server:"
    )
    await reply_safe(bot, message, text, reply_markup=markup)


@router.message(Command(commands=["new", "reset"]))
@router.message(F.text == "🔄 New Session")
async def reset_conversation(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    agent_runner.reset_session(message.chat.id, storage=session_storage)
    await reply_safe(
        bot,
        message,
        "🔄 <b>Antigravity AI chat session successfully reset.</b>\n"
        "Ready to receive new instructions!",
    )
