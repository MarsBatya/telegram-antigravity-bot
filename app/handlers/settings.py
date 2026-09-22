import contextlib
import html
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.core import config
from app.core.model_manager import ModelManager
from app.core.storage import SessionStorage
from app.ui.callbacks import (
    EffortCallback,
    ModeCallback,
    ModelCallback,
    NavigationCallback,
)
from app.ui.keyboards import (
    get_effort_keyboard,
    get_mode_keyboard,
    get_model_keyboard,
)
from app.utils.bot_utils import reply_safe

router = Router(name="settings")


def _get_models_list(
    model_manager: ModelManager | None = None,
) -> list[dict[str, Any]]:
    mgr = model_manager if model_manager is not None else ModelManager()
    return mgr.get_available_models()


def _resolve_model_id(
    query: str,
    available_models: list[dict[str, Any]] | None = None,
    model_manager: ModelManager | None = None,
) -> str:
    mgr = model_manager if model_manager is not None else ModelManager()
    return mgr.resolve_model_id(query, available_models)


@router.message(Command(commands=["model"]))
@router.message(F.text == "🤖 Model & Effort")
async def show_model_picker(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
    model_manager: ModelManager | None = None,
    command: CommandObject | None = None,
) -> None:
    chat_id = message.chat.id
    mgr = model_manager if model_manager is not None else ModelManager()
    models = mgr.get_available_models()

    if command and command.args:
        raw_target = command.args.strip()
        matched_id = mgr.resolve_model_id(raw_target, models)
        session_storage.set_setting(chat_id, "model", matched_id)
        text = (
            f"✅ <b>AI Model Successfully Changed To:</b>\n"
            f"<code>{html.escape(matched_id)}</code>\n\n"
            f"<i>All subsequent AI executions will use this model!</i>"
        )
        await reply_safe(bot, message, text)
        return

    cur_model = session_storage.get_setting(chat_id, "model", config.DEFAULT_MODEL)
    markup = get_model_keyboard(cur_model, models)

    text = (
        "🤖 <b>Antigravity AI Model Selector</b>\n\n"
        f"🎯 <b>Current Active Model:</b> <code>{html.escape(cur_model)}</code>\n\n"
        "Select an AI model below to use or type <code>/model &lt;name&gt;</code>:"
    )
    await reply_safe(bot, message, text, reply_markup=markup)


async def _render_effort_picker(
    event: Message | CallbackQuery,
    session_storage: SessionStorage,
    bot: Bot | None = None,
) -> None:
    msg = event if isinstance(event, Message) else event.message
    if msg is None:
        return
    cur_effort = session_storage.get_setting(
        msg.chat.id,
        "effort",
        config.DEFAULT_EFFORT,
    )
    markup = get_effort_keyboard(cur_effort)
    text = (
        "🎯 <b>Antigravity Reasoning Effort Level</b>\n\n"
        f"📊 <b>Active Effort Level:</b> <code>{cur_effort}</code>\n\n"
        "Select the AI reasoning depth for task execution:"
    )
    if isinstance(event, Message):
        target_bot = bot or event.bot
        if target_bot:
            await reply_safe(target_bot, event, text, reply_markup=markup)
    else:
        with contextlib.suppress(Exception):
            await event.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(NavigationCallback.filter(F.target == "effort_menu"))
async def handle_open_effort_menu(
    callback: CallbackQuery,
    session_storage: SessionStorage,
) -> None:
    await _render_effort_picker(callback, session_storage)


@router.callback_query(ModelCallback.filter())
async def handle_set_model_callback(
    callback: CallbackQuery,
    callback_data: ModelCallback,
    session_storage: SessionStorage,
) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    m_id = callback_data.model_id
    session_storage.set_setting(chat_id, "model", m_id)

    with contextlib.suppress(Exception):
        text = (
            "✅ <b>AI Model Successfully Changed To:</b>\n"
            f"<code>{html.escape(m_id)}</code>\n\n"
            "<i>All subsequent AI executions will use this model!</i>"
        )
        await callback.message.edit_text(text, parse_mode="HTML")


@router.message(Command(commands=["effort"]))
async def show_effort_picker(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    await _render_effort_picker(message, session_storage, bot=bot)


@router.callback_query(EffortCallback.filter())
async def handle_set_effort_callback(
    callback: CallbackQuery,
    callback_data: EffortCallback,
    session_storage: SessionStorage,
) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    eff_key = callback_data.level
    session_storage.set_setting(chat_id, "effort", eff_key)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            f"✅ <b>Reasoning Effort Successfully Changed To:</b> <code>{eff_key.upper()}</code>",
            parse_mode="HTML",
        )


@router.message(Command(commands=["mode"]))
async def show_mode_picker(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    chat_id = message.chat.id
    cur_mode = session_storage.get_setting(chat_id, "mode", config.DEFAULT_MODE)
    markup = get_mode_keyboard(cur_mode)
    text = (
        "⚙️ <b>Antigravity Agent Execution Mode</b>\n\n"
        f"📍 <b>Current Active Mode:</b> <code>{cur_mode}</code>\n\n"
        "Select AI execution mode:"
    )
    await reply_safe(bot, message, text, reply_markup=markup)


@router.callback_query(ModeCallback.filter())
async def handle_set_mode_callback(
    callback: CallbackQuery,
    callback_data: ModeCallback,
    session_storage: SessionStorage,
) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    mode_key = callback_data.mode
    session_storage.set_setting(chat_id, "mode", mode_key)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            f"✅ <b>Agent Mode Successfully Changed To:</b> <code>{mode_key}</code>",
            parse_mode="HTML",
        )
