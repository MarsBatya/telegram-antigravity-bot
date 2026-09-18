import base64
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import config
import stream_runner


def test_ascii_bar():
    # 0%
    bar0 = stream_runner.make_ascii_bar(0, 10)
    assert bar0 == "░" * 10

    # 50%
    bar50 = stream_runner.make_ascii_bar(50, 10)
    assert bar50 == "█████░░░░░"

    # 100%
    bar100 = stream_runner.make_ascii_bar(100, 10)
    assert bar100 == "█" * 10

    # Clamping < 0 and > 100
    assert stream_runner.make_ascii_bar(-10, 10) == "░" * 10
    assert stream_runner.make_ascii_bar(150, 10) == "█" * 10


def test_parse_reset_time():
    assert stream_runner.parse_reset_time("") == ""
    assert stream_runner.parse_reset_time(None) == ""
    assert stream_runner.parse_reset_time("not-a-date") == ""

    # Past time
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert stream_runner.parse_reset_time(past) == "Refreshes soon"

    # Minutes in future (< 1h)
    in_30m = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    res_m = stream_runner.parse_reset_time(in_30m)
    assert "Refreshes in" in res_m and "m" in res_m

    # Hours in future (< 24h)
    in_5h = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=10)).isoformat()
    res_h = stream_runner.parse_reset_time(in_5h)
    assert "Refreshes in" in res_h and "h" in res_h

    # Days in future (> 24h)
    in_2d = (datetime.now(timezone.utc) + timedelta(days=2, hours=3)).isoformat()
    res_d = stream_runner.parse_reset_time(in_2d)
    assert "Refreshes in 2d" in res_d


def test_session_persistence(tmp_path):
    session_file = str(tmp_path / "sessions.json")

    # Initial load on missing file
    stream_runner.load_persistent_sessions(session_file)
    assert stream_runner.active_conversations == {}

    # Set data and save
    stream_runner.active_conversations = {123: "conv-abc"}
    stream_runner.active_workspaces = {123: "/path/to/ws"}
    stream_runner.active_settings = {
        123: {"model": "m1", "effort": "low", "mode": "plan"},
    }
    stream_runner.save_persistent_sessions(session_file)

    # Reload from file
    stream_runner.active_conversations = {}
    stream_runner.active_workspaces = {}
    stream_runner.active_settings = {}
    stream_runner.load_persistent_sessions(session_file)

    assert stream_runner.active_conversations.get(123) == "conv-abc"
    assert stream_runner.active_workspaces.get(123) == "/path/to/ws"
    assert stream_runner.active_settings.get(123)["model"] == "m1"


def test_session_persistence_legacy_format(tmp_path):
    session_file = str(tmp_path / "legacy_sessions.json")
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump({"456": "conv-legacy"}, f)

    stream_runner.load_persistent_sessions(session_file)
    assert stream_runner.active_conversations.get(456) == "conv-legacy"


def test_chat_settings_and_workspace(tmp_path):
    session_file = str(tmp_path / "sessions.json")
    with patch.object(config, "SESSION_FILE", session_file):
        # Default setting
        chat_id = 9999
        assert stream_runner.get_chat_setting(chat_id, "model") == config.DEFAULT_MODEL
        assert (
            stream_runner.get_chat_setting(chat_id, "effort") == config.DEFAULT_EFFORT
        )
        assert stream_runner.get_chat_setting(chat_id, "mode") == config.DEFAULT_MODE

        # Set setting
        stream_runner.set_chat_setting(chat_id, "model", "custom-model")
        assert stream_runner.get_chat_setting(chat_id, "model") == "custom-model"

        # Workspace
        assert stream_runner.get_chat_workspace(chat_id) == config.DEFAULT_WORKSPACE
        test_ws = str(tmp_path / "test-ws")
        stream_runner.set_chat_workspace(chat_id, test_ws)
        assert stream_runner.get_chat_workspace(chat_id) == os.path.abspath(
            test_ws,
        )


