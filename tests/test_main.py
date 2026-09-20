from unittest.mock import AsyncMock, patch

import main


def test_main_invokes_bot_main() -> None:
    with patch("bot.main", new=AsyncMock()) as mock_bot_main:
        main.main()
        mock_bot_main.assert_called_once()
