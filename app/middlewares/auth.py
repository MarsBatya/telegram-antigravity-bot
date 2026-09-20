from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.core import config
from app.utils.bot_utils import is_authorized


class AuthMiddleware(BaseMiddleware):
    """Global authentication middleware checking incoming events
    against ALLOWED_USER_IDS.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        user_id = user.id
        user_name = user.username or user.first_name or "User"
        event_desc = (
            getattr(event, "text", None) or getattr(event, "data", None) or "<event>"
        )
        print(f"[RECV] From User ID: {user_id} (@{user_name}) - {event_desc}")

        if not config.ALLOWED_USER_IDS:
            if isinstance(event, Message):
                await event.answer(
                    f"👋 <b>Welcome to Antigravity AI Bot!</b>\n\n"
                    f"Your Telegram ID is: <code>{user_id}</code>\n\n"
                    f"⚠️ <b>Bot has not been configured with your ID yet.</b>\n"
                    f"Please open the <code>.env</code> file on the server and add:\n"
                    f"<code>ALLOWED_USER_IDS={user_id}</code>\n\n"
                    f"Then restart the bot.",
                    parse_mode="HTML",
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "⚠️ Bot has not been configured with your ID yet.",
                    show_alert=True,
                )
            return None

        if not is_authorized(user_id):
            print(
                f"[SECURITY ALERT] Unauthorized access attempt from User ID: {user_id}",
            )
            if isinstance(event, Message):
                await event.answer(
                    f"⛔ <b>Access Denied!</b>\nYour Telegram ID "
                    f"(<code>{user_id}</code>) is not listed in "
                    f"ALLOWED_USER_IDS in <code>.env</code>.",
                    parse_mode="HTML",
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "⛔ Access denied! Your ID is not registered.",
                    show_alert=True,
                )
            return None

        return await handler(event, data)
