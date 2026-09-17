import os
from unittest.mock import MagicMock, patch

import telebot

import bot
import config
from bot import PathMapper, is_authorized, make_progress_bar


def make_mock_message(chat_id=12345, user_id=12345, text="/start", caption=None):
    msg = MagicMock(spec=telebot.types.Message)
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.username = "testuser"
    msg.from_user.first_name = "Test"
    msg.text = text
    msg.caption = caption
    msg.photo = None
    msg.document = None
    return msg


def make_mock_callback(chat_id=12345, user_id=12345, data="test_data"):
    call = MagicMock(spec=telebot.types.CallbackQuery)
    call.id = "call-id-99"
    call.from_user = MagicMock()
    call.from_user.id = user_id
    call.from_user.username = "testuser"
    call.message = MagicMock()
    call.message.chat.id = chat_id
    call.message.message_id = 42
    call.data = data
    return call


def test_path_mapper():
    pm = PathMapper()
    p1 = pm.encode("/tmp/folder_a")
    p2 = pm.encode("/tmp/folder_b")
    assert p1 == "p1"
    assert p2 == "p2"

    # Same path returns same token
    assert pm.encode("/tmp/folder_a") == "p1"

    # Decode
    assert pm.decode("p1") == os.path.abspath("/tmp/folder_a")
    assert pm.decode("p2") == os.path.abspath("/tmp/folder_b")
    assert pm.decode("p999") is None


def test_make_progress_bar():
    assert make_progress_bar(0, 10) == "[░░░░░░░░░░] 0.0%"
    assert make_progress_bar(50, 10) == "[█████░░░░░] 50.0%"
    assert make_progress_bar(100, 10) == "[██████████] 100.0%"


def test_is_authorized():
    with patch.object(config, "ALLOWED_USER_IDS", [12345, 67890]):
        assert is_authorized(12345) is True
        assert is_authorized(67890) is True
        assert is_authorized(99999) is False

    with patch.object(config, "ALLOWED_USER_IDS", []):
        assert is_authorized(12345) is False


def test_check_auth_decorator():
    handler_called = []

    @bot.check_auth
    def dummy_handler(message):
        handler_called.append(message.from_user.id)

    # 1. ALLOWED_USER_IDS is empty -> guide message with ID
    with patch.object(config, "ALLOWED_USER_IDS", []):
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345)
            dummy_handler(msg)
            assert not handler_called
            mock_reply.assert_called_once()
            assert "Your Telegram ID is: <code>12345</code>" in mock_reply.call_args[0][1]

    # 2. Unauthorized user
    with patch.object(config, "ALLOWED_USER_IDS", [99999]):
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345)
            dummy_handler(msg)
            assert not handler_called
            mock_reply.assert_called_once()
            assert "Access Denied" in mock_reply.call_args[0][1]

    # 3. Authorized user
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        msg = make_mock_message(user_id=12345)
        dummy_handler(msg)
        assert handler_called == [12345]


def test_check_auth_callback_decorator():
    callback_called = []

    @bot.check_auth_callback
    def dummy_callback_handler(call):
        callback_called.append(call.data)

    # 1. Unauthorized callback
    with patch.object(config, "ALLOWED_USER_IDS", [99999]):
        with patch.object(bot.bot, "answer_callback_query") as mock_ans:
            call = make_mock_callback(user_id=12345, data="click_me")
            dummy_callback_handler(call)
            assert not callback_called
            mock_ans.assert_called_once()
            assert "Access denied" in mock_ans.call_args[0][1]

    # 2. Authorized callback
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        call = make_mock_callback(user_id=12345, data="click_me")
        dummy_callback_handler(call)
        assert callback_called == ["click_me"]


def test_send_long_message_short():
    with patch.object(bot.bot, "send_message") as mock_send:
        bot.send_long_message(123, "short text")
        mock_send.assert_called_once_with(123, "short text", parse_mode="HTML", reply_markup=None)


def test_send_long_message_empty():
    with patch.object(bot.bot, "send_message") as mock_send:
        bot.send_long_message(123, "")
        bot.send_long_message(123, "   ")
        mock_send.assert_not_called()


