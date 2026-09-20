from datetime import datetime, timezone
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.core import config
from app.core.storage import SessionStorage
from app.handlers.explorer import _paginate_tree_entries
from app.middlewares.auth import AuthMiddleware
from app.ui.callbacks import (
    BrowseDirCallback,
    EffortCallback,
    FileInfoCallback,
    FileUploadCallback,
    ModeCallback,
    ModelCallback,
    SessionCallback,
    WorkspaceCallback,
)
from app.ui.keyboards import get_file_details_keyboard, get_tree_keyboard
from app.utils.bot_utils import (
    _chunk_text_safely,
    balance_html_chunks,
    format_file_size,
)
import bot


def make_mock_message(
    chat_id: int = 12345,
    user_id: int = 12345,
    text: str = "/start",
    caption: str | None = None,
) -> Message:
    user = User(id=user_id, is_bot=False, first_name="Test", username="testuser")
    chat = Chat(id=chat_id, type="private")
    msg = MagicMock(spec=Message)
    msg.message_id = 42
    msg.chat = chat
    msg.from_user = user
    msg.text = text
    msg.caption = caption
    msg.photo = None
    msg.document = None
    msg.reply = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def make_mock_callback(
    chat_id: int = 12345,
    user_id: int = 12345,
    data: str = "test_data",
) -> CallbackQuery:
    user = User(id=user_id, is_bot=False, first_name="Test", username="testuser")
    chat = Chat(id=chat_id, type="private")
    call = MagicMock(spec=CallbackQuery)
    call.id = "call-id-99"
    call.from_user = user
    call.data = data
    call.message = MagicMock(spec=Message)
    call.message.chat = chat
    call.message.message_id = 42
    call.message.edit_text = AsyncMock()
    call.answer = AsyncMock()
    return call


def test_path_mapper() -> None:
    pm = bot.PathMapper()
    p1 = pm.encode("/home/user/folder_a")
    p2 = pm.encode("/home/user/folder_b")
    assert p1 == "p1"
    assert p2 == "p2"

    # Same path returns same token
    assert pm.encode("/home/user/folder_a") == "p1"

    # Decode
    assert pm.decode("p1") == os.path.abspath("/home/user/folder_a")
    assert pm.decode("p2") == os.path.abspath("/home/user/folder_b")
    assert pm.decode("p999") is None


def test_make_progress_bar() -> None:
    assert bot.make_progress_bar(0, 10) == "[░░░░░░░░░░] 0.0%"
    assert bot.make_progress_bar(50, 10) == "[█████░░░░░] 50.0%"
    assert bot.make_progress_bar(100, 10) == "[██████████] 100.0%"


def test_is_authorized() -> None:
    with patch.object(config, "ALLOWED_USER_IDS", [12345, 67890]):
        assert bot.is_authorized(12345) is True
        assert bot.is_authorized(67890) is True
        assert bot.is_authorized(99999) is False

    with patch.object(config, "ALLOWED_USER_IDS", []):
        assert bot.is_authorized(12345) is False


async def test_auth_middleware_message() -> None:
    middleware = AuthMiddleware()
    next_handler = AsyncMock()

    # 1. ALLOWED_USER_IDS is empty -> guide message with ID
    with patch.object(config, "ALLOWED_USER_IDS", []):
        msg = make_mock_message(user_id=12345)
        await middleware(next_handler, msg, {"event_from_user": msg.from_user})
        next_handler.assert_not_called()
        msg.answer.assert_called_once()
        assert "Your Telegram ID is: <code>12345</code>" in msg.answer.call_args[0][0]

    # 2. Unauthorized user
    with patch.object(config, "ALLOWED_USER_IDS", [99999]):
        msg = make_mock_message(user_id=12345)
        await middleware(next_handler, msg, {"event_from_user": msg.from_user})
        next_handler.assert_not_called()
        assert "Access Denied" in msg.answer.call_args[0][0]

    # 3. Authorized user
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        msg = make_mock_message(user_id=12345)
        await middleware(next_handler, msg, {"event_from_user": msg.from_user})
        next_handler.assert_called_once_with(msg, {"event_from_user": msg.from_user})


async def test_auth_middleware_callback() -> None:
    middleware = AuthMiddleware()
    next_handler = AsyncMock()

    # 1. Unauthorized callback
    with patch.object(config, "ALLOWED_USER_IDS", [99999]):
        call = make_mock_callback(user_id=12345)
        await middleware(next_handler, call, {"event_from_user": call.from_user})
        next_handler.assert_not_called()
        call.answer.assert_called_once()
        assert "Access denied" in call.answer.call_args[0][0]

    # 2. Authorized callback
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        call = make_mock_callback(user_id=12345)
        await middleware(next_handler, call, {"event_from_user": call.from_user})
        next_handler.assert_called_once_with(
            call,
            {"event_from_user": call.from_user},
        )


async def test_send_long_message_short() -> None:
    mock_bot = AsyncMock(spec=Bot)
    await bot.send_long_message(mock_bot, 123, "short text")
    mock_bot.send_message.assert_called_once_with(
        123,
        "short text",
        parse_mode="HTML",
        reply_markup=None,
    )


async def test_send_long_message_empty() -> None:
    mock_bot = AsyncMock(spec=Bot)
    await bot.send_long_message(mock_bot, 123, "")
    await bot.send_long_message(mock_bot, 123, "   ")
    mock_bot.send_message.assert_not_called()


