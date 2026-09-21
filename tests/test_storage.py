import json
import os
import threading
from unittest.mock import MagicMock

from app.core import config
from app.core.storage import (
    SessionStorage,
    _terminate_process_and_group,
    calculate_session_tokens,
)


def test_session_storage_init(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "sessions_test.json")
    storage = SessionStorage(file_path=test_file)
    assert storage.file_path == test_file
    assert storage.active_conversations == {}
    assert storage.active_workspaces == {}
    assert storage.active_settings == {}
    assert storage.chat_token_usage == {}
    assert storage.active_processes == {}
    assert storage.chat_locks == {}


def test_session_storage_independence(tmp_path: os.PathLike[str]) -> None:
    file_a = os.path.join(tmp_path, "a.json")
    file_b = os.path.join(tmp_path, "b.json")
    storage_a = SessionStorage(file_path=file_a)
    storage_b = SessionStorage(file_path=file_b)

    storage_a.set_active_session(1, "conv_1")
    storage_a.set_workspace(1, os.path.join(tmp_path, "workspace_a"))
    storage_a.set_setting(1, "model", "gemini-ultra")

    assert storage_b.get_active_session(1) is None
    assert storage_b.get_workspace(1) == config.DEFAULT_WORKSPACE
    assert storage_b.get_setting(1, "model") == config.DEFAULT_MODEL


def test_session_storage_save_and_load(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "saved_sessions.json")
    storage = SessionStorage(file_path=test_file)

    storage.set_active_session(100, "conv-100")
    storage.set_workspace(100, "/home/user/project")
    storage.set_setting(100, "model", "claude-3-5-sonnet")
    storage.set_setting(100, "effort", "high")
    storage.set_setting(100, "mode", "smash")

    assert os.path.exists(test_file)

    storage_loaded = SessionStorage(file_path=test_file)
    assert storage_loaded.get_active_session(100) == "conv-100"
    assert storage_loaded.get_workspace(100) == "/home/user/project"
    assert storage_loaded.get_setting(100, "model") == "claude-3-5-sonnet"
    assert storage_loaded.get_setting(100, "effort") == "high"
    assert storage_loaded.get_setting(100, "mode") == "smash"


def test_session_storage_legacy_json_load(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "legacy.json")
    legacy_data = {"123": "legacy-session-123", "456": "legacy-session-456"}
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    storage = SessionStorage(file_path=test_file)
    assert storage.get_active_session(123) == "legacy-session-123"
    assert storage.get_active_session(456) == "legacy-session-456"


def test_session_storage_token_usage_and_reset(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "sessions_token.json")
    storage = SessionStorage(file_path=test_file)

    storage.set_active_session(42, "session-42")
    usage = storage.get_token_usage(42)
    assert usage == {"session_tokens": 0, "total_tokens": 0}

    storage.reset_session(42)
    assert storage.get_active_session(42) is None


def test_session_storage_chat_locks(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "sessions_locks.json")
    storage = SessionStorage(file_path=test_file)

    lock1 = storage.get_lock(99)
    lock2 = storage.get_lock(99)
    lock3 = storage.get_lock(100)

    assert lock1 is lock2
    assert lock1 is not lock3


def test_session_storage_process_management(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "sessions_proc.json")
    storage = SessionStorage(file_path=test_file)

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None

    storage.register_process(555, mock_proc)
    assert storage.get_process(555) is mock_proc

    storage.unregister_process(555)
    assert storage.get_process(555) is None


def test_session_storage_cancel_chat_process(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "sessions_cancel.json")
    storage = SessionStorage(file_path=test_file)

    mock_proc = MagicMock()
    mock_proc.pid = 9999
    mock_proc.poll.return_value = None

    storage.register_process(777, mock_proc)
    result = storage.cancel_chat_process(777)

    assert result is True
    assert storage.get_process(777) is None
    mock_proc.terminate.assert_called_once()


def test_session_storage_thread_safety(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "sessions_thread.json")
    storage = SessionStorage(file_path=test_file)

    def worker(worker_id: int) -> None:
        for i in range(6):
            chat_id = worker_id * 100 + i
            storage.set_active_session(chat_id, f"conv-{chat_id}")
            storage.set_setting(chat_id, "mode", config.DEFAULT_MODE)
            storage.set_workspace(chat_id, os.path.join(tmp_path, f"ws_{chat_id}"))
            _ = storage.get_active_session(chat_id)
            _ = storage.get_setting(chat_id, "mode")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify all 30 sessions were set and saved cleanly
    storage_reloaded = SessionStorage(file_path=test_file)
    assert len(storage_reloaded.active_conversations) == 30


def test_terminate_process_and_group() -> None:
    mock_proc = MagicMock()
    mock_proc.pid = 54321
    mock_proc.poll.return_value = None

    _terminate_process_and_group(mock_proc)
    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()


