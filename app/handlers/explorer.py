import contextlib
import datetime
import html
import os
import sys

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.core import config
from app.core.storage import SessionStorage
from app.ui.callbacks import (
    BrowseDirCallback,
    FileInfoCallback,
    FileUploadCallback,
    NavigationCallback,
    WorkspaceCallback,
)
from app.ui.keyboards import (
    get_file_details_keyboard,
    get_tree_keyboard,
    get_workspace_keyboard,
)
from app.utils.bot_utils import reply_safe
from app.utils.helpers import PathMapper, format_file_size

router = Router(name="explorer")

TREE_PAGE_SIZE: int = 10


@router.message(Command(commands=["workspace"]))
async def change_workspace(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
    path_mapper: PathMapper,
) -> None:
    text = message.text or ""
    args = text.split(maxsplit=1)
    if len(args) > 1 and text not in ["📂 Workspace & Tree"]:
        new_ws = os.path.abspath(args[1].strip())
        if not os.path.exists(new_ws):
            os.makedirs(new_ws, exist_ok=True)

        session_storage.set_workspace(message.chat.id, new_ws)
        await reply_safe(
            bot,
            message,
            f"✅ <b>AI Workspace Changed & Synced To:</b>\n"
            f"<code>{html.escape(new_ws)}</code>",
        )
    else:
        await show_workspace_picker(
            message,
            bot,
            session_storage=session_storage,
            path_mapper=path_mapper,
        )


async def show_workspace_picker(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
    path_mapper: PathMapper,
) -> None:
    chat_id = message.chat.id
    current_ws = session_storage.get_workspace(chat_id)

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
    session_storage: SessionStorage,
    path_mapper: PathMapper,
) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    new_ws = path_mapper.decode(callback_data.token)

    if not new_ws:
        await callback.answer("Invalid workspace!", show_alert=True)
        return

    os.makedirs(new_ws, exist_ok=True)
    session_storage.set_workspace(chat_id, new_ws)

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
async def show_tree_explorer(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
    path_mapper: PathMapper,
) -> None:
    current_ws = session_storage.get_workspace(message.chat.id)
    await render_file_explorer_message(
        message,
        bot,
        current_ws,
        session_storage=session_storage,
        path_mapper=path_mapper,
    )


@router.callback_query(NavigationCallback.filter(F.target == "tree_explorer"))
async def handle_nav_tree(
    callback: CallbackQuery,
    session_storage: SessionStorage,
    path_mapper: PathMapper,
) -> None:
    if callback.message is None:
        return
    current_ws = session_storage.get_workspace(callback.message.chat.id)
    await render_file_explorer_callback(
        callback,
        current_ws,
        session_storage=session_storage,
        path_mapper=path_mapper,
    )


@router.callback_query(BrowseDirCallback.filter())
async def handle_browse_dir_callback(
    callback: CallbackQuery,
    callback_data: BrowseDirCallback,
    session_storage: SessionStorage,
    path_mapper: PathMapper,
) -> None:
    path_dir = path_mapper.decode(callback_data.token) or config.DEFAULT_WORKSPACE
    await render_file_explorer_callback(
        callback,
        path_dir,
        page=callback_data.page,
        session_storage=session_storage,
        path_mapper=path_mapper,
    )


