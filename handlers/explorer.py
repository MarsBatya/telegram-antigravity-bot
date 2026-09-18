import contextlib
import html
import os

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import agent_runner
from bot_utils import path_mapper, reply_safe
from callbacks import (
    BrowseDirCallback,
    FileInfoCallback,
    NavigationCallback,
    WorkspaceCallback,
)
import config
from keyboards import get_tree_keyboard, get_workspace_keyboard

router = Router(name="explorer")


@router.message(Command(commands=["workspace"]))
async def change_workspace(message: Message, bot: Bot) -> None:
    text = message.text or ""
    args = text.split(maxsplit=1)
    if len(args) > 1 and text not in ["📂 Workspace & Tree"]:
        new_ws = os.path.abspath(args[1].strip())
        if not os.path.exists(new_ws):
            os.makedirs(new_ws, exist_ok=True)

        agent_runner.set_chat_workspace(message.chat.id, new_ws)
        await reply_safe(
            bot,
            message,
            f"✅ <b>AI Workspace Changed & Synced To:</b>\n"
            f"<code>{html.escape(new_ws)}</code>",
        )
    else:
        await show_workspace_picker(message, bot)


async def show_workspace_picker(message: Message, bot: Bot) -> None:
    chat_id = message.chat.id
    current_ws = agent_runner.get_chat_workspace(chat_id)

    base_dir = config.DEFAULT_WORKSPACE
    available_dirs = [base_dir]

    if os.path.exists(base_dir):
        for entry in sorted(os.listdir(base_dir)):
            full = os.path.join(base_dir, entry)
            if os.path.isdir(full) and not entry.startswith("."):
                available_dirs.append(full)

    markup = get_workspace_keyboard(available_dirs, current_ws, path_mapper.encode)
    text = (
        f"📂 <b>Interactive Workspace Picker</b>\n\n"
        f"📍 <b>Current Active Workspace (Synced to AI):</b>\n"
        f"<code>{html.escape(current_ws)}</code>\n\n"
        f"Select a project directory below to switch AI working directory:"
    )
    await reply_safe(bot, message, text, reply_markup=markup)


@router.callback_query(WorkspaceCallback.filter())
async def handle_set_ws_callback(
    callback: CallbackQuery,
    callback_data: WorkspaceCallback,
) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    new_ws = path_mapper.decode(callback_data.token)

    if not new_ws:
        await callback.answer("Invalid workspace!", show_alert=True)
        return

    os.makedirs(new_ws, exist_ok=True)
    agent_runner.set_chat_workspace(chat_id, new_ws)

    await callback.answer("Workspace synced to AI!")
    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            f"✅ <b>AI Workspace Successfully Changed & Synced To:</b>\n"
            f"<code>{html.escape(new_ws)}</code>\n\n"
            f"<i>All subsequent AI analysis, file searches, and executions "
            f"will target this folder!</i>",
            parse_mode="HTML",
        )


@router.message(Command(commands=["tree", "ls"]))
@router.message(F.text == "📂 Workspace & Tree")
async def show_tree_explorer(message: Message, bot: Bot) -> None:
    current_ws = agent_runner.get_chat_workspace(message.chat.id)
    await render_file_explorer_message(message, bot, current_ws)


@router.callback_query(NavigationCallback.filter(F.target == "tree_explorer"))
async def handle_nav_tree(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    current_ws = agent_runner.get_chat_workspace(callback.message.chat.id)
    await render_file_explorer_callback(callback, current_ws)


@router.callback_query(BrowseDirCallback.filter())
async def handle_browse_dir_callback(
    callback: CallbackQuery,
    callback_data: BrowseDirCallback,
) -> None:
    path_dir = path_mapper.decode(callback_data.token) or config.DEFAULT_WORKSPACE
    await render_file_explorer_callback(callback, path_dir)


@router.callback_query(FileInfoCallback.filter())
async def handle_file_info_callback(
    callback: CallbackQuery,
    callback_data: FileInfoCallback,
) -> None:
    await callback.answer(f"File: {callback_data.name}", show_alert=False)


def _build_tree_data(
    chat_id: int,
    path_dir: str,
) -> tuple[str, str, list[str], list[tuple[str, float]]]:
    norm_path = os.path.abspath(path_dir)
    if not os.path.exists(norm_path):
        norm_path = config.DEFAULT_WORKSPACE

    cur_ws = agent_runner.get_chat_workspace(chat_id)
    dirs: list[str] = []
    files: list[tuple[str, float]] = []

    try:
        entries = sorted(os.listdir(norm_path))
        for e in entries:
            if e.startswith("."):
                continue
            full_e = os.path.join(norm_path, e)
            if os.path.isdir(full_e):
                dirs.append(e)
            else:
                sz_kb = round(os.path.getsize(full_e) / 1024, 1)
                files.append((e, sz_kb))
    except Exception as e:
        print(f"[ERROR] Listing dir {norm_path}: {e}")

    return norm_path, cur_ws, dirs[:10], files[:10]


async def render_file_explorer_message(
    message: Message,
    bot: Bot,
    path_dir: str,
) -> None:
    norm_path, cur_ws, dirs, files = _build_tree_data(message.chat.id, path_dir)
    markup = get_tree_keyboard(norm_path, cur_ws, dirs, files, path_mapper.encode)
    text = (
        f"🌳 <b>Interactive File Explorer (VPS)</b>\n\n"
        f"📂 <b>Current Path:</b>\n<code>{html.escape(norm_path)}</code>\n\n"
        f"Click a folder to browse or set as target workspace:"
    )
    await reply_safe(bot, message, text, reply_markup=markup)


async def render_file_explorer_callback(
    callback: CallbackQuery,
    path_dir: str,
) -> None:
    if callback.message is None:
        return
    norm_path, cur_ws, dirs, files = _build_tree_data(
        callback.message.chat.id,
        path_dir,
    )
    markup = get_tree_keyboard(norm_path, cur_ws, dirs, files, path_mapper.encode)
    text = (
        f"🌳 <b>Interactive File Explorer (VPS)</b>\n\n"
        f"📂 <b>Current Path:</b>\n<code>{html.escape(norm_path)}</code>\n\n"
        f"Click a folder to browse or set as target workspace:"
    )
    with contextlib.suppress(Exception):
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