def test_send_long_message_split_and_fallback():
    # Long text exceeding 3800 chars
    lines = ["Line " + str(i) + " " + "x" * 100 for i in range(50)]
    long_text = "\n".join(lines)
    assert len(long_text) > 3800

    with patch.object(bot.bot, "send_message") as mock_send:
        with patch("time.sleep"):
            bot.send_long_message(123, long_text)
            assert mock_send.call_count > 1

    # HTML fallback to plain text on exception
    with patch.object(bot.bot, "send_message") as mock_send:
        mock_send.side_effect = [Exception("HTML parse error"), MagicMock()]
        bot.send_long_message(123, "<b>invalid text")
        assert mock_send.call_count == 2
        # Second call has parse_mode=None
        assert mock_send.call_args_list[1][1]["parse_mode"] is None


def test_reply_safe():
    msg = make_mock_message()

    # Success reply_to
    with patch.object(bot.bot, "reply_to") as mock_reply:
        bot.reply_safe(msg, "hello")
        mock_reply.assert_called_once()

    # Fallback to send_message when reply_to fails
    with patch.object(bot.bot, "reply_to", side_effect=Exception("msg deleted")):
        with patch.object(bot.bot, "send_message") as mock_send:
            bot.reply_safe(msg, "hello")
            mock_send.assert_called_once()
            assert mock_send.call_args[0] == (msg.chat.id, "hello")
            assert "reply_markup" in mock_send.call_args[1]


def test_register_telegram_commands():
    mock_target_bot = MagicMock()
    success = bot.register_telegram_commands(mock_target_bot)
    assert success is True
    mock_target_bot.set_my_commands.assert_called_once()
    commands = mock_target_bot.set_my_commands.call_args[0][0]
    assert len(commands) == 18

    # When set_my_commands raises
    mock_target_bot.set_my_commands.side_effect = Exception("Telegram API error")
    assert bot.register_telegram_commands(mock_target_bot) is False


def test_command_start_and_help():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345, text="/start")
            bot.send_welcome(msg)
            mock_reply.assert_called_once()
            reply_text = mock_reply.call_args[0][1]
            assert "Antigravity AI Agent Bot" in reply_text
            assert "Core Engine Commands" in reply_text


def test_command_model_picker_and_callback():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345, text="/model")
            bot.show_model_picker(msg)
            mock_reply.assert_called_once()
            text = mock_reply.call_args[0][1]
            assert "Antigravity AI Model Selector" in text

        # Set model callback
        with patch.object(bot.bot, "answer_callback_query") as mock_ans:
            with patch.object(bot.bot, "edit_message_text") as mock_edit:
                call = make_mock_callback(user_id=12345, data="set_model:claude-sonnet-4-6")
                bot.handle_set_model_callback(call)
                mock_ans.assert_called_once()
                mock_edit.assert_called_once()
                assert "claude-sonnet-4-6" in mock_edit.call_args[0][0]
                assert bot.agent_runner.get_chat_setting(12345, "model") == "claude-sonnet-4-6"


def test_command_effort_picker_and_callback():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345, text="/effort")
            bot.show_effort_picker(msg)
            mock_reply.assert_called_once()
            assert "Antigravity Reasoning Effort Level" in mock_reply.call_args[0][1]

        # Set effort callback
        with patch.object(bot.bot, "answer_callback_query") as mock_ans:
            with patch.object(bot.bot, "edit_message_text") as mock_edit:
                call = make_mock_callback(user_id=12345, data="set_effort:medium")
                bot.handle_set_effort_callback(call)
                mock_ans.assert_called_once()
                mock_edit.assert_called_once()
                assert "MEDIUM" in mock_edit.call_args[0][0]
                assert bot.agent_runner.get_chat_setting(12345, "effort") == "medium"


def test_command_mode_picker_and_callback():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345, text="/mode")
            bot.show_mode_picker(msg)
            mock_reply.assert_called_once()
            assert "Antigravity Agent Execution Mode" in mock_reply.call_args[0][1]

        # Set mode callback
        with patch.object(bot.bot, "answer_callback_query") as mock_ans:
            with patch.object(bot.bot, "edit_message_text") as mock_edit:
                call = make_mock_callback(user_id=12345, data="set_mode:plan")
                bot.handle_set_mode_callback(call)
                mock_ans.assert_called_once()
                mock_edit.assert_called_once()
                assert "plan" in mock_edit.call_args[0][0]
                assert bot.agent_runner.get_chat_setting(12345, "mode") == "plan"


