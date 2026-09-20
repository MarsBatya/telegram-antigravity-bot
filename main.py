"""Antigravity AI Agent Telegram Bot - Entry Point.

This module provides a convenience entry point for launching the bot.
You can run the bot with either `python main.py` or `python bot.py`.
"""

import asyncio

import bot


def main() -> None:
    """Synchronous entry point that runs the bot async loop."""
    asyncio.run(bot.main())


if __name__ == "__main__":
    main()