@router.callback_query(FileInfoCallback.filter())
async def handle_file_info_callback(
    callback: CallbackQuery,
    callback_data: FileInfoCallback,
    path_mapper: PathMapper,
) -> None:
    if callback.message is None:
        return
    file_path = path_mapper.decode(callback_data.token)
    if not file_path or not os.path.exists(file_path):
        await callback.answer("File not found or moved!", show_alert=True)
        return

    fname = os.path.basename(file_path)
    parent_dir = os.path.dirname(file_path)
    dir_token = path_mapper.encode(parent_dir)

    try:
        size_bytes = os.path.getsize(file_path)
        mtime = os.path.getmtime(file_path)
        mtime_str = datetime.datetime.fromtimestamp(mtime).strftime(
            "%Y-%m-%d %H:%M:%S",
        )
    except OSError:
        size_bytes = 0
        mtime_str = "Unknown"

    size_formatted = format_file_size(size_bytes)
    is_empty = size_bytes == 0
    is_oversized = size_bytes > 50 * 1024 * 1024
    can_upload = not is_empty and not is_oversized

    text = (
        f"📄 <b>File Information</b>\n\n"
        f"📁 <b>Filename:</b> <code>{html.escape(fname)}</code>\n"
        f"📂 <b>Directory:</b> <code>{html.escape(parent_dir)}</code>\n"
        f"📏 <b>Size:</b> {size_formatted} (<code>{size_bytes:,} bytes</code>)\n"
        f"🕒 <b>Modified:</b> {mtime_str}\n\n"
    )
    if is_empty:
        text += (
            "⚠️ <i>File is empty (0 bytes). "
            "Telegram does not allow sending empty files.</i>"
        )
    elif is_oversized:
        text += "⚠️ <i>File exceeds Telegram's 50MB upload limit.</i>"
    else:
        text += "<i>Tap below to upload this file directly into your Telegram chat:</i>"

    markup = get_file_details_keyboard(
        file_token=callback_data.token,
        dir_token=dir_token,
        page=callback_data.page,
        can_upload=can_upload,
    )
    with contextlib.suppress(Exception):
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(FileUploadCallback.filter())
async def handle_file_upload_callback(
    callback: CallbackQuery,
    callback_data: FileUploadCallback,
    bot: Bot,
    path_mapper: PathMapper,
) -> None:
    if callback.message is None:
        return
    file_path = path_mapper.decode(callback_data.token)
    if not file_path or not os.path.exists(file_path) or not os.path.isfile(file_path):
        await callback.answer("File not found or cannot be read!", show_alert=True)
        return

    try:
        size_bytes = os.path.getsize(file_path)
    except OSError:
        await callback.answer("Unable to read file size!", show_alert=True)
        return

    if size_bytes == 0:
        await callback.answer(
            "⚠️ File is empty (0 bytes). Telegram does not allow sending empty files.",
            show_alert=True,
        )
        return

    if size_bytes > 50 * 1024 * 1024:
        await callback.answer(
            "⚠️ File exceeds Telegram's 50MB upload limit!",
            show_alert=True,
        )
        return

    await callback.answer("📤 Uploading file to chat...", show_alert=False)
    chat_id = callback.message.chat.id
    fname = os.path.basename(file_path)
    size_formatted = format_file_size(size_bytes)
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext in [".png", ".jpg", ".jpeg", ".webp"]:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(file_path),
                    caption=f"🖼️ <b>{html.escape(fname)}</b> ({size_formatted})",
                    parse_mode="HTML",
                )
            except Exception:
                await bot.send_document(
                    chat_id=chat_id,
                    document=FSInputFile(file_path),
                    caption=f"📄 <b>{html.escape(fname)}</b> ({size_formatted})",
                    parse_mode="HTML",
                )
        else:
            await bot.send_document(
                chat_id=chat_id,
                document=FSInputFile(file_path),
                caption=f"📄 <b>{html.escape(fname)}</b> ({size_formatted})",
                parse_mode="HTML",
            )
    except Exception as exc:
        print(f"[ERROR] Failed to send file {file_path}: {exc}")
        await callback.answer(f"Failed to upload: {exc}", show_alert=True)
        return

    parent_dir = os.path.dirname(file_path)
    dir_token = path_mapper.encode(parent_dir)
    markup = get_file_details_keyboard(
        file_token=callback_data.token,
        dir_token=dir_token,
        page=callback_data.page,
        can_upload=True,
        uploaded=True,
    )
    success_text = (
        f"✅ <b>File Successfully Uploaded to Chat!</b>\n\n"
        f"📁 <b>Filename:</b> <code>{html.escape(fname)}</code>\n"
        f"📂 <b>Directory:</b> <code>{html.escape(parent_dir)}</code>\n"
        f"📏 <b>Size:</b> {size_formatted} (<code>{size_bytes:,} bytes</code>)\n\n"
        f"<i>File has been delivered above. "
        f"You can upload again or return to files.</i>"
    )
    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            success_text,
            reply_markup=markup,
            parse_mode="HTML",
        )