def test_calculate_session_tokens_missing(tmp_path: os.PathLike[str]) -> None:
    tokens = calculate_session_tokens("non-existent-conv", brain_dir=str(tmp_path))
    assert tokens == 0


def test_calculate_session_tokens_valid(tmp_path: os.PathLike[str]) -> None:
    conv_id = "test-conv-tokens"
    logs_dir = os.path.join(tmp_path, conv_id, ".system_generated", "logs")
    os.makedirs(logs_dir, exist_ok=True)
    transcript_file = os.path.join(logs_dir, "transcript.jsonl")

    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "type": "PLANNER_RESPONSE",
                    "usage": {"total_tokens": 150},
                },
            )
            + "\n",
        )
        f.write(
            json.dumps(
                {
                    "type": "USER_INPUT",
                    "content": "hello",
                },
            )
            + "\n",
        )
        f.write(
            json.dumps(
                {
                    "type": "PLANNER_RESPONSE",
                    "usage": {"total_tokens": 250},
                },
            )
            + "\n",
        )

    tokens = calculate_session_tokens(conv_id, brain_dir=str(tmp_path))
    assert tokens == 400


def test_session_storage_cleanup_all_processes(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "sessions_cleanup.json")
    storage = SessionStorage(file_path=test_file)

    mock_proc1 = MagicMock()
    mock_proc1.pid = 1111
    mock_proc1.poll.return_value = None

    mock_proc2 = MagicMock()
    mock_proc2.pid = 2222
    mock_proc2.poll.return_value = 0

    storage.register_process(1, mock_proc1)
    storage.register_process(2, mock_proc2)

    storage.cleanup_all_active_processes()
    mock_proc1.terminate.assert_called_once()
    mock_proc2.terminate.assert_not_called()
    assert storage.active_processes == {}


def test_session_storage_boolean_session(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "sessions_bool.json")
    storage = SessionStorage(file_path=test_file)

    storage.set_active_session(888, True)
    assert storage.get_active_session(888) is True
    usage = storage.get_token_usage(888)
    assert usage["session_tokens"] == 0


def test_session_storage_save_retry_on_permission_error(
    tmp_path: os.PathLike[str],
) -> None:
    from unittest.mock import patch

    test_file = os.path.join(tmp_path, "sessions_retry.json")
    storage = SessionStorage(file_path=test_file)

    attempts = 0
    orig_replace = os.replace

    def mock_replace(src: str, dst: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("Access is denied (transient Windows lock)")
        orig_replace(src, dst)

    with patch("os.replace", side_effect=mock_replace):
        storage.set_active_session(123, "conv-retry")

    assert attempts == 2
    assert os.path.exists(test_file)
    assert storage.get_active_session(123) == "conv-retry"


def test_session_storage_save_failure_cleans_temp_file(
    tmp_path: os.PathLike[str],
) -> None:
    from unittest.mock import patch

    test_file = os.path.join(tmp_path, "sessions_fail.json")
    storage = SessionStorage(file_path=test_file)

    with patch("os.replace", side_effect=PermissionError("Persistent lock")):
        storage.set_active_session(456, "conv-fail")

    # Verify no dangling .tmp files remain in directory
    remaining_files = os.listdir(tmp_path)
    tmp_files = [f for f in remaining_files if ".tmp." in f]
    assert len(tmp_files) == 0


def test_session_storage_pending_files(tmp_path: os.PathLike[str]) -> None:
    test_file = os.path.join(tmp_path, "sessions_pending.json")
    storage = SessionStorage(file_path=test_file)

    dl_test = os.path.join(tmp_path, "downloads", "test.txt")
    ws_test = os.path.join(tmp_path, "workspace", "test.txt")
    storage.add_pending_file(100, "test.txt", dl_test, 1024)
    pending = storage.get_pending_files(100)
    assert len(pending) == 1
    assert pending[0]["file_name"] == "test.txt"
    assert pending[0]["saved_to_workspace"] is False

    # Mark saved to workspace
    updated = storage.mark_file_saved_to_workspace(
        100,
        dl_test,
        ws_test,
    )
    assert updated is True
    pending_after = storage.get_pending_files(100)
    assert pending_after[0]["saved_to_workspace"] is True
    assert pending_after[0]["workspace_path"] == ws_test

    # Persistence load
    storage_loaded = SessionStorage(file_path=test_file)
    pending_loaded = storage_loaded.get_pending_files(100)
    assert len(pending_loaded) == 1
    assert pending_loaded[0]["workspace_path"] == ws_test

    # Get and clear
    cleared = storage_loaded.get_and_clear_pending_files(100)
    assert len(cleared) == 1
    assert len(storage_loaded.get_pending_files(100)) == 0

    # Reset session clears pending files
    dl_foo = os.path.join(tmp_path, "downloads", "foo.py")
    storage.add_pending_file(200, "foo.py", dl_foo, 2048)
    assert len(storage.get_pending_files(200)) == 1
    storage.reset_session(200)
    assert len(storage.get_pending_files(200)) == 0