async def test_send_long_message_split_and_fallback() -> None:
    lines = ["Line " + str(i) + " " + "x" * 100 for i in range(50)]
    long_text = "\n".join(lines)
    assert len(long_text) > 3800

    mock_bot = AsyncMock(spec=Bot)
    with patch("asyncio.sleep", new=AsyncMock()):
        await bot.send_long_message(mock_bot, 123, long_text)
        assert mock_bot.send_message.call_count > 1

    # HTML fallback to plain text on exception
    mock_bot_err = AsyncMock(spec=Bot)
    mock_bot_err.send_message.side_effect = [
        Exception("HTML parse error"),
        MagicMock(),
    ]
    await bot.send_long_message(mock_bot_err, 123, "<b>invalid text")
    assert mock_bot_err.send_message.call_count == 2
    assert mock_bot_err.send_message.call_args_list[1][1]["parse_mode"] is None


async def test_reply_safe() -> None:
    mock_bot = AsyncMock(spec=Bot)
    msg = make_mock_message()

    # Success reply
    await bot.reply_safe(mock_bot, msg, "hello")
    msg.reply.assert_called_once()

    # Fallback to send_message when reply fails
    msg.reply.side_effect = Exception("msg deleted")
    await bot.reply_safe(mock_bot, msg, "hello")
    mock_bot.send_message.assert_called_once()
    assert mock_bot.send_message.call_args[0] == (msg.chat.id, "hello")
    assert "reply_markup" in mock_bot.send_message.call_args[1]


async def test_register_telegram_commands() -> None:
    mock_bot = AsyncMock(spec=Bot)
    success = await bot.register_telegram_commands(mock_bot)
    assert success is True
    mock_bot.set_my_commands.assert_called_once()
    commands = mock_bot.set_my_commands.call_args[0][0]
    assert len(commands) == 18

    # When set_my_commands raises
    mock_bot.set_my_commands.side_effect = Exception("Telegram API error")
    assert await bot.register_telegram_commands(mock_bot) is False


