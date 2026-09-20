import asyncio
import sys
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from app.core import config
from app.core.storage import SessionStorage
from app.handlers import (
    agent_router,
    commands_router,
    explorer_router,
    sessions_router,
    settings_router,
)
from app.handlers.agent import (
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
from app.handlers.commands import (
    handle_cancel_command,
    send_status,
    send_usage,
    send_welcome,
    show_bot_logs,
)
from app.handlers.explorer import (
    change_workspace,
    handle_browse_dir_callback,
    handle_file_info_callback,
    handle_file_upload_callback,
    handle_nav_tree,
    handle_set_ws_callback,
    render_file_explorer_callback,
    render_file_explorer_message,
    show_tree_explorer,
    show_workspace_picker,
)
from app.handlers.sessions import (
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
from app.handlers.settings import (
    handle_open_effort_menu,
    handle_set_effort_callback,
    handle_set_mode_callback,
    handle_set_model_callback,
    show_effort_picker,
    show_mode_picker,
    show_model_picker,
)
from app.middlewares.auth import AuthMiddleware
from app.runner import agent_runner, stream_runner
from app.utils.bot_utils import (
    PathMapper,
    is_authorized,
    make_progress_bar,
    mask_proxy_url,
    path_mapper,
    register_telegram_commands,
    reply_safe,
    send_long_message,
)

_bot_token = (
    config.BOT_TOKEN
    if (config.BOT_TOKEN and ":" in config.BOT_TOKEN)
    else "123456:TEST_DUMMY_TOKEN"
)


def create_bot_session(proxy: str | None = None) -> AiohttpSession | None:
    """Creates an AiohttpSession configured with HTTP proxy if present."""
    target_proxy = config.get_http_proxy() if proxy is None else proxy
    if target_proxy and target_proxy.strip():
        norm_proxy = config.normalize_proxy_url(target_proxy)
        if norm_proxy:
            return AiohttpSession(proxy=norm_proxy)
    return None


def create_bot(
    token: str | None = None,
    proxy: str | None = None,
) -> Bot:
    """Creates a Bot instance with configured session and defaults."""
    target_token = token or _bot_token
    session = create_bot_session(proxy=proxy)
    return Bot(
        token=target_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


bot = create_bot()
storage = SessionStorage()
dp = Dispatcher()


def setup_dispatcher(
    target_dp: Dispatcher,
    storage: SessionStorage | None = None,
) -> None:
    if not target_dp.sub_routers:
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

    if storage is not None:
        target_dp["session_storage"] = storage


setup_dispatcher(dp, storage=storage)


async def on_shutdown(
    *args: Any,
    router: Router | None = None,
    bot: Bot | None = None,
    session_storage: SessionStorage | None = None,
    **kwargs: Any,
) -> None:
    print("🛑 Shutting down bot, terminating active CLI processes...")
    target_storage = (
        session_storage
        or (router.get("session_storage") if router is not None else None)
        or dp.get("session_storage")
    )
    if isinstance(target_storage, SessionStorage):
        stream_runner.cleanup_all_active_processes(target_storage)
    target_bot = bot or globals().get("bot")
    if target_bot is not None and getattr(target_bot, "session", None) is not None:
        await target_bot.session.close()


dp.shutdown.register(on_shutdown)


async def main() -> None:
    if not config.validate_config():
        print("[ERROR] Please configure .env before starting the bot.")
        sys.exit(1)

    storage = SessionStorage()
    setup_dispatcher(dp, storage=storage)

    await register_telegram_commands(bot)

    print("🚀 Starting Antigravity AI Agent Bot (aiogram v3 Modular Architecture)...")
    print(f"📂 Default Workspace Dir: {config.DEFAULT_WORKSPACE}")
    print(f"🔒 Allowed User IDs: {config.ALLOWED_USER_IDS}")
    session = getattr(bot, "session", None)
    session_proxy = getattr(session, "proxy", None) if session is not None else None
    if session_proxy:
        print(f"🌐 Telegram Connection Proxy: {mask_proxy_url(str(session_proxy))}")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook status cleared.")
    except Exception as e:
        print(f"⚠️ Remove webhook notice: {e}")

    print("🤖 Bot is active & polling for messages...")
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        session_storage=storage,
    )


__all__ = [
    "PathMapper",
    "agent_runner",
    "bot",
    "change_workspace",
    "create_bot",
    "create_bot_session",
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
    "handle_file_upload_callback",
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
    "mask_proxy_url",
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
    "SessionStorage",
]

if __name__ == "__main__":
    asyncio.run(main())
