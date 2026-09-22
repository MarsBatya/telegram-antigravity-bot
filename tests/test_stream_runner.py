import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from unittest.mock import MagicMock, patch


from app.core import config
from app.core.storage import SessionStorage
from app.runner import stream_runner
from app.utils.helpers import make_progress_bar


def test_ascii_bar() -> None:
    assert "[░░░░░░░░░░] 0.0%" in make_progress_bar(0, 10)
    assert "[█████░░░░░] 50.0%" in make_progress_bar(50, 10)
    assert "[██████████] 100.0%" in make_progress_bar(100, 10)
    assert "[░░░░░░░░░░] -10.0%" in make_progress_bar(-10, 10)
    assert "[██████████] 150.0%" in make_progress_bar(150, 10)


def test_parse_reset_time() -> None:
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


def test_session_persistence(tmp_path: Path) -> None:
    session_file = str(tmp_path / "sessions.json")
    storage = SessionStorage(file_path=session_file)

    # Initial load on missing file
    storage.load(session_file)
    assert storage.active_conversations == {}

    # Set data and save
    storage.set_active_session(123, "conv-abc")
    storage.set_workspace(123, "/path/to/ws")
    storage.set_setting(123, "model", "m1")
    storage.set_setting(123, "effort", "low")
    storage.set_setting(123, "mode", "plan")
    storage.save(session_file)

    # Reload from file
    new_storage = SessionStorage(file_path=session_file)
    new_storage.load(session_file)

    assert new_storage.get_active_session(123) == "conv-abc"
    assert new_storage.get_workspace(123) == "/path/to/ws"
    assert new_storage.get_setting(123, "model") == "m1"


def test_session_persistence_legacy_format(tmp_path: Path) -> None:
    session_file = str(tmp_path / "legacy_sessions.json")
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump({"456": "conv-legacy"}, f)

    storage = SessionStorage(file_path=session_file)
    storage.load(session_file)
    assert storage.get_active_session(456) == "conv-legacy"


def test_chat_settings_and_workspace(tmp_path: Path, storage: SessionStorage) -> None:
    chat_id = 9999
    assert storage.get_setting(chat_id, "model") == config.DEFAULT_MODEL
    assert storage.get_setting(chat_id, "effort") == config.DEFAULT_EFFORT
    assert storage.get_setting(chat_id, "mode") == config.DEFAULT_MODE

    storage.set_setting(chat_id, "model", "custom-model")
    assert storage.get_setting(chat_id, "model") == "custom-model"

    assert storage.get_workspace(chat_id) == config.DEFAULT_WORKSPACE
    test_ws = str(tmp_path / "test-ws")
    storage.set_workspace(chat_id, test_ws)
    assert storage.get_workspace(chat_id) == os.path.abspath(test_ws)


def test_chat_lock(storage: SessionStorage) -> None:
    lock1 = storage.get_lock(101)
    lock2 = storage.get_lock(101)
    lock3 = storage.get_lock(102)
    assert lock1 is lock2
    assert lock1 is not lock3


def test_calculate_session_tokens(tmp_path: Path) -> None:
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


def test_get_recent_sessions(tmp_path: Path) -> None:
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


def test_rename_and_delete_session(tmp_path: Path) -> None:
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


def test_get_full_session_history_formatted(tmp_path: Path) -> None:
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


def test_active_session_and_reset(storage: SessionStorage) -> None:
    storage.set_active_session(777, "session-777")
    assert storage.get_active_session(777) == "session-777"

    storage.reset_session(777)
    assert storage.get_active_session(777) is None


def test_cancel_chat_process(storage: SessionStorage) -> None:
    # No process
    assert storage.cancel_chat_process(99999) is False

    # Mock process already finished
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    storage.register_process(111, mock_proc)
    assert storage.cancel_chat_process(111) is False

    # Mock process running
    mock_proc_running = MagicMock()
    mock_proc_running.poll.side_effect = [
        None,
        0,
    ]  # First poll running, second terminated
    storage.register_process(222, mock_proc_running)
    assert storage.cancel_chat_process(222) is True
    mock_proc_running.terminate.assert_called_once()


def test_fetch_bot_logs() -> None:
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


def test_fetch_available_models_live(tmp_path: Path) -> None:
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