def test_command_workspace_and_callback(tmp_path):
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        # /workspace with argument
        new_dir = str(tmp_path / "project-x")
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345, text=f"/workspace {new_dir}")
            bot.change_workspace(msg)
            mock_reply.assert_called_once()
            assert new_dir in mock_reply.call_args[0][1]
            assert bot.agent_runner.get_chat_workspace(12345) == os.path.abspath(new_dir)

        # /workspace without argument shows picker
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345, text="/workspace")
            bot.change_workspace(msg)
            mock_reply.assert_called_once()
            assert "Interactive Workspace Picker" in mock_reply.call_args[0][1]

        # set_ws callback
        token = bot.path_mapper.encode(new_dir)
        with patch.object(bot.bot, "answer_callback_query") as mock_ans:
            with patch.object(bot.bot, "edit_message_text") as mock_edit:
                call = make_mock_callback(user_id=12345, data=f"set_ws:{token}")
                bot.handle_set_ws_callback(call)
                mock_ans.assert_called_once()
                mock_edit.assert_called_once()
                assert "AI Workspace Successfully Changed" in mock_edit.call_args[0][0]


def test_command_tree_explorer(tmp_path):
    # Create sample structure
    sub = tmp_path / "subdir"
    sub.mkdir()
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("hello world")

    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot.agent_runner, "get_chat_workspace", return_value=str(tmp_path)):
            with patch.object(bot, "reply_safe") as mock_reply:
                msg = make_mock_message(user_id=12345, text="/tree")
                bot.show_tree_explorer(msg)
                mock_reply.assert_called_once()
                text = mock_reply.call_args[0][1]
                assert "Interactive File Explorer" in text


def test_command_cancel_and_stop():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot.agent_runner, "cancel_chat_process", return_value=True):
            with patch.object(bot, "reply_safe") as mock_reply:
                msg = make_mock_message(user_id=12345, text="/stop")
                bot.handle_cancel_command(msg)
                mock_reply.assert_called_once()
                assert "Successfully Cancelled" in mock_reply.call_args[0][1]

        with patch.object(bot.agent_runner, "cancel_chat_process", return_value=False):
            with patch.object(bot, "reply_safe") as mock_reply:
                msg = make_mock_message(user_id=12345, text="/cancel")
                bot.handle_cancel_command(msg)
                mock_reply.assert_called_once()
                assert "No AI execution process is currently running" in mock_reply.call_args[0][1]


def test_command_logs():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot.agent_runner, "fetch_bot_logs", return_value="log line 1\nlog line 2"):
            with patch.object(bot, "send_long_message") as mock_send:
                msg = make_mock_message(user_id=12345, text="/logs")
                bot.show_bot_logs(msg)
                mock_send.assert_called_once()
                assert "Recent Bot Service Activity Logs" in mock_send.call_args[0][1]


def test_command_status_and_usage():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345, text="/status")
            bot.send_status(msg)
            mock_reply.assert_called_once()
            assert "Server & AI Engine Status" in mock_reply.call_args[0][1]

        with patch.object(bot.agent_runner, "fetch_live_user_quota_summary", return_value="Quota Info"):
            with patch.object(bot, "reply_safe") as mock_reply:
                msg = make_mock_message(user_id=12345, text="/usage")
                bot.send_usage(msg)
                mock_reply.assert_called_once()
                assert "Active Conversation Session Capacity" in mock_reply.call_args[0][1]


def test_command_new_session():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot.agent_runner, "reset_session") as mock_reset:
            with patch.object(bot, "reply_safe") as mock_reply:
                msg = make_mock_message(user_id=12345, text="/new")
                bot.reset_conversation(msg)
                mock_reset.assert_called_once_with(12345)
                mock_reply.assert_called_once()
                assert "successfully reset" in mock_reply.call_args[0][1]