def test_chat_lock():
    lock1 = stream_runner.get_chat_lock(101)
    lock2 = stream_runner.get_chat_lock(101)
    lock3 = stream_runner.get_chat_lock(102)
    assert lock1 is lock2
    assert lock1 is not lock3


def test_calculate_session_tokens(tmp_path):
    brain_dir = str(tmp_path / "brain")
    conv_id = "test-conv-123"
    log_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    log_dir.mkdir(parents=True)
    transcript_file = log_dir / "transcript.jsonl"

    # Write transcript lines
    lines = [
        {"type": "USER_INPUT", "content": "hello"},
        {"type": "PLANNER_RESPONSE", "content": "hi", "usage": {"total_tokens": 150}},
        "not valid json",
        {"type": "PLANNER_RESPONSE", "content": "done", "usage": {"total_tokens": 250}},
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for item in lines:
            if isinstance(item, str):
                f.write(item + "\n")
            else:
                f.write(json.dumps(item) + "\n")

    total = stream_runner.calculate_session_tokens(conv_id, brain_dir=brain_dir)
    assert total == 400

    # Non-existent conversation
    assert (
        stream_runner.calculate_session_tokens("non-existent", brain_dir=brain_dir) == 0
    )


def test_get_recent_sessions(tmp_path):
    brain_dir = str(tmp_path / "brain")

    # Non-existent brain dir
    assert stream_runner.get_recent_sessions(brain_dir=str(tmp_path / "missing")) == []

    # Create two conversations
    c1 = "conv-1"
    c2 = "conv-2"
    c1_dir = tmp_path / "brain" / c1 / ".system_generated" / "logs"
    c2_dir = tmp_path / "brain" / c2 / ".system_generated" / "logs"
    c1_dir.mkdir(parents=True)
    c2_dir.mkdir(parents=True)

    # c1 has <USER_REQUEST>
    with open(c1_dir / "transcript.jsonl", "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "type": "USER_INPUT",
                    "content": "<USER_REQUEST>\nBuild a web scraper\n</USER_REQUEST>",
                    "created_at": "2026-03-01T12:00:00Z",
                },
            )
            + "\n",
        )

    # c2 has plain text
    with open(c2_dir / "transcript.jsonl", "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "type": "USER_INPUT",
                    "content": "Fix database connection pool bug",
                    "created_at": "2026-03-02T15:30:00Z",
                },
            )
            + "\n",
        )

    sessions = stream_runner.get_recent_sessions(limit=5, brain_dir=brain_dir)
    assert len(sessions) == 2
    titles = [s["title"] for s in sessions]
    assert any("Build a web scraper" in t for t in titles)
    assert any("Fix database connection pool bug" in t for t in titles)