def _build_tree_data(
    chat_id: int,
    path_dir: str,
    session_storage: SessionStorage,
) -> tuple[str, str, list[str], list[tuple[str, float]]]:
    norm_path = os.path.abspath(path_dir)
    if not os.path.exists(norm_path):
        norm_path = config.DEFAULT_WORKSPACE

    cur_ws = session_storage.get_workspace(chat_id)
    dirs: list[str] = []
    files: list[tuple[str, float]] = []

    try:
        entries = sorted(os.listdir(norm_path))
        for e in entries:
            if e.startswith("."):
                continue
            full_e = os.path.join(norm_path, e)
            try:
                if os.path.isdir(full_e):
                    dirs.append(e)
                else:
                    sz_kb = round(os.path.getsize(full_e) / 1024, 1)
                    files.append((e, sz_kb))
            except (OSError, PermissionError):
                continue
    except Exception as e:
        print(f"[ERROR] Listing dir {norm_path}: {e}")

    return norm_path, cur_ws, dirs, files


def _paginate_tree_entries(
    dirs: list[str],
    files: list[tuple[str, float]],
    page: int = 1,
    page_size: int = TREE_PAGE_SIZE,
) -> tuple[list[str], list[tuple[str, float]], int, int, int]:
    """Slices combined dirs and files for the requested page.

    Returns (page_dirs, page_files, valid_page, total_pages, total_items).
    """
    total_items = len(dirs) + len(files)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    valid_page = max(1, min(page, total_pages))

    start_idx = (valid_page - 1) * page_size
    end_idx = start_idx + page_size
    num_dirs = len(dirs)

    dir_start = max(0, min(start_idx, num_dirs))
    dir_end = max(0, min(end_idx, num_dirs))
    page_dirs = dirs[dir_start:dir_end]

    file_start = max(0, min(start_idx - num_dirs, len(files)))
    file_end = max(0, min(end_idx - num_dirs, len(files)))
    page_files = files[file_start:file_end]

    return page_dirs, page_files, valid_page, total_pages, total_items


async def render_file_explorer(
    event: Message | CallbackQuery,
    path_dir: str,
    *,
    session_storage: SessionStorage,
    path_mapper: PathMapper,
    bot: Bot | None = None,
    page: int = 1,
) -> None:
    msg = event if isinstance(event, Message) else event.message
    if msg is None:
        return
    norm_path, cur_ws, all_dirs, all_files = _build_tree_data(
        msg.chat.id,
        path_dir,
        session_storage=session_storage,
    )
    page_dirs, page_files, page, total_pages, total_items = _paginate_tree_entries(
        all_dirs,
        all_files,
        page=page,
        page_size=TREE_PAGE_SIZE,
    )
    markup = get_tree_keyboard(
        norm_path,
        cur_ws,
        page_dirs,
        page_files,
        path_mapper.encode,
        page=page,
        total_pages=total_pages,
    )
    if total_items == 0:
        info_line = "📊 <i>(Directory is empty)</i>\n\n"
    elif total_pages > 1:
        info_line = (
            f"📊 <b>Page {page}/{total_pages}</b> ({total_items} items total)\n\n"
        )
    else:
        info_line = f"📊 <b>{total_items} items total</b>\n\n"

    platform_desc = "Windows" if sys.platform == "win32" else "Server"
    text = (
        f"🌳 <b>Interactive File Explorer ({platform_desc})</b>\n\n"
        f"📂 <b>Current Path:</b>\n<code>{html.escape(norm_path)}</code>\n\n"
        f"{info_line}"
        f"Click a folder to browse, or tap a file to view and upload to chat:"
    )
    if isinstance(event, Message):
        target_bot = bot or event.bot
        if target_bot:
            await reply_safe(target_bot, event, text, reply_markup=markup)
    else:
        with contextlib.suppress(Exception):
            await event.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


async def render_file_explorer_message(
    message: Message,
    bot: Bot,
    path_dir: str,
    *,
    session_storage: SessionStorage,
    path_mapper: PathMapper,
    page: int = 1,
) -> None:
    await render_file_explorer(
        message,
        path_dir,
        session_storage=session_storage,
        path_mapper=path_mapper,
        bot=bot,
        page=page,
    )


async def render_file_explorer_callback(
    callback: CallbackQuery,
    path_dir: str,
    *,
    session_storage: SessionStorage,
    path_mapper: PathMapper,
    page: int = 1,
) -> None:
    await render_file_explorer(
        callback,
        path_dir,
        session_storage=session_storage,
        path_mapper=path_mapper,
        page=page,
    )