def test_command_rename_session():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        # No title given
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345, text="/rename")
            bot.rename_session_command(msg)
            assert "Usage:" in mock_reply.call_args[0][1]

        # No active session
        bot.agent_runner.active_conversations.pop(12345, None)
        with patch.object(bot, "reply_safe") as mock_reply:
            msg = make_mock_message(user_id=12345, text="/rename Project Alpha")
            bot.rename_session_command(msg)
            assert "No active conversation session" in mock_reply.call_args[0][1]

        # Success rename
        bot.agent_runner.active_conversations[12345] = "conv-xyz"
        with patch.object(bot.agent_runner, "rename_session", return_value=True):
            with patch.object(bot, "reply_safe") as mock_reply:
                msg = make_mock_message(user_id=12345, text="/rename Project Alpha")
                bot.rename_session_command(msg)
                assert "Session Name Successfully Changed" in mock_reply.call_args[0][1]


def test_command_smash_goal_plan():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        # Smash with arg
        with patch.object(bot, "process_custom_agent_prompt") as mock_proc:
            msg = make_mock_message(user_id=12345, text="/smash Fix all lints")
            bot.execute_smash(msg)
            mock_proc.assert_called_once()
            assert mock_proc.call_args[0][1] == "Fix all lints"

        # Goal with arg
        with patch.object(bot, "process_agent_prompt") as mock_proc:
            msg = make_mock_message(user_id=12345, text="/goal Complete project")
            bot.execute_goal(msg)
            mock_proc.assert_called_once()
            assert "Goal: Complete project" in mock_proc.call_args[0][1]

        # Plan with arg
        with patch.object(bot, "process_agent_prompt") as mock_proc:
            msg = make_mock_message(user_id=12345, text="/plan Database migration")
            bot.execute_plan(msg)
            mock_proc.assert_called_once()
            assert "Database migration" in mock_proc.call_args[0][1]


def test_handle_text_prompt():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(bot, "process_agent_prompt") as mock_proc:
            msg = make_mock_message(user_id=12345, text="Refactor the authentication module")
            bot.handle_text_prompt(msg)
            mock_proc.assert_called_once_with(msg, "Refactor the authentication module")

        # Empty text does nothing
        with patch.object(bot, "process_agent_prompt") as mock_proc:
            msg_empty = make_mock_message(user_id=12345, text="   ")
            bot.handle_text_prompt(msg_empty)
            mock_proc.assert_not_called()


def test_execute_resume():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        # Without prompt -> shows picker
        with patch.object(bot, "show_session_picker") as mock_picker:
            msg = make_mock_message(user_id=12345, text="/resume")
            bot.execute_resume(msg)
            mock_picker.assert_called_once_with(msg)

        # With prompt -> resumes session
        with patch.object(bot, "process_custom_agent_prompt") as mock_custom:
            msg = make_mock_message(user_id=12345, text="/resume Continue building UI")
            bot.execute_resume(msg)
            mock_custom.assert_called_once()
            assert mock_custom.call_args[0][1] == "Continue building UI"


def test_show_session_picker_and_history():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        # No sessions found
        with patch.object(bot.agent_runner, "get_recent_sessions", return_value=[]):
            with patch.object(bot, "reply_safe") as mock_reply:
                msg = make_mock_message(user_id=12345)
                bot.show_session_picker(msg)
                assert "No conversation session history" in mock_reply.call_args[0][1]

        # Populated sessions
        sessions = [{"id": "s1", "title": "Session 1", "date": "10 Mar 12:00"}]
        with patch.object(bot.agent_runner, "get_recent_sessions", return_value=sessions):
            with patch.object(bot, "reply_safe") as mock_reply:
                msg = make_mock_message(user_id=12345)
                bot.show_session_picker(msg)
                assert "Select / Resume Conversation Session" in mock_reply.call_args[0][1]


def test_handle_session_selection():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        # Select "new"
        with patch.object(bot.agent_runner, "reset_session") as mock_reset:
            with patch.object(bot.bot, "answer_callback_query") as mock_ans:
                with patch.object(bot.bot, "edit_message_text") as mock_edit:
                    call = make_mock_callback(user_id=12345, data="select_session|new")
                    bot.handle_session_selection(call)
                    mock_reset.assert_called_once_with(12345)
                    mock_ans.assert_called_once()
                    assert "New Conversation Session Started" in mock_edit.call_args[0][0]

        # Select existing session
        with patch.object(bot.agent_runner, "set_active_session") as mock_set:
            with patch.object(bot.bot, "answer_callback_query") as mock_ans:
                with patch.object(bot, "show_session_history_card") as mock_card:
                    call = make_mock_callback(user_id=12345, data="select_session|conv-101")
                    bot.handle_session_selection(call)
                    mock_set.assert_called_once_with(12345, "conv-101")
                    mock_ans.assert_called_once()
                    mock_card.assert_called_once()