def test_rename_and_delete_session(tmp_path):
    brain_dir = str(tmp_path / "brain")
    conv_id = "conv-rename"
    log_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    log_dir.mkdir(parents=True)
    transcript_file = log_dir / "transcript.jsonl"

    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "type": "USER_INPUT",
                    "content": "<USER_REQUEST>Old Title</USER_REQUEST>",
                },
            )
            + "\n",
        )

    # Rename existing
    assert (
        stream_runner.rename_session(conv_id, "New Title", brain_dir=brain_dir) is True
    )
    with open(transcript_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "New Title" in content

    # Rename non-existing
    assert (
        stream_runner.rename_session("missing", "New Title", brain_dir=brain_dir)
        is False
    )

    # Delete existing
    assert stream_runner.delete_session(conv_id, brain_dir=brain_dir) is True
    assert not os.path.exists(tmp_path / "brain" / conv_id)

    # Delete non-existing
    assert stream_runner.delete_session("missing", brain_dir=brain_dir) is False


def test_get_full_session_history_formatted(tmp_path):
    brain_dir = str(tmp_path / "brain")
    conv_id = "conv-history"
    log_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    log_dir.mkdir(parents=True)
    transcript_file = log_dir / "transcript.jsonl"

    turns_data = [
        {
            "type": "USER_INPUT",
            "content": "<USER_REQUEST>What is Python?</USER_REQUEST>",
        },
        {"type": "PLANNER_RESPONSE", "content": "Python is a programming language."},
        {"type": "PLANNER_RESPONSE", "content": "It is widely used."},
        {
            "type": "USER_INPUT",
            "content": "<USER_REQUEST>How do I test?</USER_REQUEST>",
        },
        {"type": "PLANNER_RESPONSE", "content": "Use pytest!"},
    ]

    with open(transcript_file, "w", encoding="utf-8") as f:
        for item in turns_data:
            f.write(json.dumps(item) + "\n")

    history = stream_runner.get_full_session_history_formatted(
        conv_id,
        max_turns=5,
        brain_dir=brain_dir,
    )
    assert len(history) == 2
    assert history[0]["user"] == "What is Python?"
    assert "Python is a programming language.\n\nIt is widely used." in history[0]["ai"]
    assert history[1]["user"] == "How do I test?"
    assert history[1]["ai"] == "Use pytest!"

    # Respects max_turns
    short_history = stream_runner.get_full_session_history_formatted(
        conv_id,
        max_turns=1,
        brain_dir=brain_dir,
    )
    assert len(short_history) == 1
    assert short_history[0]["user"] == "How do I test?"


def test_active_session_and_reset(tmp_path):
    session_file = str(tmp_path / "sessions.json")
    with patch.object(config, "SESSION_FILE", session_file):
        stream_runner.set_active_session(777, "session-777")
        assert stream_runner.active_conversations[777] == "session-777"

        stream_runner.reset_session(777)
        assert 777 not in stream_runner.active_conversations


def test_cancel_chat_process():
    # No process
    assert stream_runner.cancel_chat_process(99999) is False

    # Mock process already finished
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    stream_runner.active_processes[111] = mock_proc
    assert stream_runner.cancel_chat_process(111) is False

    # Mock process running
    mock_proc_running = MagicMock()
    mock_proc_running.poll.side_effect = [
        None,
        0,
    ]  # First poll running, second terminated
    stream_runner.active_processes[222] = mock_proc_running
    assert stream_runner.cancel_chat_process(222) is True
    mock_proc_running.terminate.assert_called_once()


def test_fetch_bot_logs():
    with patch("subprocess.run") as mock_run:
        # Success with logs
        mock_run.return_value = MagicMock(stdout="systemd[1]: Started antigravity-bot.")
        logs = stream_runner.fetch_bot_logs(10)
        assert "Started antigravity-bot" in logs

        # Empty logs
        mock_run.return_value = MagicMock(stdout="")
        logs_empty = stream_runner.fetch_bot_logs(10)
        assert "No recent logs" in logs_empty

        # Error
        mock_run.side_effect = Exception("journalctl not found")
        logs_err = stream_runner.fetch_bot_logs(10)
        assert "Failed to fetch logs" in logs_err


def test_fetch_available_models_live(tmp_path):
    token_file = str(tmp_path / "oauth-token.json")

    # Missing file
    assert (
        stream_runner.fetch_available_models_live(token_file=str(tmp_path / "missing"))
        == []
    )

    # File without access token
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump({"token": {}}, f)
    assert stream_runner.fetch_available_models_live(token_file=token_file) == []

    # Valid token file with mock response
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump({"token": {"access_token": "ya29.mock_token"}}, f)

    fake_response = {
        "models": {
            "model-b": {"displayName": "Model Beta", "recommended": False},
            "model-a": {"displayName": "Model Alpha", "recommended": True},
        },
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        models = stream_runner.fetch_available_models_live(token_file=token_file)
        assert len(models) == 2
        # Recommended model comes first
        assert models[0]["id"] == "model-a"
        assert models[0]["recommended"] is True
        assert models[1]["id"] == "model-b"


def test_fetch_live_user_quota_summary(tmp_path):
    token_file = str(tmp_path / "oauth-token.json")

    # Missing file
    res = stream_runner.fetch_live_user_quota_summary(
        token_file=str(tmp_path / "missing"),
    )
    assert "OAuth token file not found" in res

    # Missing access token
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump({"token": {}}, f)
    res_no_tok = stream_runner.fetch_live_user_quota_summary(token_file=token_file)
    assert "Invalid OAuth access token" in res_no_tok

    # Valid token with fake id_token containing email
    payload = json.dumps({"email": "developer@example.com"}).encode("utf-8")
    fake_jwt = "header." + base64.b64encode(payload).decode("utf-8") + ".sig"

    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(
            {"token": {"access_token": "ya29.mock_token"}, "id_token": fake_jwt},
            f,
        )

    fake_quota_data = {
        "groups": [
            {
                "displayName": "Gemini Models",
                "description": "Rate limits for Gemini",
                "buckets": [
                    {
                        "displayName": "Pro Requests",
                        "remainingFraction": 0.75,
                        "resetTime": (
                            datetime.now(timezone.utc) + timedelta(hours=2)
                        ).isoformat(),
                        "description": "Per day quota",
                    },
                    {
                        "displayName": "Disabled Model",
                        "disabled": True,
                        "description": "Not available",
                    },
                ],
            },
        ],
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_quota_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        quota_summary = stream_runner.fetch_live_user_quota_summary(
            token_file=token_file,
        )
        assert "developer@example.com" in quota_summary
        assert "GEMINI MODELS" in quota_summary
        assert "Pro Requests" in quota_summary
        assert "75.00%" in quota_summary
        assert "[Disabled]" in quota_summary


def test_run_antigravity_stream_missing_binary():
    with patch.object(config, "AGY_PATH", "/non/existent/path/to/agy"):
        resp, usage, files = stream_runner.run_antigravity_stream("test prompt", 1234)
        assert "agy executable not found" in resp
        assert usage == {}
        assert files == []


def test_run_antigravity_stream_streaming_events(tmp_path):
    agy_mock = str(tmp_path / "agy")
    with open(agy_mock, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(agy_mock, 0o755)  # noqa: S103

    stream_lines = [
        json.dumps({"event": "init", "conversation_id": "conv-stream-100"}),
        json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "step_type": "agent_response",
                    "text_delta": "Hello from ",
                    "usage": {"total_tokens": 50},
                },
            },
        ),
        json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "step_type": "tool_use",
                    "tool_call": {
                        "name": "view_file",
                        "args": {
                            "AbsolutePath": "/project/file.py",
                            "toolAction": "Reading code",
                        },
                    },
                },
            },
        ),
        json.dumps(
            {
                "event": "result",
                "result": {
                    "response": "Hello from Antigravity!",
                    "usage": {"total_tokens": 120},
                },
            },
        ),
    ]

    mock_process = MagicMock()
    mock_process.stdout.readline.side_effect = [
        line + "\n" for line in stream_lines
    ] + [""]
    mock_process.wait.return_value = 0

    progress_messages = []

    def on_progress(text):
        progress_messages.append(text)

    with patch.object(config, "AGY_PATH", agy_mock):
        with patch("subprocess.Popen", return_value=mock_process):
            with patch.object(stream_runner, "save_persistent_sessions"):
                resp, usage, files = stream_runner.run_antigravity_stream(
                    "Say hello",
                    9988,
                    workspace_dir=str(tmp_path),
                    progress_callback=on_progress,
                )

                assert resp == "Hello from Antigravity!"
                assert usage.get("total_tokens") == 120
                assert stream_runner.active_conversations[9988] == "conv-stream-100"


