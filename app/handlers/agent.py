import asyncio
from collections.abc import Callable
import contextlib
import html
import inspect
import os
import re
import shutil
import tempfile
import time
import traceback
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message
from aiogram.utils.chat_action import ChatActionSender

from app.core import config
from app.core.storage import SessionStorage
from app.runner import stream_runner
from app.ui.callbacks import NavigationCallback, SaveToWorkspaceCallback
from app.ui.keyboards import (
    get_action_bar_keyboard,
    get_cancel_keyboard,
    get_main_reply_keyboard,
    get_save_to_workspace_keyboard,
)
from app.utils import formatter
from app.utils.bot_utils import (
    format_file_size,
    path_mapper,
    reply_safe,
    send_long_message,
)

router = Router(name="agent")
_active_background_tasks: set[asyncio.Task[Any]] = set()

MAX_DOWNLOAD_SIZE_BYTES: int = 100 * 1024 * 1024  # 100 MB


def format_pending_files_system_message(pending_files: list[dict[str, Any]]) -> str:
    """Formats pending uploaded files into a system prompt message to be injected
    before the user's message into the AI dialog.
    """
    if not pending_files:
        return ""
    lines: list[str] = []
    for f in pending_files:
        name = f.get("file_name", "file")
        ws_path = f.get("workspace_path")
        dl_path = f.get("file_path", "")
        if f.get("saved_to_workspace") and ws_path:
            lines.append(
                f"user uploaded '{name}' to the downloads folder "
                f"and confirmed downloading to workspace at '{ws_path}'",
            )
        else:
            lines.append(
                f"user uploaded a '{name}' to the downloads folder ({dl_path})",
            )
    notice = ". ".join(lines)
    return f"[System: {notice}]\n\n"


def _consume_pending_files_prefix(
    session_storage: SessionStorage,
    chat_id: int,
) -> str:
    pending = session_storage.get_and_clear_pending_files(chat_id)
    return format_pending_files_system_message(pending)


@router.message(Command(commands=["smash"]))
async def execute_smash(
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
            "💥 <b>SMASH MODE!</b>\nEnter bug description or task to smash.\n"
            "Example: <code>/smash Fix all errors in main.py "
            "and test until working!</code>",
        )
        return

    prefix = _consume_pending_files_prefix(session_storage, message.chat.id)
    smash_prompt = (
        f"{prefix}"
        "💥 SMASH MODE INSTRUCTION: Complete the following task with "
        "maximum effort, thoroughness, and speed. Fix all bugs, resolve any "
        "broken code/tests, build the project, and do not stop until "
        "everything runs 100% cleanly:\n\n"
        f"{args[1].strip()}"
    )
    status_text = (
        "💥 <b>SMASH MODE ACTIVATED!</b>\n"
        "🔨 <i>AI is smashing bugs and executing complete fixes...</i>"
    )
    await process_custom_agent_prompt(
        bot=bot,
        chat_id=message.chat.id,
        prompt=smash_prompt,
        status_text=status_text,
        runner_func=stream_runner.run_antigravity_stream,
        reply_to_message_id=message.message_id,
        session_storage=session_storage,
    )


@router.message(Command(commands=["goal"]))
async def execute_goal(
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
            "⚠️ Enter a goal description.\n"
            "Example: <code>/goal Implement complete JWT authentication "
            "in project-a</code>",
        )
        return

    prefix = _consume_pending_files_prefix(session_storage, message.chat.id)
    goal_prompt = (
        f"{prefix}"
        f"Goal: {args[1].strip()}. "
        f"Ensure this task is completed thoroughly and completely."
    )
    await process_agent_prompt(
        bot,
        message,
        goal_prompt,
        session_storage=session_storage,
    )


@router.message(Command(commands=["plan"]))
async def execute_plan(
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
            "⚠️ Enter a planning topic.\n"
            "Example: <code>/plan Database architecture plan for e-commerce</code>",
        )
        return

    prefix = _consume_pending_files_prefix(session_storage, message.chat.id)
    plan_prompt = f"{prefix}Create a step-by-step plan for: {args[1].strip()}"
    await process_agent_prompt(
        bot,
        message,
        plan_prompt,
        session_storage=session_storage,
    )