def test_show_session_history_card():
    turns = [{"user": "Hello", "ai": "Hi there!"}]
    with patch.object(bot.agent_runner, "get_full_session_history_formatted", return_value=turns):
        with patch.object(bot, "send_long_message") as mock_send:
            with patch("time.sleep"):
                bot.show_session_history_card(12345, "conv-101")
                # Header, Turn, Footer
                assert mock_send.call_count >= 3


def test_delete_session_command_and_callback():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        # Delete command with sessions
        sessions = [{"id": "s1", "title": "Session 1", "date": "10 Mar"}]
        with patch.object(bot.agent_runner, "get_recent_sessions", return_value=sessions):
            with patch.object(bot, "reply_safe") as mock_reply:
                msg = make_mock_message(user_id=12345, text="/delete")
                bot.delete_session_command(msg)
                assert "Delete Conversation Session" in mock_reply.call_args[0][1]

        # Delete callback
        bot.agent_runner.active_conversations[12345] = "s1"
        with patch.object(bot.agent_runner, "delete_session", return_value=True):
            with patch.object(bot.agent_runner, "reset_session") as mock_reset:
                with patch.object(bot.bot, "answer_callback_query") as mock_ans:
                    with patch.object(bot.bot, "edit_message_text") as mock_edit:
                        call = make_mock_callback(user_id=12345, data="delete_session|s1")
                        bot.handle_delete_session_callback(call)
                        mock_reset.assert_called_once_with(12345)
                        mock_ans.assert_called_once()
                        assert "Deleted Successfully" in mock_edit.call_args[0][0]


def test_handle_media_prompt(tmp_path):
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        with patch.object(config, "TEMP_UPLOAD_DIR", str(tmp_path)):
            # Photo upload
            msg_photo = make_mock_message(user_id=12345, caption="Explain this diagram")
            photo_size = MagicMock()
            photo_size.file_id = "photo_123"
            msg_photo.photo = [photo_size]

            file_info = MagicMock()
            file_info.file_path = "photos/file_0.jpg"

            with patch.object(bot.bot, "get_file", return_value=file_info):
                with patch.object(bot.bot, "download_file", return_value=b"fake image bytes"):
                    with patch.object(bot, "process_agent_prompt") as mock_proc:
                        bot.handle_media_prompt(msg_photo)
                        mock_proc.assert_called_once()
                        prompt_arg = mock_proc.call_args[0][1]
                        assert "File uploaded at" in prompt_arg
                        assert "Explain this diagram" in prompt_arg


def test_additional_callbacks():
    with patch.object(config, "ALLOWED_USER_IDS", [12345]):
        # open_quota_info
        with patch.object(bot, "send_usage") as mock_usage:
            with patch.object(bot.bot, "answer_callback_query") as mock_ans:
                call = make_mock_callback(user_id=12345, data="open_quota_info")
                bot.handle_open_quota_info(call)
                mock_ans.assert_called_once()
                mock_usage.assert_called_once()

        # open_tree_explorer
        with patch.object(bot, "show_tree_explorer") as mock_tree:
            with patch.object(bot.bot, "answer_callback_query") as mock_ans:
                call = make_mock_callback(user_id=12345, data="open_tree_explorer")
                bot.handle_open_tree_explorer(call)
                mock_ans.assert_called_once()
                mock_tree.assert_called_once()

        # cancel_execution callback
        with patch.object(bot.agent_runner, "cancel_chat_process", return_value=True):
            with patch.object(bot.bot, "answer_callback_query") as mock_ans:
                with patch.object(bot.bot, "edit_message_text") as mock_edit:
                    call = make_mock_callback(user_id=12345, data="cancel_execution")
                    bot.handle_cancel_callback(call)
                    mock_ans.assert_called_once_with(call.id, "Process cancelled!")
                    assert "Execution Cancelled by User" in mock_edit.call_args[0][0]
