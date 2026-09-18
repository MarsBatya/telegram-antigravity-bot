import contextlib
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import agent_runner
from bot_utils import reply_safe
from callbacks import EffortCallback, ModeCallback, ModelCallback, NavigationCallback
import config
from keyboards import get_effort_keyboard, get_mode_keyboard, get_model_keyboard
from storage import SessionStorage

router = Router(name="settings")


def _get_models_list() -> list[dict[str, Any]]:
    models = agent_runner.fetch_available_models_live()
    if not models:
        models = [
            {"id": "gemini-3.6-flash-high", "displayName": "Gemini 3.6 Flash (High)"},
            {
                "id": "gemini-3.6-flash-medium",
                "displayName": "Gemini 3.6 Flash (Medium)",
            },
            {"id": "gemini-3.1-pro-high", "displayName": "Gemini 3.1 Pro (High)"},
            {"id": "claude-sonnet-4-6", "displayName": "Claude Sonnet 4.6 (Thinking)"},
            {
                "id": "claude-opus-4-6-thinking",
                "displayName": "Claude Opus 4.6 (Thinking)",
            },
            {"id": "gpt-oss-120b-medium", "displayName": "GPT-OSS 120B (Medium)"},
        ]
    return models


@router.message(Command(commands=["model"]))
@router.message(F.text == "🤖 Model & Effort")
async def show_model_picker(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    chat_id = message.chat.id
    cur_model = session_storage.get_setting(chat_id, "model", config.DEFAULT_MODEL)
    models = _get_models_list()
    markup = get_model_keyboard(cur_model, models)

    text = (
        "🤖 <b>Antigravity AI Model Selector</b>\n\n"
        f"🎯 <b>Current Active Model:</b> <code>{cur_model}</code>\n\n"
        "Select an AI model below to use in the conversation:"
    )
    await reply_safe(bot, message, text, reply_markup=markup)


@router.callback_query(NavigationCallback.filter(F.target == "effort_menu"))
async def handle_open_effort_menu(
    callback: CallbackQuery,
    session_storage: SessionStorage,
) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    cur_effort = session_storage.get_setting(chat_id, "effort", config.DEFAULT_EFFORT)
    markup = get_effort_keyboard(cur_effort)
    text = (
        "🎯 <b>Antigravity Reasoning Effort Level</b>\n\n"
        f"📊 <b>Active Effort Level:</b> <code>{cur_effort}</code>\n\n"
        "Select the AI reasoning depth for task execution:"
    )
    with contextlib.suppress(Exception):
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


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
        await callback.message.edit_text(
            f"✅ <b>AI Model Successfully Changed To:</b>\n<code>{m_id}</code>\n\n"
            f"<i>All subsequent AI executions will use this model!</i>",
            parse_mode="HTML",
        )


@router.message(Command(commands=["effort"]))
async def show_effort_picker(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    chat_id = message.chat.id
    cur_effort = session_storage.get_setting(chat_id, "effort", config.DEFAULT_EFFORT)
    markup = get_effort_keyboard(cur_effort)
    text = (
        "🎯 <b>Antigravity Reasoning Effort Level</b>\n\n"
        f"📊 <b>Active Effort Level:</b> <code>{cur_effort}</code>\n\n"
        "Select the AI reasoning depth for task execution:"
    )
    await reply_safe(bot, message, text, reply_markup=markup)


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
            f"✅ <b>Reasoning Effort Successfully Changed To:</b> "
            f"<code>{eff_key.upper()}</code>",
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
