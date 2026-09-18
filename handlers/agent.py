import asyncio
from collections.abc import Callable
import contextlib
import html
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

import agent_runner
from bot_utils import reply_safe, send_long_message
from callbacks import NavigationCallback
import config
import formatter
from keyboards import (
    get_action_bar_keyboard,
    get_cancel_keyboard,
    get_main_reply_keyboard,
)

router = Router(name="agent")
_active_background_tasks: set[asyncio.Task[Any]] = set()


@router.message(Command(commands=["smash"]))
async def execute_smash(message: Message, bot: Bot) -> None:
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
    )


@router.message(Command(commands=["goal"]))
async def execute_goal(message: Message, bot: Bot) -> None:
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
    await process_agent_prompt(bot, message, goal_prompt)


@router.message(Command(commands=["plan"]))
async def execute_plan(message: Message, bot: Bot) -> None:
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
    await process_agent_prompt(bot, message, plan_prompt)


@router.callback_query(NavigationCallback.filter(F.target == "cancel_execution"))
async def handle_cancel_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    if agent_runner.cancel_chat_process(chat_id):
        await callback.answer("Process cancelled!")
        with contextlib.suppress(Exception):
            await callback.message.edit_text(
                "🛑 <b>Execution Cancelled by User.</b>",
                parse_mode="HTML",
            )
    else:
        await callback.answer("No running process.", show_alert=True)


@router.callback_query(NavigationCallback.filter(F.target == "quota_info"))
async def handle_quota_info_callback(callback: CallbackQuery, bot: Bot) -> None:
    if callback.message is None:
        return
    await callback.answer()
    from handlers.commands import send_usage

    await send_usage(callback.message, bot)


@router.message(F.photo | F.document)
async def handle_media_prompt(message: Message, bot: Bot) -> None:
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
            await process_agent_prompt(bot, message, prompt)
    except Exception as e:
        err_msg = f"❌ Failed to process file/photo: {html.escape(str(e))}"
        await reply_safe(bot, message, err_msg)


@router.message(F.text)
async def handle_text_prompt(message: Message, bot: Bot) -> None:
    prompt = (message.text or "").strip()
    if not prompt:
        return
    await process_agent_prompt(bot, message, prompt)


async def process_agent_prompt(bot: Bot, message: Message, prompt: str) -> None:
    status_text = "<i>thinking...</i>"
    await process_custom_agent_prompt(
        bot=bot,
        chat_id=message.chat.id,
        prompt=prompt,
        status_text=status_text,
        runner_func=agent_runner.run_antigravity_agent,
        reply_to_message_id=message.message_id,
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

    user_ws = agent_runner.get_chat_workspace(chat_id)
    cur_model = agent_runner.get_chat_setting(
        chat_id,
        "model",
        config.DEFAULT_MODEL,
    )
    cur_effort = agent_runner.get_chat_setting(
        chat_id,
        "effort",
        config.DEFAULT_EFFORT,
    )

    async def _worker() -> None:  # noqa: C901
        loop = asyncio.get_running_loop()
        last_edit_time = 0.0

        def sync_progress_callback(text: str) -> None:
            nonlocal last_edit_time
            if not status_msg:
                return
            now = time.time()
            if now - last_edit_time < 1.2:
                return
            last_edit_time = now

            async def _edit() -> None:
                try:
                    await bot.edit_message_text(
                        text=text,
                        chat_id=chat_id,
                        message_id=status_msg.message_id,
                        parse_mode="HTML",
                        reply_markup=cancel_markup,
                    )
                except Exception:
                    with contextlib.suppress(Exception):
                        await bot.edit_message_text(
                            text=re.sub(r"<[^>]+>", "", text),
                            chat_id=chat_id,
                            message_id=status_msg.message_id,
                            parse_mode=None,
                            reply_markup=cancel_markup,
                        )

            asyncio.run_coroutine_threadsafe(_edit(), loop)

        try:
            async with ChatActionSender.typing(chat_id=chat_id, bot=bot, interval=4.0):
                response, turn_usage, generated_files = await asyncio.to_thread(
                    runner_func,
                    prompt,
                    chat_id,
                    user_ws,
                    progress_callback=sync_progress_callback,
                )

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

            final_output = header_card + formatted_response
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
