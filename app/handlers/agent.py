import asyncio
from collections.abc import Callable
import contextlib
import html
import inspect
import os
import re
import tempfile
import time
import traceback
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.chat_action import ChatActionSender

from app.core import config
from app.core.storage import SessionStorage
from app.runner import agent_runner
from app.ui.callbacks import NavigationCallback
from app.ui.keyboards import (
    get_action_bar_keyboard,
    get_cancel_keyboard,
    get_main_reply_keyboard,
)
from app.utils import formatter
from app.utils.bot_utils import reply_safe, send_long_message

router = Router(name="agent")
_active_background_tasks: set[asyncio.Task[Any]] = set()


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
            "Example: <code>/smash Fix all errors in bot.py "
            "and test until working!</code>",
        )
        return

    smash_prompt = args[1].strip()
    status_text = (
        "💥 <b>SMASH MODE ACTIVATED!</b>\n"
        "🔨 <i>AI is smashing bugs and executing complete fixes...</i>"
    )
    await process_custom_agent_prompt(
        bot=bot,
        chat_id=message.chat.id,
        prompt=smash_prompt,
        status_text=status_text,
        runner_func=agent_runner.run_smash_mode,
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

    goal_prompt = (
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

    plan_prompt = f"Create a step-by-step plan for: {args[1].strip()}"
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
    if agent_runner.cancel_chat_process(chat_id, storage=session_storage):
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


@router.message(F.photo | F.document)
async def handle_media_prompt(
    message: Message,
    bot: Bot,
    session_storage: SessionStorage,
) -> None:
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
        elif message.document:
            file_id = message.document.file_id
            file_info = await bot.get_file(file_id)
            file_name = message.document.file_name or f"doc_{int(time.time())}"

        if file_info and file_info.file_path:
            temp_dir = getattr(
                config,
                "TEMP_UPLOAD_DIR",
                os.path.join(tempfile.gettempdir(), "antigravity_uploads"),
            )
            os.makedirs(temp_dir, exist_ok=True)
            saved_path = os.path.join(temp_dir, file_name)
            await bot.download_file(file_info.file_path, destination=saved_path)

            prompt = f"File uploaded at '{saved_path}'. Instructions: {caption}"
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
    prompt = (message.text or "").strip()
    if not prompt:
        return
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
        runner_func=agent_runner.run_antigravity_agent,
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


async def process_custom_agent_prompt(  # noqa: C901
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

    storage = session_storage
    user_ws = storage.get_workspace(chat_id)
    cur_model = storage.get_setting(
        chat_id,
        "model",
        config.DEFAULT_MODEL,
    )
    cur_effort = storage.get_setting(
        chat_id,
        "effort",
        config.DEFAULT_EFFORT,
    )

    async def _worker() -> None:  # noqa: C901
        loop = asyncio.get_running_loop()
        last_edit_time = 0.0
        last_sent_text = ""
        latest_text = ""
        is_editing = False
        is_finished = False

        def sync_progress_callback(text: str) -> None:
            nonlocal latest_text
            if not status_msg or is_finished:
                return
            latest_text = text
            asyncio.run_coroutine_threadsafe(_trigger_edit(), loop)

        async def _trigger_edit() -> None:
            nonlocal is_editing, last_sent_text, last_edit_time
            if is_editing or is_finished:
                return
            is_editing = True
            try:
                while not is_finished and latest_text and latest_text != last_sent_text:
                    now = time.time()
                    elapsed = now - last_edit_time
                    if elapsed < 1.0:
                        await asyncio.sleep(1.0 - elapsed)
                    if is_finished:
                        break

                    text_to_send = latest_text
                    if text_to_send == last_sent_text:
                        break

                    # Enforce strict length under Telegram's 4096 character limit
                    if len(text_to_send) > 3800:
                        text_to_send = text_to_send[:3700] + "\n<i>(truncated)</i>"

                    last_sent_text = text_to_send
                    last_edit_time = time.time()

                    try:
                        await bot.edit_message_text(
                            text=text_to_send,
                            chat_id=chat_id,
                            message_id=status_msg.message_id,
                            parse_mode="HTML",
                            reply_markup=cancel_markup,
                        )
                    except Exception:
                        if is_finished:
                            break
                        with contextlib.suppress(Exception):
                            await bot.edit_message_text(
                                text=re.sub(r"<[^>]+>", "", text_to_send),
                                chat_id=chat_id,
                                message_id=status_msg.message_id,
                                parse_mode=None,
                                reply_markup=cancel_markup,
                            )
            finally:
                is_editing = False

        try:
            async with ChatActionSender.typing(chat_id=chat_id, bot=bot, interval=4.0):
                sig = inspect.signature(runner_func)
                call_kwargs: dict[str, Any] = {
                    "progress_callback": sync_progress_callback,
                }
                if "storage" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                ):
                    call_kwargs["storage"] = storage

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

            formatted_response = formatter.markdown_to_telegram_html(response)
            header_card = formatter.format_response_header(
                cur_model,
                cur_effort,
                user_ws,
            )
            steps_badge = formatter.format_execution_steps(
                turn_usage.get("steps", []) if turn_usage else [],
            )

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