def test_fetch_available_models_tiered_expansion(tmp_path: Path) -> None:
    token_file = str(tmp_path / "oauth-token.json")
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump({"token": {"access_token": "ya29.mock_token"}}, f)

    fake_response = {
        "models": {
            "gemini-3.8-flash-tiered": {
                "supportsThinking": True,
                "recommended": True,
            },
            "gemini-3.1-pro-high": {
                "displayName": "Gemini 3.1 Pro (High)",
                "recommended": False,
            },
        },
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        models = stream_runner.fetch_available_models_live(token_file=token_file)
        ids = [m["id"] for m in models]
        assert "gemini-3.8-flash-high" in ids
        assert "gemini-3.8-flash-medium" in ids
        assert "gemini-3.8-flash-low" in ids
        assert "gemini-3.1-pro-high" in ids


def test_fetch_live_user_quota_summary(tmp_path: Path) -> None:
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
        assert "75.0%" in quota_summary
        assert "[Disabled]" in quota_summary


def test_run_antigravity_stream_missing_binary(storage: SessionStorage) -> None:
    with patch.object(config, "AGY_PATH", "/non/existent/path/to/agy"):
        resp, usage, files = stream_runner.run_antigravity_stream(
            "test prompt",
            1234,
            storage=storage,
        )
        assert "agy executable not found" in resp
        assert usage == {}
        assert files == []


def test_run_antigravity_stream_streaming_events(
    tmp_path: Path,
    storage: SessionStorage,
) -> None:
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

    def on_progress(text: str) -> None:
        progress_messages.append(text)

    with patch.object(config, "AGY_PATH", agy_mock):
        with patch("subprocess.Popen", return_value=mock_process):
            with patch.object(storage, "save"):
                resp, usage, files = stream_runner.run_antigravity_stream(
                    "Say hello",
                    9988,
                    workspace_dir=str(tmp_path),
                    progress_callback=on_progress,
                    storage=storage,
                )

                assert resp == "Hello from Antigravity!"
                assert usage.get("total_tokens") == 120
                assert storage.get_active_session(9988) == "conv-stream-100"


def test_run_smash_and_resume_stream(storage: SessionStorage) -> None:
    with patch.object(stream_runner, "run_antigravity_stream") as mock_run:
        mock_run.return_value = ("Success", {}, [])

        # Smash prompt
        smash_prompt = (
            "💥 SMASH MODE INSTRUCTION: Complete the following task: Fix everything"
        )
        stream_runner.run_antigravity_stream(smash_prompt, 555, storage=storage)
        mock_run.assert_called_once()
        prompt_arg = mock_run.call_args[0][0]
        assert "SMASH MODE INSTRUCTION" in prompt_arg
        assert "Fix everything" in prompt_arg
        assert mock_run.call_args[1].get("storage") is storage


def test_rename_session_with_metadata_header(tmp_path: Path) -> None:
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


def test_cancel_chat_process_kills_process_group(storage: SessionStorage) -> None:
    mock_proc = MagicMock()
    mock_proc.pid = 4321
    mock_proc.poll.side_effect = [None, None, 0]

    storage.register_process(333, mock_proc)

    with (
        patch("sys.platform", "linux"),
        patch("os.getpgid", return_value=4321, create=True) as mock_getpgid,
        patch("os.killpg", create=True) as mock_killpg,
    ):
        assert storage.cancel_chat_process(333) is True
        mock_getpgid.assert_called_with(4321)
        assert mock_killpg.call_count >= 1
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        assert storage.get_process(333) is None


def test_cancel_chat_process_windows(storage: SessionStorage) -> None:
    mock_proc = MagicMock()
    mock_proc.pid = 7777
    mock_proc.poll.return_value = None

    storage.register_process(555, mock_proc)

    with (
        patch("subprocess.run") as mock_subproc,
        patch("psutil.Process") as mock_psutil_proc,
        patch("sys.platform", "win32"),
    ):
        child_mock = MagicMock()
        mock_psutil_proc.return_value.children.return_value = [child_mock]

        assert storage.cancel_chat_process(555) is True
        mock_psutil_proc.assert_called_with(7777)
        child_mock.kill.assert_called_once()
        mock_psutil_proc.return_value.kill.assert_called_once()
        mock_subproc.assert_called_once()
        mock_proc.kill.assert_called_once()
        assert storage.get_process(555) is None


def test_cleanup_all_active_processes(storage: SessionStorage) -> None:
    proc1 = MagicMock()
    proc1.pid = 1001
    proc1.poll.return_value = None

    proc2 = MagicMock()
    proc2.pid = 1002
    proc2.poll.return_value = 0  # already stopped

    storage.register_process(1, proc1)
    storage.register_process(2, proc2)

    with (
        patch("sys.platform", "linux"),
        patch("os.getpgid", return_value=1001, create=True),
        patch("os.killpg", create=True),
    ):
        storage.cleanup_all_active_processes()
        proc1.terminate.assert_called_once()
        proc2.terminate.assert_not_called()
        assert len(storage.active_processes) == 0


def test_run_antigravity_stream_registers_active_process(
    tmp_path: Path,
    storage: SessionStorage,
) -> None:
    agy_mock = str(tmp_path / "agy")
    with open(agy_mock, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(agy_mock, 0o755)  # noqa: S103

    mock_process = MagicMock()
    mock_process.pid = 5555

    registered_during_run = False

    def fake_readline():
        nonlocal registered_during_run
        if storage.get_process(7788) is not None:
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
                storage=storage,
            )

    assert registered_during_run is True
    assert storage.get_process(7788) is None


def test_atomic_session_persistence_concurrent(tmp_path: Path) -> None:
    import concurrent.futures
    from app.core.storage import SessionStorage

    session_file = str(tmp_path / "concurrent_sessions.json")
    storage = SessionStorage(file_path=session_file)

    def worker(idx: int) -> None:
        storage.set_active_session(idx, f"conv-{idx}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, i) for i in range(10)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    new_storage = SessionStorage(file_path=session_file)
    assert len(new_storage.active_conversations) == 10
    for i in range(10):
        assert new_storage.get_active_session(i) == f"conv-{i}"


def test_format_tool_step_description() -> None:
    # run_command active
    cmd_act = stream_runner.format_tool_step_description(
        "run_command",
        {"CommandLine": "pytest tests/ -v"},
        done=False,
    )
    assert "Running command:" in cmd_act
    assert "<code>pytest tests/ -v</code>" in cmd_act

    # run_command done with duration
    cmd_done = stream_runner.format_tool_step_description(
        "run_command",
        {"CommandLine": "pytest"},
        done=True,
        duration_seconds=1.456,
    )
    assert "Ran <code>pytest</code>" in cmd_done
    assert "(1.46s)" in cmd_done

    # Special character escaping in command line
    cmd_esc = stream_runner.format_tool_step_description(
        "run_command",
        {"CommandLine": "echo '<tag>' > out.txt & cat"},
        done=True,
    )
    assert "&lt;tag&gt;" in cmd_esc
    assert "&amp;" in cmd_esc

    # view_file
    vf_act = stream_runner.format_tool_step_description(
        "view_file",
        {"AbsolutePath": "/home/mars/project/bot.py"},
        done=False,
    )
    assert "Reading <code>bot.py</code>" in vf_act

    vf_done = stream_runner.format_tool_step_description(
        "view_file",
        {"TargetFile": "/path/to/config.py"},
        done=True,
        duration_seconds=0.03,
    )
    assert "Read <code>config.py</code>" in vf_done
    assert "(0.03s)" in vf_done

    # replace_file_content and write_to_file
    ed_done = stream_runner.format_tool_step_description(
        "replace_file_content",
        {"TargetFile": "/path/to/stream.py"},
        done=True,
    )
    assert "Edited <code>stream.py</code>" in ed_done

    wr_act = stream_runner.format_tool_step_description(
        "write_to_file",
        {"TargetFile": "/path/to/new.py"},
        done=False,
    )
    assert "Writing <code>new.py</code>" in wr_act

    # list_dir
    ld_done = stream_runner.format_tool_step_description(
        "list_dir",
        {"DirectoryPath": "/path/to/handlers/"},
        done=True,
        duration_seconds=0.01,
    )
    assert "Listed directory <code>handlers/</code>" in ld_done

    # grep_search
    grep_done = stream_runner.format_tool_step_description(
        "grep_search",
        {"Query": "def run_antigravity"},
        done=True,
    )
    assert "Searched <code>def run_antigravity</code>" in grep_done

    # search_web
    web_act = stream_runner.format_tool_step_description(
        "search_web",
        {"query": "aiogram 3 docs"},
        done=False,
    )
    assert "Searching web: <code>aiogram 3 docs</code>" in web_act

    # fallback toolAction
    fb_done = stream_runner.format_tool_step_description(
        "custom_tool",
        {"toolAction": "Optimizing database"},
        done=True,
        duration_seconds=2.5,
    )
    assert "Optimizing database" in fb_done
    assert "(2.50s)" in fb_done


def test_format_progress_card() -> None:
    # 1. Initial thinking without steps
    card_thk = stream_runner.format_progress_card(
        elapsed_seconds=3,
        completed_steps=[],
        active_activity="thinking...",
    )
    assert "🧠 <b>Thinking...</b> <i>(3s)</i>" in card_thk

    # 2. Drafting without steps
    card_draft = stream_runner.format_progress_card(
        elapsed_seconds=7,
        completed_steps=[],
        active_activity="drafting response...",
    )
    assert "✍️ <b>Drafting response...</b> <i>(7s)</i>" in card_draft

    # 3. Running tool without completed steps
    card_tool_only = stream_runner.format_progress_card(
        elapsed_seconds=2,
        completed_steps=[],
        active_activity="Running command: <code>pwd</code>",
        spinner_frame="⠋",
    )
    assert "⚡ <b>Working...</b> <i>(2s)</i>" in card_tool_only
    assert "⠋ <i>Running command: <code>pwd</code></i>" in card_tool_only

    # 4. With completed steps and active tool
    steps = [
        "Listed directory <code>handlers/</code> <i>(0.01s)</i>",
        "Read <code>bot.py</code> <i>(0.02s)</i>",
    ]
    card_multi = stream_runner.format_progress_card(
        elapsed_seconds=5,
        completed_steps=steps,
        active_activity="Running command: <code>pytest</code>",
        spinner_frame="⠙",
    )
    assert "⚡ <b>Working...</b> <i>(5s)</i>" in card_multi
    assert "✓ Listed directory <code>handlers/</code>" in card_multi
    assert "✓ Read <code>bot.py</code>" in card_multi
    assert "⠙ <i>Running command: <code>pytest</code></i>" in card_multi

    # 5. When drafting response after steps
    card_drafting_after_steps = stream_runner.format_progress_card(
        elapsed_seconds=10,
        completed_steps=steps,
        active_activity="Drafting response...",
    )
    assert "✍️ <i>Drafting response...</i>" in card_drafting_after_steps

    # 6. Truncation when more than 5 steps
    many_steps = [f"Step {i}" for i in range(1, 9)]
    card_many = stream_runner.format_progress_card(
        elapsed_seconds=20,
        completed_steps=many_steps,
        active_activity="done",
    )
    assert "<i>... 4 earlier steps</i>" in card_many
    assert "✓ Step 8" in card_many
    assert "✓ Step 5" in card_many
    assert "✓ Step 1" not in card_many

    # 7. Card strictly bounded under Telegram limits even with giant steps
    giant_steps = ["G" * 500 for _ in range(10)]
    card_giant = stream_runner.format_progress_card(
        elapsed_seconds=10,
        completed_steps=giant_steps,
        active_activity="A" * 500,
    )
    assert len(card_giant) <= 3500


def test_stream_progress_tracker() -> None:
    messages = []

    def on_progress(text: str) -> None:
        messages.append(text)

    tracker = stream_runner.StreamProgressTracker(
        progress_callback=on_progress,
        throttle_interval=0.01,
    )
    try:
        tracker.set_activity("Running command: <code>pwd</code>")
        time.sleep(0.015)
        tracker.add_completed_step("Ran <code>pwd</code>")
        time.sleep(0.015)
        tracker.set_activity("Drafting response...")
        tracker.flush(force=True)

        assert len(messages) >= 2
        # Check that steps appear in flushed cards
        last_msg = messages[-1]
        assert "Ran <code>pwd</code>" in last_msg
        assert "Drafting response..." in last_msg
    finally:
        tracker.stop()


def test_run_antigravity_stream_multi_step_flow(
    tmp_path: Path,
    storage: SessionStorage,
) -> None:
    agy_mock = str(tmp_path / "agy")
    with open(agy_mock, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(agy_mock, 0o755)  # noqa: S103

    events = [
        json.dumps({"event": "init", "conversation_id": "conv-multi-step"}),
        # Step 1: Tool active
        json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "step_index": 1,
                    "state": "ACTIVE",
                    "step_type": "tool",
                    "tool_name": "run_command",
                    "tool_info": {
                        "name": "run_command",
                        "parameters": {"CommandLine": "git status"},
                    },
                },
            },
        ),
        # Step 1: Tool done
        json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "step_index": 1,
                    "state": "DONE",
                    "step_type": "tool",
                    "tool_name": "run_command",
                    "duration_seconds": 0.05,
                    "tool_info": {
                        "name": "run_command",
                        "parameters": {"CommandLine": "git status"},
                        "output": "clean",
                    },
                },
            },
        ),
        # Step 2: Agent drafting text
        json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "step_index": 2,
                    "state": "ACTIVE",
                    "step_type": "agent_response",
                    "text_delta": "Everything is up to date!",
                },
            },
        ),
        # Result
        json.dumps(
            {
                "event": "result",
                "result": {
                    "response": "Everything is up to date!",
                    "usage": {"total_tokens": 80},
                },
            },
        ),
    ]

    mock_process = MagicMock()
    mock_process.stdout.readline.side_effect = [e + "\n" for e in events] + [""]
    mock_process.wait.return_value = 0

    captured_progress = []

    def on_progress(text: str) -> None:
        captured_progress.append(text)

    with patch.object(config, "AGY_PATH", agy_mock):
        with patch("subprocess.Popen", return_value=mock_process):
            with patch.object(storage, "save"):
                resp, usage, files = stream_runner.run_antigravity_stream(
                    "Check git status",
                    12345,
                    workspace_dir=str(tmp_path),
                    progress_callback=on_progress,
                    storage=storage,
                )

                assert resp == "Everything is up to date!"
                assert usage.get("total_tokens") == 80
                assert "steps" in usage
                assert len(usage["steps"]) == 1
                assert "git status" in usage["steps"][0]
                assert len(captured_progress) > 0


