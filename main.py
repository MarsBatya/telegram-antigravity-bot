"""Antigravity AI Agent Telegram Bot - Main Entry Point."""

import asyncio
import sys
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from app.core import config
from app.core.model_manager import ModelManager
from app.core.storage import SessionStorage
from app.handlers import (
    agent_router,
    commands_router,
    explorer_router,
    sessions_router,
    settings_router,
)
from app.middlewares.auth import AuthMiddleware
from app.utils.bot_utils import register_telegram_commands
from app.utils.helpers import mask_proxy_url

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
model_manager = ModelManager()
dp = Dispatcher()


def setup_dispatcher(
    target_dp: Dispatcher,
    storage: SessionStorage | None = None,
    model_manager: ModelManager | None = None,
) -> None:
    """Configures middlewares, routers, and dependency injection on a Dispatcher."""
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
    if model_manager is not None:
        target_dp["model_manager"] = model_manager


setup_dispatcher(dp, storage=storage, model_manager=model_manager)


async def on_shutdown(
    *args: Any,
    router: Router | None = None,
    bot: Bot | None = None,
    session_storage: SessionStorage | None = None,
    **kwargs: Any,
) -> None:
    """Shuts down active CLI processes and closes bot session on app exit."""
    print("🛑 Shutting down bot, terminating active CLI processes...")
    target_storage = (
        session_storage
        or (router.get("session_storage") if router is not None else None)
        or dp.get("session_storage")
    )
    if isinstance(target_storage, SessionStorage):
        target_storage.cleanup_all_active_processes()
    target_bot = bot or globals().get("bot")
    if target_bot is not None and getattr(target_bot, "session", None) is not None:
        await target_bot.session.close()


dp.shutdown.register(on_shutdown)


async def main() -> None:
    """Launches the Antigravity Telegram bot long-polling process."""
    if not config.validate_config():
        print("[ERROR] Please configure .env before starting the bot.")
        sys.exit(1)

    storage = SessionStorage()
    model_manager = ModelManager()
    setup_dispatcher(dp, storage=storage, model_manager=model_manager)

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
        model_manager=model_manager,
    )


__all__ = [
    "bot",
    "create_bot",
    "create_bot_session",
    "dp",
    "main",
    "model_manager",
    "on_shutdown",
    "setup_dispatcher",
    "storage",
]

if __name__ == "__main__":
    asyncio.run(main())