def test_run_smash_and_resume_stream():
    with patch.object(stream_runner, "run_antigravity_stream") as mock_run:
        mock_run.return_value = ("Success", {}, [])

        # Smash stream
        stream_runner.run_smash_stream("Fix everything", 555)
        mock_run.assert_called_once()
        prompt_arg = mock_run.call_args[0][0]
        assert "SMASH MODE INSTRUCTION" in prompt_arg
        assert "Fix everything" in prompt_arg

        mock_run.reset_mock()

        # Resume stream
        stream_runner.resume_stream("Keep going", 555)
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == "Keep going"


def test_rename_session_with_metadata_header(tmp_path):
    brain_dir = str(tmp_path / "brain")
    conv_id = "conv-meta-rename"
    log_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    log_dir.mkdir(parents=True)
    transcript_file = log_dir / "transcript.jsonl"

    # Line 0 is a system message; Line 1 is the user request
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"type": "SYSTEM_INFO", "content": "Session initialized"},
            )
            + "\n",
        )
        f.write(
            json.dumps(
                {
                    "type": "USER_INPUT",
                    "content": "<USER_REQUEST>Initial Goal</USER_REQUEST>",
                },
            )
            + "\n",
        )

    assert (
        stream_runner.rename_session(conv_id, "Renamed Goal", brain_dir=brain_dir)
        is True
    )

    with open(transcript_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 2
        assert "Session initialized" in lines[0]
        assert "Renamed Goal" in lines[1]


def test_cancel_chat_process_kills_process_group():
    mock_proc = MagicMock()
    mock_proc.pid = 4321
    mock_proc.poll.side_effect = [None, None, 0]

    stream_runner.active_processes[333] = mock_proc

    with (
        patch("os.getpgid", return_value=4321) as mock_getpgid,
        patch("os.killpg") as mock_killpg,
    ):
        assert stream_runner.cancel_chat_process(333) is True
        mock_getpgid.assert_called_with(4321)
        assert mock_killpg.call_count >= 1
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        assert 333 not in stream_runner.active_processes


def test_cleanup_all_active_processes():
    proc1 = MagicMock()
    proc1.pid = 1001
    proc1.poll.return_value = None

    proc2 = MagicMock()
    proc2.pid = 1002
    proc2.poll.return_value = 0  # already stopped

    stream_runner.active_processes[1] = proc1
    stream_runner.active_processes[2] = proc2

    with patch("os.getpgid", return_value=1001), patch("os.killpg"):
        stream_runner.cleanup_all_active_processes()
        proc1.terminate.assert_called_once()
        proc2.terminate.assert_not_called()
        assert len(stream_runner.active_processes) == 0


def test_run_antigravity_stream_registers_active_process(tmp_path):
    agy_mock = str(tmp_path / "agy")
    with open(agy_mock, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(agy_mock, 0o755)  # noqa: S103

    mock_process = MagicMock()
    mock_process.pid = 5555

    registered_during_run = False

    def fake_readline():
        nonlocal registered_during_run
        if 7788 in stream_runner.active_processes:
            registered_during_run = True
        return ""

    mock_process.stdout.readline.side_effect = fake_readline
    mock_process.wait.return_value = 0

    with patch.object(config, "AGY_PATH", agy_mock):
        with patch("subprocess.Popen", return_value=mock_process):
            stream_runner.run_antigravity_stream(
                "Test",
                7788,
                workspace_dir=str(tmp_path),
            )

    assert registered_during_run is True
    assert 7788 not in stream_runner.active_processes


def test_atomic_session_persistence_concurrent(tmp_path):
    import concurrent.futures

    session_file = str(tmp_path / "concurrent_sessions.json")
    stream_runner.active_conversations.clear()
    stream_runner.active_workspaces.clear()
    stream_runner.active_settings.clear()

    def worker(idx: int) -> None:
        stream_runner.active_conversations[idx] = f"conv-{idx}"
        stream_runner.save_persistent_sessions(session_file)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, i) for i in range(10)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    stream_runner.active_conversations.clear()
    stream_runner.load_persistent_sessions(session_file)
    assert len(stream_runner.active_conversations) == 10
    for i in range(10):
        assert stream_runner.active_conversations[i] == f"conv-{i}"