async def test_command_start_and_help(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    msg = make_mock_message(user_id=12345, text="/start")
    with patch("app.handlers.commands.reply_safe", new=AsyncMock()) as mock_reply:
        await bot.send_welcome(msg, mock_bot, session_storage=storage)
        mock_reply.assert_called_once()
        reply_text = mock_reply.call_args[0][2]
        assert "Antigravity AI Agent Bot" in reply_text
        assert "Core Engine Commands" in reply_text


async def test_command_model_picker_and_callback(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    msg = make_mock_message(user_id=12345, text="/model")
    with patch("app.handlers.settings.reply_safe", new=AsyncMock()) as mock_reply:
        await bot.show_model_picker(msg, mock_bot, session_storage=storage)
        mock_reply.assert_called_once()
        text = mock_reply.call_args[0][2]
        assert "Antigravity AI Model Selector" in text

    # Set model callback
    call = make_mock_callback(user_id=12345)
    cb_data = ModelCallback(model_id="claude-sonnet-4-6")
    await bot.handle_set_model_callback(call, cb_data, session_storage=storage)
    call.message.edit_text.assert_called_once()
    assert "claude-sonnet-4-6" in call.message.edit_text.call_args[0][0]
    assert storage.get_setting(12345, "model") == "claude-sonnet-4-6"


async def test_command_effort_picker_and_callback(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    msg = make_mock_message(user_id=12345, text="/effort")
    with patch("app.handlers.settings.reply_safe", new=AsyncMock()) as mock_reply:
        await bot.show_effort_picker(msg, mock_bot, session_storage=storage)
        mock_reply.assert_called_once()
        assert "Antigravity Reasoning Effort Level" in mock_reply.call_args[0][2]

    # Set effort callback
    call = make_mock_callback(user_id=12345)
    cb_data = EffortCallback(level="medium")
    await bot.handle_set_effort_callback(call, cb_data, session_storage=storage)
    call.message.edit_text.assert_called_once()
    assert "MEDIUM" in call.message.edit_text.call_args[0][0]
    assert storage.get_setting(12345, "effort") == "medium"


async def test_command_mode_picker_and_callback(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    msg = make_mock_message(user_id=12345, text="/mode")
    with patch("app.handlers.settings.reply_safe", new=AsyncMock()) as mock_reply:
        await bot.show_mode_picker(msg, mock_bot, session_storage=storage)
        mock_reply.assert_called_once()
        assert "Antigravity Agent Execution Mode" in mock_reply.call_args[0][2]

    # Set mode callback
    call = make_mock_callback(user_id=12345)
    cb_data = ModeCallback(mode="plan")
    await bot.handle_set_mode_callback(call, cb_data, session_storage=storage)
    call.message.edit_text.assert_called_once()
    assert "plan" in call.message.edit_text.call_args[0][0]
    assert storage.get_setting(12345, "mode") == "plan"


async def test_command_workspace_and_callback(
    tmp_path: Path,
    storage: SessionStorage,
) -> None:
    mock_bot = AsyncMock(spec=Bot)
    # /workspace with argument
    new_dir = str(tmp_path / "project-x")
    with patch("app.handlers.explorer.reply_safe", new=AsyncMock()) as mock_reply:
        msg = make_mock_message(user_id=12345, text=f"/workspace {new_dir}")
        await bot.change_workspace(msg, mock_bot, session_storage=storage)
        mock_reply.assert_called_once()
        assert new_dir in mock_reply.call_args[0][2]
        assert storage.get_workspace(
            12345,
        ) == os.path.abspath(
            new_dir,
        )

    # /workspace without argument shows picker
    with patch("app.handlers.explorer.reply_safe", new=AsyncMock()) as mock_reply:
        msg = make_mock_message(user_id=12345, text="/workspace")
        await bot.change_workspace(msg, mock_bot, session_storage=storage)
        mock_reply.assert_called_once()
        assert "Interactive Workspace Picker" in mock_reply.call_args[0][2]

    # set_ws callback
    token = bot.path_mapper.encode(new_dir)
    call = make_mock_callback(user_id=12345)
    cb_data = WorkspaceCallback(token=token)
    await bot.handle_set_ws_callback(call, cb_data, session_storage=storage)
    call.answer.assert_called_once_with("Workspace synced to AI!")
    call.message.edit_text.assert_called_once()
    assert "AI Workspace Successfully Changed" in call.message.edit_text.call_args[0][0]


async def test_command_tree_explorer(tmp_path: Path, storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    sub = tmp_path / "subdir"
    sub.mkdir()
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("hello world")

    storage.set_workspace(12345, str(tmp_path))
    with patch(
        "app.handlers.explorer.reply_safe",
        new=AsyncMock(),
    ) as mock_reply:
        msg = make_mock_message(user_id=12345, text="/tree")
        await bot.show_tree_explorer(msg, mock_bot, session_storage=storage)
        mock_reply.assert_called_once()
        text = mock_reply.call_args[0][2]
        assert "Interactive File Explorer" in text


async def test_command_cancel_and_stop(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    with patch.object(storage, "cancel_chat_process", return_value=True):
        with patch("app.handlers.commands.reply_safe", new=AsyncMock()) as mock_reply:
            msg = make_mock_message(user_id=12345, text="/stop")
            await bot.handle_cancel_command(msg, mock_bot, session_storage=storage)
            mock_reply.assert_called_once()
            assert "Successfully Cancelled" in mock_reply.call_args[0][2]

    with patch.object(storage, "cancel_chat_process", return_value=False):
        with patch("app.handlers.commands.reply_safe", new=AsyncMock()) as mock_reply:
            msg = make_mock_message(user_id=12345, text="/cancel")
            await bot.handle_cancel_command(msg, mock_bot, session_storage=storage)
            mock_reply.assert_called_once()
            assert (
                "No AI execution process is currently running"
                in mock_reply.call_args[0][2]
            )


async def test_command_logs() -> None:
    mock_bot = AsyncMock(spec=Bot)
    with patch.object(
        bot.agent_runner,
        "fetch_bot_logs",
        return_value="log line 1\nlog line 2",
    ):
        with patch(
            "app.handlers.commands.send_long_message",
            new=AsyncMock(),
        ) as mock_send:
            msg = make_mock_message(user_id=12345, text="/logs")
            await bot.show_bot_logs(msg, mock_bot)
            mock_send.assert_called_once()
            assert "Recent Bot Service Activity Logs" in mock_send.call_args[0][2]


async def test_command_status_and_usage(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    with patch("app.handlers.commands.reply_safe", new=AsyncMock()) as mock_reply:
        msg = make_mock_message(user_id=12345, text="/status")
        await bot.send_status(msg, mock_bot, session_storage=storage)
        mock_reply.assert_called_once()
        assert "Server & AI Engine Status" in mock_reply.call_args[0][2]

    with patch.object(
        bot.agent_runner,
        "fetch_live_user_quota_summary",
        return_value="Quota Info",
    ):
        with patch(
            "app.handlers.commands.reply_safe",
            new=AsyncMock(),
        ) as mock_reply:
            msg = make_mock_message(user_id=12345, text="/usage")
            await bot.send_usage(msg, mock_bot, session_storage=storage)
            mock_reply.assert_called_once()
            assert "Active Conversation Session Capacity" in mock_reply.call_args[0][2]


async def test_command_new_session(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    with patch.object(storage, "reset_session") as mock_reset:
        with patch("app.handlers.sessions.reply_safe", new=AsyncMock()) as mock_reply:
            msg = make_mock_message(user_id=12345, text="/new")
            await bot.reset_conversation(msg, mock_bot, session_storage=storage)
            mock_reset.assert_called_once_with(12345)
            mock_reply.assert_called_once()
            assert "successfully reset" in mock_reply.call_args[0][2]


async def test_command_rename_session(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    # No title given
    with patch("app.handlers.sessions.reply_safe", new=AsyncMock()) as mock_reply:
        msg = make_mock_message(user_id=12345, text="/rename")
        await bot.rename_session_command(msg, mock_bot, session_storage=storage)
        assert "Usage:" in mock_reply.call_args[0][2]

    # No active session
    with patch("app.handlers.sessions.reply_safe", new=AsyncMock()) as mock_reply:
        msg = make_mock_message(user_id=12345, text="/rename Project Alpha")
        await bot.rename_session_command(msg, mock_bot, session_storage=storage)
        assert "No active conversation session" in mock_reply.call_args[0][2]

    # Success rename
    storage.set_active_session(12345, "conv-xyz")
    with patch.object(bot.agent_runner, "rename_session", return_value=True):
        with patch("app.handlers.sessions.reply_safe", new=AsyncMock()) as mock_reply:
            msg = make_mock_message(user_id=12345, text="/rename Project Alpha")
            await bot.rename_session_command(msg, mock_bot, session_storage=storage)
            assert "Session Name Successfully Changed" in mock_reply.call_args[0][2]


async def test_command_smash_goal_plan(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    # Smash with arg
    with patch(
        "app.handlers.agent.process_custom_agent_prompt",
        new=AsyncMock(),
    ) as mock_proc:
        msg = make_mock_message(user_id=12345, text="/smash Fix all lints")
        await bot.execute_smash(msg, mock_bot, session_storage=storage)
        mock_proc.assert_called_once()
        assert "Fix all lints" in mock_proc.call_args[1]["prompt"]
        assert mock_proc.call_args[1]["session_storage"] is storage

    # Goal with arg
    with patch(
        "app.handlers.agent.process_agent_prompt",
        new=AsyncMock(),
    ) as mock_proc:
        msg = make_mock_message(user_id=12345, text="/goal Complete project")
        await bot.execute_goal(msg, mock_bot, session_storage=storage)
        mock_proc.assert_called_once()
        assert "Goal: Complete project" in mock_proc.call_args[0][2]
        assert mock_proc.call_args[1]["session_storage"] is storage

    # Plan with arg
    with patch(
        "app.handlers.agent.process_agent_prompt",
        new=AsyncMock(),
    ) as mock_proc:
        msg = make_mock_message(user_id=12345, text="/plan Database migration")
        await bot.execute_plan(msg, mock_bot, session_storage=storage)
        mock_proc.assert_called_once()
        assert "Database migration" in mock_proc.call_args[0][2]
        assert mock_proc.call_args[1]["session_storage"] is storage


async def test_handle_text_prompt(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    with patch(
        "app.handlers.agent.process_agent_prompt",
        new=AsyncMock(),
    ) as mock_proc:
        msg = make_mock_message(
            user_id=12345,
            text="Refactor the authentication module",
        )
        await bot.handle_text_prompt(msg, mock_bot, session_storage=storage)
        mock_proc.assert_called_once_with(
            mock_bot,
            msg,
            "Refactor the authentication module",
            session_storage=storage,
        )

    # Empty text does nothing
    with patch(
        "app.handlers.agent.process_agent_prompt",
        new=AsyncMock(),
    ) as mock_proc:
        msg_empty = make_mock_message(user_id=12345, text="   ")
        await bot.handle_text_prompt(msg_empty, mock_bot, session_storage=storage)
        mock_proc.assert_not_called()


async def test_execute_resume(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    # Without prompt -> shows picker
    with patch(
        "app.handlers.sessions.show_session_picker_message",
        new=AsyncMock(),
    ) as mock_picker:
        msg = make_mock_message(user_id=12345, text="/resume")
        await bot.execute_resume(msg, mock_bot, session_storage=storage)
        mock_picker.assert_called_once_with(msg, mock_bot, session_storage=storage)

    # With prompt -> resumes session
    with patch(
        "app.handlers.agent.process_custom_agent_prompt",
        new=AsyncMock(),
    ) as mock_custom:
        msg = make_mock_message(
            user_id=12345,
            text="/resume Continue building UI",
        )
        await bot.execute_resume(msg, mock_bot, session_storage=storage)
        mock_custom.assert_called_once()
        assert mock_custom.call_args[1]["prompt"] == "Continue building UI"
        assert mock_custom.call_args[1]["session_storage"] is storage


async def test_show_session_picker_and_history(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    # No sessions found
    with patch.object(bot.agent_runner, "get_recent_sessions", return_value=[]):
        with patch("app.handlers.sessions.reply_safe", new=AsyncMock()) as mock_reply:
            msg = make_mock_message(user_id=12345)
            await bot.show_session_picker_message(
                msg,
                mock_bot,
                session_storage=storage,
            )
            assert "No conversation session history" in mock_reply.call_args[0][2]

    # Populated sessions
    sessions = [{"id": "s1", "title": "Session 1", "date": "10 Mar 12:00"}]
    with patch.object(
        bot.agent_runner,
        "get_recent_sessions",
        return_value=sessions,
    ):
        with patch("app.handlers.sessions.reply_safe", new=AsyncMock()) as mock_reply:
            msg = make_mock_message(user_id=12345)
            await bot.show_session_picker_message(
                msg,
                mock_bot,
                session_storage=storage,
            )
            assert "Select / Resume Conversation Session" in mock_reply.call_args[0][2]


async def test_handle_session_selection(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    # Select "new"
    with patch.object(storage, "reset_session") as mock_reset:
        call = make_mock_callback(user_id=12345)
        cb_data = SessionCallback(action="new", session_id="new")
        await bot.handle_session_callback(
            call,
            cb_data,
            mock_bot,
            session_storage=storage,
        )
        mock_reset.assert_called_once_with(12345)
        call.answer.assert_called_once_with("Starting new session.")
        assert (
            "New Conversation Session Started" in call.message.edit_text.call_args[0][0]
        )

    # Select existing session
    with patch.object(storage, "set_active_session") as mock_set:
        with patch(
            "app.handlers.sessions.show_session_history_card",
            new=AsyncMock(),
        ) as mock_card:
            call = make_mock_callback(user_id=12345)
            cb_data = SessionCallback(action="select", session_id="conv-101")
            await bot.handle_session_callback(
                call,
                cb_data,
                mock_bot,
                session_storage=storage,
            )
            mock_set.assert_called_once_with(12345, "conv-101")
            call.answer.assert_called_once_with("Loading session history...")
            mock_card.assert_called_once()


async def test_show_session_history_card() -> None:
    mock_bot = AsyncMock(spec=Bot)
    turns = [{"user": "Hello", "ai": "Hi there!"}]
    with patch.object(
        bot.agent_runner,
        "get_full_session_history_formatted",
        return_value=turns,
    ):
        with patch(
            "app.handlers.sessions.send_long_message",
            new=AsyncMock(),
        ) as mock_send:
            with patch("asyncio.sleep", new=AsyncMock()):
                await bot.show_session_history_card(mock_bot, 12345, "conv-101")
                # Header, Turn, Footer
                assert mock_send.call_count >= 3


async def test_delete_session_command_and_callback(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    # Delete command with sessions
    sessions = [{"id": "s1", "title": "Session 1", "date": "10 Mar"}]
    with patch.object(
        bot.agent_runner,
        "get_recent_sessions",
        return_value=sessions,
    ):
        with patch("app.handlers.sessions.reply_safe", new=AsyncMock()) as mock_reply:
            msg = make_mock_message(user_id=12345, text="/delete")
            await bot.delete_session_command(msg, mock_bot)
            assert "Delete Conversation Session" in mock_reply.call_args[0][2]

    # Delete callback
    storage.set_active_session(12345, "s1")
    with patch.object(bot.agent_runner, "delete_session", return_value=True):
        with patch.object(storage, "reset_session") as mock_reset:
            call = make_mock_callback(user_id=12345)
            cb_data = SessionCallback(action="delete", session_id="s1")
            await bot.handle_session_callback(
                call,
                cb_data,
                mock_bot,
                session_storage=storage,
            )
            mock_reset.assert_called_once_with(12345)
            call.answer.assert_called_once_with("Session deleted successfully.")
            assert "Deleted Successfully" in call.message.edit_text.call_args[0][0]


async def test_handle_media_prompt(tmp_path: Path, storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    with patch.object(config, "TEMP_UPLOAD_DIR", str(tmp_path)):
        msg_photo = make_mock_message(user_id=12345, caption="Explain this diagram")
        photo_size = MagicMock()
        photo_size.file_id = "photo_123"
        msg_photo.photo = [photo_size]

        file_info = MagicMock()
        file_info.file_path = "photos/file_0.jpg"

        mock_bot.get_file.return_value = file_info
        mock_bot.download_file = AsyncMock()

        with patch(
            "app.handlers.agent.process_agent_prompt",
            new=AsyncMock(),
        ) as mock_proc:
            await bot.handle_media_prompt(msg_photo, mock_bot, session_storage=storage)
            mock_proc.assert_called_once()
            prompt_arg = mock_proc.call_args[0][2]
            assert "File uploaded at" in prompt_arg
            assert "Explain this diagram" in prompt_arg
            assert mock_proc.call_args[1]["session_storage"] is storage


async def test_additional_callbacks(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    # quota_info
    call = make_mock_callback(user_id=12345)
    with patch("app.handlers.commands.send_usage", new=AsyncMock()) as mock_usage:
        await bot.handle_quota_info_callback(call, mock_bot, session_storage=storage)
        call.answer.assert_called_once()
        mock_usage.assert_called_once_with(
            call.message,
            mock_bot,
            session_storage=storage,
        )

    # tree_explorer
    call_tree = make_mock_callback(user_id=12345)
    with patch(
        "app.handlers.explorer.render_file_explorer_callback",
        new=AsyncMock(),
    ) as mock_tree:
        await bot.handle_nav_tree(call_tree, session_storage=storage)
        mock_tree.assert_called_once()

    # cancel_execution callback
    call_cancel = make_mock_callback(user_id=12345)
    with patch.object(storage, "cancel_chat_process", return_value=True):
        await bot.handle_cancel_callback(call_cancel, session_storage=storage)
        call_cancel.answer.assert_called_once_with("Process cancelled!")
        assert (
            "Execution Cancelled by User"
            in call_cancel.message.edit_text.call_args[0][0]
        )

    # open_effort_menu
    call_effort = make_mock_callback(user_id=12345)
    await bot.handle_open_effort_menu(call_effort, session_storage=storage)
    call_effort.message.edit_text.assert_called_once()
    assert (
        "Antigravity Reasoning Effort Level"
        in call_effort.message.edit_text.call_args[0][0]
    )

    # browse_dir callback
    call_dir = make_mock_callback(user_id=12345)
    token = bot.path_mapper.encode("/root/my-project")
    cb_dir = BrowseDirCallback(token=token)
    with patch(
        "app.handlers.explorer.render_file_explorer_callback",
        new=AsyncMock(),
    ) as mock_tree:
        await bot.handle_browse_dir_callback(call_dir, cb_dir, session_storage=storage)
        mock_tree.assert_called_once()


def test_chunk_text_safely_oversized_line() -> None:
    giant_line = "A" * 9000
    chunks = _chunk_text_safely(giant_line, max_length=3800)
    assert len(chunks) == 3
    assert len(chunks[0]) == 3800
    assert len(chunks[1]) == 3800
    assert len(chunks[2]) == 1400
    assert "".join(chunks) == giant_line


def test_balance_html_chunks() -> None:
    raw_chunks = [
        "<pre><code>line 1",
        "line 2</code></pre>",
    ]
    balanced = balance_html_chunks(raw_chunks)
    assert len(balanced) == 2
    assert balanced[0] == "<pre><code>line 1</code></pre>"
    assert balanced[1] == "<pre><code>line 2</code></pre>"


async def test_send_long_message_unbroken_giant_line() -> None:
    mock_bot = AsyncMock(spec=Bot)
    giant_line = "X" * 10000

    await bot.send_long_message(mock_bot, 123, giant_line)
    assert mock_bot.send_message.call_count == 3
    for call in mock_bot.send_message.call_args_list:
        chunk_sent = call[0][1]
        assert len(chunk_sent) <= 3800


async def test_on_shutdown(storage: SessionStorage) -> None:
    with (
        patch.object(storage, "cleanup_all_active_processes") as mock_cleanup,
        patch.object(bot.bot.session, "close", new=AsyncMock()) as mock_close,
    ):
        await bot.on_shutdown(session_storage=storage)
        mock_cleanup.assert_called_once()
        mock_close.assert_called_once()


def test_mask_proxy_url() -> None:
    assert bot.mask_proxy_url(None) == ""
    assert bot.mask_proxy_url("") == ""
    assert bot.mask_proxy_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert (
        bot.mask_proxy_url("http://admin:secret123@proxy.example.com:8080")
        == "http://admin:***@proxy.example.com:8080"
    )
    assert (
        bot.mask_proxy_url("socks5://user:pass@127.0.0.1:1080")
        == "socks5://user:***@127.0.0.1:1080"
    )


def test_create_bot_session_explicit_proxy() -> None:
    session = bot.create_bot_session("http://127.0.0.1:8080")
    assert session is not None
    assert session.proxy == "http://127.0.0.1:8080"


def test_create_bot_session_empty_proxy() -> None:
    session = bot.create_bot_session("")
    assert session is None


def test_create_bot_session_from_env() -> None:
    with patch("app.core.config.get_http_proxy", return_value="http://10.0.0.1:8080"):
        session = bot.create_bot_session()
        assert session is not None
        assert session.proxy == "http://10.0.0.1:8080"

    with patch("app.core.config.get_http_proxy", return_value=None):
        session = bot.create_bot_session()
        assert session is None


def test_create_bot_with_proxy() -> None:
    custom_bot = bot.create_bot(
        token="123456:TEST_TOKEN",  # noqa: S106
        proxy="http://192.168.1.1:8080",
    )
    assert custom_bot.token == "123456:TEST_TOKEN"  # noqa: S105
    assert getattr(custom_bot.session, "proxy", None) == "http://192.168.1.1:8080"


def test_create_bot_without_proxy() -> None:
    with patch("app.core.config.get_http_proxy", return_value=None):
        custom_bot = bot.create_bot(
            token="123456:TEST_TOKEN",  # noqa: S106
            proxy=None,
        )
        assert getattr(custom_bot.session, "proxy", None) is None


async def test_command_status_displays_proxy(storage: SessionStorage) -> None:
    mock_bot = AsyncMock(spec=Bot)
    mock_session = MagicMock()
    mock_session.proxy = "http://user:secret@127.0.0.1:8080"
    mock_bot.session = mock_session

    with patch("app.handlers.commands.reply_safe", new=AsyncMock()) as mock_reply:
        msg = make_mock_message(user_id=12345, text="/status")
        await bot.send_status(msg, mock_bot, session_storage=storage)
        mock_reply.assert_called_once()
        status_text = mock_reply.call_args[0][2]
        assert "Telegram Proxy:" in status_text
        assert "http://user:***@127.0.0.1:8080" in status_text


def test_format_file_size() -> None:
    assert format_file_size(500) == "500 B"
    assert format_file_size(1024) == "1.0 KB"
    assert format_file_size(1536) == "1.5 KB"
    assert format_file_size(1024 * 1024) == "1.0 MB"
    assert format_file_size(2.5 * 1024 * 1024) == "2.5 MB"
    assert format_file_size(1024 * 1024 * 1024) == "1.0 GB"


def test_paginate_tree_entries() -> None:
    dirs = [f"dir_{i}" for i in range(12)]
    files = [(f"file_{i}.txt", 1.0) for i in range(15)]
    # Total = 27 items, page size = 10 -> 3 pages
    p1_dirs, p1_files, p1, total_pages, total_items = _paginate_tree_entries(
        dirs,
        files,
        page=1,
        page_size=10,
    )
    assert total_pages == 3
    assert total_items == 27
    assert p1 == 1
    assert len(p1_dirs) == 10
    assert len(p1_files) == 0

    p2_dirs, p2_files, p2, _, _ = _paginate_tree_entries(
        dirs,
        files,
        page=2,
        page_size=10,
    )
    assert p2 == 2
    assert len(p2_dirs) == 2
    assert len(p2_files) == 8

    p3_dirs, p3_files, p3, _, _ = _paginate_tree_entries(
        dirs,
        files,
        page=3,
        page_size=10,
    )
    assert p3 == 3
    assert len(p3_dirs) == 0
    assert len(p3_files) == 7

    # Clamping out-of-range page numbers
    _, _, p_neg, _, _ = _paginate_tree_entries(dirs, files, page=-1, page_size=10)
    assert p_neg == 1

    _, _, p_large, _, _ = _paginate_tree_entries(dirs, files, page=999, page_size=10)
    assert p_large == 3


def test_get_tree_keyboard_pagination() -> None:
    norm_path = "/home/test/project"
    cur_ws = "/home/test/project"
    dirs = ["subdir1"]
    files = [("file1.txt", 2.5)]

    # Single page -> no pagination row
    kb_single = get_tree_keyboard(
        norm_path,
        cur_ws,
        dirs,
        files,
        bot.path_mapper.encode,
        page=1,
        total_pages=1,
    )
    all_buttons = [btn for row in kb_single.inline_keyboard for btn in row]
    assert not any("Next ➡️" in btn.text for btn in all_buttons)
    assert not any("⬅️ Prev" in btn.text for btn in all_buttons)

    # Multi page (Page 1 of 3) -> has Next and Page info, no Prev
    kb_p1 = get_tree_keyboard(
        norm_path,
        cur_ws,
        dirs,
        files,
        bot.path_mapper.encode,
        page=1,
        total_pages=3,
    )
    buttons_p1 = [btn for row in kb_p1.inline_keyboard for btn in row]
    assert any("Next ➡️" in btn.text for btn in buttons_p1)
    assert not any("⬅️ Prev" in btn.text for btn in buttons_p1)
    assert any("📄 1/3" in btn.text for btn in buttons_p1)

    # Multi page (Page 2 of 3) -> has Prev, Next, and Page info
    kb_p2 = get_tree_keyboard(
        norm_path,
        cur_ws,
        dirs,
        files,
        bot.path_mapper.encode,
        page=2,
        total_pages=3,
    )
    buttons_p2 = [btn for row in kb_p2.inline_keyboard for btn in row]
    assert any("Next ➡️" in btn.text for btn in buttons_p2)
    assert any("⬅️ Prev" in btn.text for btn in buttons_p2)
    assert any("📄 2/3" in btn.text for btn in buttons_p2)

    # Multi page (Page 3 of 3) -> has Prev and Page info, no Next
    kb_p3 = get_tree_keyboard(
        norm_path,
        cur_ws,
        dirs,
        files,
        bot.path_mapper.encode,
        page=3,
        total_pages=3,
    )
    buttons_p3 = [btn for row in kb_p3.inline_keyboard for btn in row]
    assert not any("Next ➡️" in btn.text for btn in buttons_p3)
    assert any("⬅️ Prev" in btn.text for btn in buttons_p3)
    assert any("📄 3/3" in btn.text for btn in buttons_p3)


def test_get_file_details_keyboard() -> None:
    kb = get_file_details_keyboard(
        file_token="p1",  # noqa: S106
        dir_token="p2",  # noqa: S106
        page=2,
        can_upload=True,
    )
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert any("Upload to Chat" in btn.text for btn in buttons)
    assert any("Back to Files" in btn.text for btn in buttons)

    kb_uploaded = get_file_details_keyboard(
        file_token="p1",  # noqa: S106
        dir_token="p2",  # noqa: S106
        page=2,
        can_upload=True,
        uploaded=True,
    )
    buttons_up = [btn for row in kb_uploaded.inline_keyboard for btn in row]
    assert any("Upload Again" in btn.text for btn in buttons_up)


async def test_handle_file_info_callback(tmp_path: Path) -> None:
    # 1. Valid file
    test_file = tmp_path / "hello.py"
    test_file.write_text("print('hello world')\n")
    token = bot.path_mapper.encode(str(test_file))

    call = make_mock_callback(user_id=12345)
    cb_data = FileInfoCallback(token=token, page=2)
    await bot.handle_file_info_callback(call, cb_data)
    call.message.edit_text.assert_called_once()
    text = call.message.edit_text.call_args[0][0]
    assert "File Information" in text
    assert "hello.py" in text
    assert "Size:" in text
    markup = call.message.edit_text.call_args[1]["reply_markup"]
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any("Upload to Chat" in btn.text for btn in buttons)
    assert any("Back to Files" in btn.text for btn in buttons)

    # 2. File not found
    call_missing = make_mock_callback(user_id=12345)
    missing_token = bot.path_mapper.encode(str(tmp_path / "nonexistent.txt"))
    await bot.handle_file_info_callback(
        call_missing,
        FileInfoCallback(token=missing_token, page=1),
    )
    call_missing.answer.assert_called_once_with(
        "File not found or moved!",
        show_alert=True,
    )

    # 3. Empty file (0 bytes)
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("")
    empty_token = bot.path_mapper.encode(str(empty_file))
    call_empty = make_mock_callback(user_id=12345)
    await bot.handle_file_info_callback(
        call_empty,
        FileInfoCallback(token=empty_token, page=1),
    )
    call_empty.message.edit_text.assert_called_once()
    assert "File is empty" in call_empty.message.edit_text.call_args[0][0]
    empty_markup = call_empty.message.edit_text.call_args[1]["reply_markup"]
    empty_buttons = [btn for row in empty_markup.inline_keyboard for btn in row]
    assert not any("Upload to Chat" in btn.text for btn in empty_buttons)

    # 4. Oversized file (> 50MB)
    call_oversized = make_mock_callback(user_id=12345)
    with patch("os.path.getsize", return_value=51 * 1024 * 1024):
        await bot.handle_file_info_callback(
            call_oversized,
            FileInfoCallback(token=token, page=1),
        )
        oversized_text = call_oversized.message.edit_text.call_args[0][0]
        assert "exceeds Telegram's 50MB" in oversized_text


async def test_handle_file_upload_callback(tmp_path: Path) -> None:
    mock_bot = AsyncMock(spec=Bot)
    # 1. Successful document upload
    sample_file = tmp_path / "script.py"
    sample_file.write_text("a = 10\n")
    token = bot.path_mapper.encode(str(sample_file))

    call = make_mock_callback(user_id=12345)
    cb_data = FileUploadCallback(token=token, page=1)
    await bot.handle_file_upload_callback(call, cb_data, mock_bot)

    mock_bot.send_document.assert_called_once()
    assert mock_bot.send_document.call_args.kwargs["chat_id"] == call.message.chat.id
    assert "script.py" in mock_bot.send_document.call_args.kwargs["caption"]
    call.message.edit_text.assert_called_once()
    assert "Successfully Uploaded" in call.message.edit_text.call_args[0][0]

    # 2. Successful photo upload for images
    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\nfakeimage")
    img_token = bot.path_mapper.encode(str(image_file))
    call_img = make_mock_callback(user_id=12345)
    await bot.handle_file_upload_callback(
        call_img,
        FileUploadCallback(token=img_token, page=1),
        mock_bot,
    )
    mock_bot.send_photo.assert_called_once()
    assert "image.png" in mock_bot.send_photo.call_args.kwargs["caption"]

    # 3. Photo upload fallback to document if send_photo raises
    mock_bot.send_photo.side_effect = Exception("Invalid photo dimensions")
    call_img_fallback = make_mock_callback(user_id=12345)
    mock_bot.send_document.reset_mock()
    await bot.handle_file_upload_callback(
        call_img_fallback,
        FileUploadCallback(token=img_token, page=1),
        mock_bot,
    )
    mock_bot.send_document.assert_called_once()

    # 4. Missing file
    missing_token = bot.path_mapper.encode(str(tmp_path / "gone.txt"))
    call_missing = make_mock_callback(user_id=12345)
    await bot.handle_file_upload_callback(
        call_missing,
        FileUploadCallback(token=missing_token, page=1),
        mock_bot,
    )
    call_missing.answer.assert_called_once_with(
        "File not found or cannot be read!",
        show_alert=True,
    )

    # 5. Empty file (0 bytes)
    empty_file = tmp_path / "zero.txt"
    empty_file.write_text("")
    zero_token = bot.path_mapper.encode(str(empty_file))
    call_zero = make_mock_callback(user_id=12345)
    await bot.handle_file_upload_callback(
        call_zero,
        FileUploadCallback(token=zero_token, page=1),
        mock_bot,
    )
    assert "File is empty (0 bytes)" in call_zero.answer.call_args[0][0]

    # 6. File > 50MB
    call_huge = make_mock_callback(user_id=12345)
    with patch("os.path.getsize", return_value=60 * 1024 * 1024):
        await bot.handle_file_upload_callback(
            call_huge,
            FileUploadCallback(token=token, page=1),
            mock_bot,
        )
        assert "50MB" in call_huge.answer.call_args[0][0]

    # 7. Upload failure exception handling
    mock_bot.send_document.side_effect = Exception("Telegram API timeout")
    call_err = make_mock_callback(user_id=12345)
    await bot.handle_file_upload_callback(
        call_err,
        FileUploadCallback(token=token, page=1),
        mock_bot,
    )
    assert "Failed to upload" in call_err.answer.call_args_list[-1][0][0]


async def test_main_startup() -> None:
    with (
        patch.object(config, "BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"),
        patch.object(config, "ALLOWED_USER_IDS", [12345]),
        patch.object(bot.dp, "start_polling", new=AsyncMock()) as mock_poll,
        patch.object(bot.bot, "delete_webhook", new=AsyncMock()),
        patch("bot.register_telegram_commands", new=AsyncMock()),
    ):
        await bot.main()
        mock_poll.assert_called_once()
        assert "session_storage" in mock_poll.call_args.kwargs


async def test_dispatcher_workflow_injection(storage: SessionStorage) -> None:
    test_bot = bot.create_bot("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    now = datetime.now(timezone.utc)
    msg = Message(
        message_id=42,
        date=now,
        chat=Chat(id=12345, type="private"),
        from_user=User(id=12345, is_bot=False, first_name="Test", username="testuser"),
        text="/start",
    )
    update = Update(update_id=1, message=msg)
    try:
        with (
            patch.object(config, "ALLOWED_USER_IDS", [12345]),
            patch("app.handlers.commands.reply_safe", new=AsyncMock()) as mock_reply,
        ):
            await bot.dp.feed_update(
                bot=test_bot,
                update=update,
                session_storage=storage,
            )
            mock_reply.assert_called_once()
            assert mock_reply.call_args[0][0] == test_bot
            assert mock_reply.call_args[0][1].text == "/start"
    finally:
        await test_bot.session.close()