@router.callback_query(NavigationCallback.filter(F.target == "cancel_execution"))
async def handle_cancel_callback(
    callback: CallbackQuery,
    session_storage: SessionStorage,
) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    if session_storage.cancel_chat_process(chat_id):
        await callback.answer("Process cancelled!")
        with contextlib.suppress(Exception):
            await callback.message.edit_text(
                "🛑 <b>Execution Cancelled by User.</b>",
                parse_mode="HTML",
            )
    else:
        await callback.answer("No running process.", show_alert=True)


@router.callback_query(NavigationCallback.filter(F.target == "quota_info"))
async def handle_quota_info_callback(
    callback: CallbackQuery,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    if callback.message is None:
        return
    await callback.answer()
    from app.handlers.commands import send_usage

    await send_usage(callback.message, bot, session_storage=session_storage)


@router.message(F.document)
async def handle_document_upload(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    doc = message.document
    if not doc:
        return

    file_name = doc.file_name or f"doc_{int(time.time())}"
    safe_name = os.path.basename(file_name) or f"doc_{int(time.time())}"
    file_size = doc.file_size or 0

    if file_size > MAX_DOWNLOAD_SIZE_BYTES:
        await reply_safe(
            bot,
            message,
            f"⚠️ <b>File Too Large</b>\n"
            f"File <code>{html.escape(safe_name)}</code> is "
            f"{format_file_size(file_size)}, which exceeds the 100MB limit "
            f"for automatic downloads.",
        )
        return

    downloads_dir = getattr(
        config,
        "DOWNLOADS_DIR",
        str(config.PROJECT_ROOT / "downloads"),
    )
    os.makedirs(downloads_dir, exist_ok=True)
    saved_path = os.path.join(downloads_dir, safe_name)

    try:
        file_info = await bot.get_file(doc.file_id)
        if not file_info or not file_info.file_path:
            raise ValueError("Could not retrieve file path from Telegram.")
        await bot.download_file(file_info.file_path, destination=saved_path)
    except Exception as e:
        err_text = str(e)
        if "file is too big" in err_text.lower():
            err_msg = (
                f"❌ <b>Download Failed</b>\n"
                f"Telegram rejected download for "
                f"<code>{html.escape(safe_name)}</code> "
                f"({format_file_size(file_size)}): exceeds Telegram Cloud Bot API "
                f"20MB limit.\n"
                f"<i>(Note: A local Telegram Bot API server is required to "
                f"download files up to 100MB.)</i>"
            )
        else:
            err_msg = (
                f"❌ <b>Download Failed</b>\n"
                f"Failed to download <code>{html.escape(safe_name)}</code>: "
                f"{html.escape(err_text)}"
            )
        await reply_safe(bot, message, err_msg)
        return

    token = path_mapper.encode(saved_path)
    workspace_markup = get_save_to_workspace_keyboard(token)
    caption = (message.caption or "").strip()

    if caption:
        prefix = _consume_pending_files_prefix(session_storage, message.chat.id)
        current_notice = (
            f"user uploaded a '{safe_name}' to the downloads folder ({saved_path})"
        )
        if prefix:
            combined_system = f"{prefix.rstrip()}\n{current_notice}"
            full_prompt = f"{combined_system}\n\n{caption}"
        else:
            full_prompt = f"[System: {current_notice}]\n\n{caption}"

        await reply_safe(
            bot,
            message,
            f"📥 <b>File Downloaded to Server</b>\n\n"
            f"• <b>File:</b> <code>{html.escape(safe_name)}</code>\n"
            f"• <b>Size:</b> {format_file_size(file_size)}\n"
            f"• <b>Saved to:</b> <code>{html.escape(saved_path)}</code>\n\n"
            f"<i>Tap below to confirm downloading this file to your "
            f"active workspace:</i>",
            reply_markup=workspace_markup,
        )
        await process_agent_prompt(
            bot,
            message,
            full_prompt,
            session_storage=session_storage,
        )
    else:
        session_storage.add_pending_file(
            message.chat.id,
            safe_name,
            saved_path,
            file_size,
        )
        await reply_safe(
            bot,
            message,
            f"📥 <b>File Downloaded to Server</b>\n\n"
            f"• <b>File:</b> <code>{html.escape(safe_name)}</code>\n"
            f"• <b>Size:</b> {format_file_size(file_size)}\n"
            f"• <b>Saved to:</b> <code>{html.escape(saved_path)}</code>\n\n"
            f"<i>Tap below to confirm downloading this file to your active workspace, "
            f"or send your instructions/prompt:</i>",
            reply_markup=workspace_markup,
        )


@router.callback_query(SaveToWorkspaceCallback.filter())
async def handle_save_to_workspace_callback(
    callback: CallbackQuery,
    callback_data: SaveToWorkspaceCallback,
    session_storage: SessionStorage,
) -> None:
    if callback.message is None:
        return

    chat_id = callback.message.chat.id
    saved_path = path_mapper.decode(callback_data.token)

    if not saved_path or not os.path.exists(saved_path):
        await callback.answer("⚠️ File not found on server or expired.", show_alert=True)
        return

    file_name = os.path.basename(saved_path)
    workspace = session_storage.get_workspace(chat_id)
    try:
        os.makedirs(workspace, exist_ok=True)
        dest_path = os.path.join(workspace, file_name)
        shutil.copy2(saved_path, dest_path)
        session_storage.mark_file_saved_to_workspace(chat_id, saved_path, dest_path)
        await callback.answer("✅ Saved to workspace!")
        with contextlib.suppress(Exception):
            await callback.message.edit_text(
                f"✅ <b>File Saved to Workspace!</b>\n\n"
                f"• <b>File:</b> <code>{html.escape(file_name)}</code>\n"
                f"• <b>Workspace:</b> <code>{html.escape(dest_path)}</code>\n"
                f"• <b>Downloads:</b> <code>{html.escape(saved_path)}</code>",
                parse_mode="HTML",
            )
    except Exception as e:
        await callback.answer(f"Failed to copy file: {e}", show_alert=True)


@router.message(F.photo)
async def handle_media_prompt(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    if message.document:
        await handle_document_upload(message, bot, session_storage=session_storage)
        return

    caption = (
        message.caption or "Analyze this file/photo and help fix any errors if present."
    )
    file_info = None
    file_name = "uploaded_file"
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
            file_info = await bot.get_file(file_id)
            file_name = f"photo_{int(time.time())}.jpg"

        if file_info and file_info.file_path:
            temp_dir = getattr(
                config,
                "TEMP_UPLOAD_DIR",
                os.path.join(tempfile.gettempdir(), "antigravity_uploads"),
            )
            os.makedirs(temp_dir, exist_ok=True)
            saved_path = os.path.join(temp_dir, file_name)
            await bot.download_file(file_info.file_path, destination=saved_path)

            prefix = _consume_pending_files_prefix(session_storage, message.chat.id)
            prompt = f"{prefix}File uploaded at '{saved_path}'. Instructions: {caption}"
            await process_agent_prompt(
                bot,
                message,
                prompt,
                session_storage=session_storage,
            )
    except Exception as e:
        err_msg = f"❌ Failed to process file/photo: {html.escape(str(e))}"
        await reply_safe(bot, message, err_msg)


@router.message(F.text)
async def handle_text_prompt(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    prefix = _consume_pending_files_prefix(session_storage, message.chat.id)
    prompt = f"{prefix}{text}" if prefix else text
    await process_agent_prompt(
        bot,
        message,
        prompt,
        session_storage=session_storage,
    )


async def process_agent_prompt(
    bot: Bot,
    message: Message,
    prompt: str,
    *,
    session_storage: SessionStorage,
) -> None:
    status_text = "🧠 <b>Thinking...</b> <i>(0s)</i>"
    await process_custom_agent_prompt(
        bot=bot,
        chat_id=message.chat.id,
        prompt=prompt,
        status_text=status_text,
        runner_func=stream_runner.run_antigravity_stream,
        reply_to_message_id=message.message_id,
        session_storage=session_storage,
    )


async def _send_generated_files(
    bot: Bot,
    chat_id: int,
    generated_files: list[str],
) -> None:
    for fpath in generated_files[:3]:
        if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
            try:
                ext = os.path.splitext(fpath)[1].lower()
                input_file = FSInputFile(fpath)
                fname = os.path.basename(fpath)
                if ext in [".png", ".jpg", ".jpeg", ".webp"]:
                    await bot.send_photo(
                        chat_id,
                        input_file,
                        caption=f"🖼️ Generated Image: {fname}",
                    )
                else:
                    await bot.send_document(
                        chat_id,
                        input_file,
                        caption=f"📄 Generated File: {fname}",
                    )
            except Exception as e:
                print(f"[ERROR] Auto-send file failed: {e}")


def _build_final_output(
    response: str,
    turn_usage: dict[str, Any] | None,
    cur_model: str,
    cur_effort: str,
    user_ws: str,
) -> str:
    formatted_response = formatter.markdown_to_telegram_html(response)
    header_card = formatter.format_response_header(cur_model, cur_effort, user_ws)
    steps = turn_usage.get("steps", []) if turn_usage else []
    steps_badge = formatter.format_execution_steps(steps)
    final_output = header_card + steps_badge + formatted_response

    if turn_usage and turn_usage.get("total_tokens"):
        tot = turn_usage.get("total_tokens", 0)
        inp = turn_usage.get("input_tokens", 0)
        out = turn_usage.get("output_tokens", 0)
        thk = turn_usage.get("thinking_tokens", 0)
        cac = turn_usage.get("cache_read_tokens", 0)
        usage_badge = (
            f"\n\n───────────────\n"
            f"📊 <b>Token Used:</b> {tot:,} <i>(In: {inp:,} | Out: {out:,} "
            f"| Think: {thk:,} | Cache: {cac:,})</i>"
        )
        final_output += usage_badge
    return final_output


def _build_runner_kwargs(
    runner_func: Callable[..., Any],
    progress_callback: Callable[[str], None],
    storage: SessionStorage,
) -> dict[str, Any]:
    sig = inspect.signature(runner_func)
    call_kwargs: dict[str, Any] = {"progress_callback": progress_callback}
    if "storage" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    ):
        call_kwargs["storage"] = storage
    return call_kwargs


async def _send_progress_edit(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    if len(text) > 3800:
        text = text[:3700] + "\n<i>(truncated)</i>"
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception:
        with contextlib.suppress(Exception):
            await bot.edit_message_text(
                text=re.sub(r"<[^>]+>", "", text),
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=None,
                reply_markup=reply_markup,
            )


async def process_custom_agent_prompt(
    bot: Bot,
    chat_id: int,
    prompt: str,
    status_text: str,
    runner_func: Callable[..., tuple[str, dict[str, Any], list[str]]],
    *,
    session_storage: SessionStorage,
    reply_to_message_id: int | None = None,
) -> None:
    cancel_markup = get_cancel_keyboard()
    status_msg: Message | None = None
    try:
        status_msg = await bot.send_message(
            chat_id=chat_id,
            text=status_text,
            parse_mode="HTML",
            reply_markup=cancel_markup,
            reply_to_message_id=reply_to_message_id,
        )
    except Exception as e:
        print(f"[WARNING] Could not send initial status message: {e}")

    user_ws = session_storage.get_workspace(chat_id)
    cur_model = session_storage.get_setting(chat_id, "model", config.DEFAULT_MODEL)
    cur_effort = session_storage.get_setting(chat_id, "effort", config.DEFAULT_EFFORT)

    async def _worker() -> None:
        loop = asyncio.get_running_loop()
        is_finished = False

        def sync_progress_callback(text: str) -> None:
            if not status_msg or is_finished:
                return
            asyncio.run_coroutine_threadsafe(
                _send_progress_edit(
                    bot,
                    chat_id,
                    status_msg.message_id,
                    text,
                    cancel_markup,
                ),
                loop,
            )

        try:
            call_kwargs = _build_runner_kwargs(
                runner_func,
                sync_progress_callback,
                session_storage,
            )
            async with ChatActionSender.typing(chat_id=chat_id, bot=bot, interval=4.0):
                response, turn_usage, generated_files = await asyncio.to_thread(
                    runner_func,
                    prompt,
                    chat_id,
                    user_ws,
                    **call_kwargs,
                )

            is_finished = True
            if status_msg:
                with contextlib.suppress(Exception):
                    await bot.delete_message(
                        chat_id=chat_id,
                        message_id=status_msg.message_id,
                    )

            final_output = _build_final_output(
                response,
                turn_usage,
                cur_model,
                cur_effort,
                user_ws,
            )
            action_bar = get_action_bar_keyboard()
            await send_long_message(bot, chat_id, final_output, reply_markup=action_bar)

            if generated_files:
                await _send_generated_files(bot, chat_id, generated_files)

        except Exception as e:
            traceback.print_exc()
            err_card = formatter.format_error_card(
                str(e),
                suggestion=(
                    "Try typing /new to reset the session or check your "
                    "server connection."
                ),
            )
            await bot.send_message(
                chat_id=chat_id,
                text=err_card,
                parse_mode="HTML",
                reply_markup=get_main_reply_keyboard(),
            )

    task = asyncio.create_task(_worker())
    _active_background_tasks.add(task)
    task.add_done_callback(_active_background_tasks.discard)
