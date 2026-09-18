import asyncio
import sys
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

import agent_runner
from bot_utils import (
    PathMapper,
    is_authorized,
    make_progress_bar,
    path_mapper,
    register_telegram_commands,
    reply_safe,
    send_long_message,
)
import config
from handlers import (
    agent_router,
    commands_router,
    explorer_router,
    sessions_router,
    settings_router,
)
from handlers.agent import (
    execute_goal,
    execute_plan,
    execute_smash,
    handle_cancel_callback,
    handle_media_prompt,
    handle_quota_info_callback,
    handle_text_prompt,
    process_agent_prompt,
    process_custom_agent_prompt,
)
from handlers.commands import (
    handle_cancel_command,
    send_status,
    send_usage,
    send_welcome,
    show_bot_logs,
)
from handlers.explorer import (
    change_workspace,
    handle_browse_dir_callback,
    handle_file_info_callback,
    handle_nav_tree,
    handle_set_ws_callback,
    render_file_explorer_callback,
    render_file_explorer_message,
    show_tree_explorer,
    show_workspace_picker,
)
from handlers.sessions import (
    delete_session_command,
    execute_resume,
    handle_select_session_menu,
    handle_session_callback,
    rename_session_command,
    reset_conversation,
    show_active_session_info,
    show_session_history_card,
    show_session_picker_callback,
    show_session_picker_message,
)
from handlers.settings import (
    handle_open_effort_menu,
    handle_set_effort_callback,
    handle_set_mode_callback,
    handle_set_model_callback,
    show_effort_picker,
    show_mode_picker,
    show_model_picker,
)
from middlewares import AuthMiddleware
import stream_runner
from stream_runner import cleanup_all_active_processes

_bot_token = (
    config.BOT_TOKEN
    if (config.BOT_TOKEN and ":" in config.BOT_TOKEN)
    else "123456:TEST_DUMMY_TOKEN"
)

bot = Bot(
    token=_bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()


def setup_dispatcher(target_dp: Dispatcher) -> None:
    # Outer middleware for global authentication
    target_dp.message.outer_middleware(AuthMiddleware())
    target_dp.callback_query.outer_middleware(AuthMiddleware())

    # Auto callback answer middleware
    target_dp.callback_query.middleware(CallbackAnswerMiddleware())

    # Register modular routers
    target_dp.include_router(commands_router)
    target_dp.include_router(settings_router)
    target_dp.include_router(explorer_router)
    target_dp.include_router(sessions_router)
    target_dp.include_router(agent_router)


setup_dispatcher(dp)


async def on_shutdown(*args: Any, **kwargs: Any) -> None:
    print("🛑 Shutting down bot, terminating active CLI processes...")
    stream_runner.cleanup_all_active_processes()
    await bot.session.close()


dp.shutdown.register(on_shutdown)


async def main() -> None:
    if not config.validate_config():
        print("[ERROR] Please configure .env before starting the bot.")
        sys.exit(1)

    await register_telegram_commands(bot)

    print("🚀 Starting Antigravity AI Agent Bot (aiogram v3 Modular Architecture)...")
    print(f"📂 Default Workspace Dir: {config.DEFAULT_WORKSPACE}")
    print(f"🔒 Allowed User IDs: {config.ALLOWED_USER_IDS}")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook status cleared.")
    except Exception as e:
        print(f"⚠️ Remove webhook notice: {e}")

    print("🤖 Bot is active & polling for messages...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


__all__ = [
    "PathMapper",
    "agent_runner",
    "bot",
    "change_workspace",
    "cleanup_all_active_processes",
    "delete_session_command",
    "dp",
    "execute_goal",
    "execute_plan",
    "execute_resume",
    "execute_smash",
    "handle_browse_dir_callback",
    "handle_cancel_callback",
    "handle_cancel_command",
    "handle_file_info_callback",
    "handle_media_prompt",
    "handle_nav_tree",
    "handle_open_effort_menu",
    "handle_quota_info_callback",
    "handle_select_session_menu",
    "handle_session_callback",
    "handle_set_effort_callback",
    "handle_set_mode_callback",
    "handle_set_model_callback",
    "handle_set_ws_callback",
    "handle_text_prompt",
    "is_authorized",
    "main",
    "make_progress_bar",
    "on_shutdown",
    "path_mapper",
    "process_agent_prompt",
    "process_custom_agent_prompt",
    "register_telegram_commands",
    "rename_session_command",
    "render_file_explorer_callback",
    "render_file_explorer_message",
    "reply_safe",
    "reset_conversation",
    "send_long_message",
    "send_status",
    "send_usage",
    "send_welcome",
    "setup_dispatcher",
    "show_active_session_info",
    "show_bot_logs",
    "show_effort_picker",
    "show_mode_picker",
    "show_model_picker",
    "show_session_history_card",
    "show_session_picker_callback",
    "show_session_picker_message",
    "show_tree_explorer",
    "show_workspace_picker",
    "stream_runner",
]

if __name__ == "__main__":
    asyncio.run(main())