def test_persona_prompt_injected_only_on_first_turn(
    tmp_path: Path,
    storage: SessionStorage,
) -> None:
    agy_mock = str(tmp_path / "agy")
    with open(agy_mock, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(agy_mock, 0o755)  # noqa: S103

    chat_id = 889911

    mock_process = MagicMock()
    mock_process.stdout.readline.side_effect = [
        json.dumps({"event": "init", "conversation_id": "conv-test-123"}) + "\n",
        json.dumps({"event": "result", "result": {"response": "Done"}}) + "\n",
        "",
    ]
    mock_process.wait.return_value = 0

    with patch.object(config, "AGY_PATH", agy_mock):
        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            with patch.object(storage, "save"):
                # Turn 1: New conversation
                stream_runner.run_antigravity_stream(
                    "First prompt",
                    chat_id,
                    workspace_dir=str(tmp_path),
                    storage=storage,
                )
                args, kwargs = mock_popen.call_args
                cmd = args[0]
                p_idx = cmd.index("-p")
                turn1_prompt = cmd[p_idx + 1]

                assert "STYLE GUIDELINES" in turn1_prompt
                assert "First prompt" in turn1_prompt
                assert storage.get_active_session(chat_id) == "conv-test-123"
                assert kwargs.get("encoding") == "utf-8"
                assert kwargs.get("errors") == "replace"

                # Turn 2: Follow-up in existing conversation
                mock_process.stdout.readline.side_effect = [
                    json.dumps(
                        {"event": "result", "result": {"response": "Follow-up done"}},
                    )
                    + "\n",
                    "",
                ]
                stream_runner.run_antigravity_stream(
                    "Second prompt",
                    chat_id,
                    workspace_dir=str(tmp_path),
                    storage=storage,
                )
                args2, kwargs2 = mock_popen.call_args
                cmd2 = args2[0]
                p_idx2 = cmd2.index("-p")
                turn2_prompt = cmd2[p_idx2 + 1]

                assert "STYLE GUIDELINES" not in turn2_prompt
                assert "TARGET WORKSPACE" in turn2_prompt
                assert "Second prompt" in turn2_prompt
                assert "--conversation" in cmd2
                assert "conv-test-123" in cmd2

                # Reset session -> Turn 3 should be treated as a new conversation again
                storage.reset_session(chat_id)
                assert storage.get_active_session(chat_id) is None

                mock_process.stdout.readline.side_effect = [
                    json.dumps({"event": "init", "conversation_id": "conv-test-456"})
                    + "\n",
                    json.dumps(
                        {
                            "event": "result",
                            "result": {"response": "Fresh session done"},
                        },
                    )
                    + "\n",
                    "",
                ]
                stream_runner.run_antigravity_stream(
                    "Third prompt in new session",
                    chat_id,
                    workspace_dir=str(tmp_path),
                    storage=storage,
                )
                args3, kwargs3 = mock_popen.call_args
                cmd3 = args3[0]
                p_idx3 = cmd3.index("-p")
                turn3_prompt = cmd3[p_idx3 + 1]

                assert "STYLE GUIDELINES" in turn3_prompt
                assert "Third prompt in new session" in turn3_prompt
