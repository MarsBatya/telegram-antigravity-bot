import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any

from app.core import config

SESSION_FILE: str = getattr(
    config,
    "SESSION_FILE",
    str(Path(__file__).resolve().parent.parent.parent / "sessions.json"),
)


def _terminate_process_and_group(proc: subprocess.Popen[Any]) -> None:
    """Terminates or kills a subprocess and its entire process group safely
    across both POSIX (Linux/macOS) and Windows.
    """
    pid = getattr(proc, "pid", None)
    if sys.platform == "win32":
        if isinstance(pid, int):
            with contextlib.suppress(Exception):
                import psutil

                parent = psutil.Process(pid)
                for child in parent.children(recursive=True):
                    with contextlib.suppress(Exception):
                        child.kill()
                parent.kill()
            with contextlib.suppress(Exception):
                subprocess.run(  # noqa: S603
                    ["taskkill", "/F", "/T", "/PID", str(pid)],  # noqa: S607
                    capture_output=True,
                    check=False,
                )
        with contextlib.suppress(Exception):
            proc.kill()
        return

    # POSIX systems (Linux, macOS, BSD)
    if isinstance(pid, int):
        with contextlib.suppress(Exception):
            if hasattr(os, "getpgid") and hasattr(os, "killpg"):
                pgid = os.getpgid(pid)
                sig_term = getattr(signal, "SIGTERM", 15)
                os.killpg(pgid, sig_term)
    with contextlib.suppress(Exception):
        proc.terminate()
    time.sleep(0.3)
    if proc.poll() is None:
        if isinstance(pid, int):
            with contextlib.suppress(Exception):
                if hasattr(os, "getpgid") and hasattr(os, "killpg"):
                    pgid = os.getpgid(pid)
                    sig_kill = getattr(signal, "SIGKILL", 9)
                    os.killpg(pgid, sig_kill)
        with contextlib.suppress(Exception):
            proc.kill()


def calculate_session_tokens(conv_id: str, brain_dir: str | None = None) -> int:
    """Calculates total tokens accumulated in a conversation session
    from transcript.jsonl.
    """
    target_brain = Path(
        brain_dir
        or getattr(
            config,
            "BRAIN_DIR",
            str(Path.home() / ".gemini" / "antigravity-cli" / "brain"),
        ),
    )
    transcript_file = (
        target_brain / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
    )
    if not transcript_file.exists():
        return 0

    total_tokens = 0
    try:
        with open(transcript_file, "r", encoding="utf-8") as f:
            for line in f:
                with contextlib.suppress(Exception):
                    data = json.loads(line)
                    if data.get("type") == "PLANNER_RESPONSE":
                        usage = data.get("usage")
                        if isinstance(usage, dict) and "total_tokens" in usage:
                            total_tokens += usage.get("total_tokens", 0)
    except Exception as e:
        print(f"[ERROR] Failed to calculate session tokens: {e}")
    return total_tokens


class SessionStorage:
    """Thread-safe, file-backed session, workspace, setting, and process storage."""

    def __init__(self, file_path: str | None = None) -> None:
        self.file_path: str = file_path or getattr(config, "SESSION_FILE", SESSION_FILE)
        self.active_conversations: dict[int, str | bool] = {}
        self.active_workspaces: dict[int, str] = {}
        self.active_settings: dict[int, dict[str, str]] = {}
        self.chat_token_usage: dict[int, dict[str, int]] = {}
        self.active_processes: dict[int, subprocess.Popen[Any]] = {}
        self.chat_locks: dict[int, threading.Lock] = {}
        self._file_lock: threading.Lock = threading.Lock()
        self._state_lock: threading.Lock = threading.Lock()
        self.load(self.file_path)

    @property
    def conversations(self) -> dict[int, str | bool]:
        with self._state_lock:
            return self.active_conversations

    @conversations.setter
    def conversations(self, value: dict[int, str | bool]) -> None:
        with self._state_lock:
            self.active_conversations = value

    @property
    def workspaces(self) -> dict[int, str]:
        with self._state_lock:
            return self.active_workspaces

    @workspaces.setter
    def workspaces(self, value: dict[int, str]) -> None:
        with self._state_lock:
            self.active_workspaces = value

    @property
    def settings(self) -> dict[int, dict[str, str]]:
        with self._state_lock:
            return self.active_settings

    @settings.setter
    def settings(self, value: dict[int, dict[str, str]]) -> None:
        with self._state_lock:
            self.active_settings = value

    @property
    def token_usage(self) -> dict[int, dict[str, int]]:
        with self._state_lock:
            return self.chat_token_usage

    @token_usage.setter
    def token_usage(self, value: dict[int, dict[str, int]]) -> None:
        with self._state_lock:
            self.chat_token_usage = value

    @property
    def processes(self) -> dict[int, subprocess.Popen[Any]]:
        with self._state_lock:
            return self.active_processes

    @processes.setter
    def processes(self, value: dict[int, subprocess.Popen[Any]]) -> None:
        with self._state_lock:
            self.active_processes = value

    @property
    def locks(self) -> dict[int, threading.Lock]:
        with self._state_lock:
            return self.chat_locks

    @locks.setter
    def locks(self, value: dict[int, threading.Lock]) -> None:
        with self._state_lock:
            self.chat_locks = value

    def load(self, file_path: str | None = None) -> None:
        """Loads conversation mapping, workspaces, and chat settings
        from persistent storage.
        """
        target_file = file_path or self.file_path
        loaded_convs: dict[int, str | bool] = {}
        loaded_workspaces: dict[int, str] = {}
        loaded_settings: dict[int, dict[str, str]] = {}
        with self._file_lock:
            if os.path.exists(target_file):
                try:
                    with open(target_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        convs = data.get("conversations", {})
                        workspaces = data.get("workspaces", {})
                        settings = data.get("settings", {})
                        if not convs and not workspaces and isinstance(data, dict):
                            convs = data

                        loaded_convs = {int(k): v for k, v in convs.items()}
                        loaded_workspaces = {int(k): v for k, v in workspaces.items()}
                        loaded_settings = {int(k): v for k, v in settings.items()}
                except Exception as e:
                    print(f"[ERROR] Loading sessions.json: {e}")

        with self._state_lock:
            self.active_conversations = loaded_convs
            self.active_workspaces = loaded_workspaces
            self.active_settings = loaded_settings

    def save(self, file_path: str | None = None) -> None:
        """Saves conversation mapping, workspaces, and settings
        to persistent storage atomically.
        """
        target_file = file_path or self.file_path
        with self._file_lock:
            with self._state_lock:
                convs_copy = dict(self.active_conversations)
                workspaces_copy = dict(self.active_workspaces)
                settings_copy = {k: dict(v) for k, v in self.active_settings.items()}

            temp_file: Path | None = None
            try:
                target_path = Path(target_file).resolve()
                target_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "conversations": {str(k): v for k, v in convs_copy.items()},
                    "workspaces": {str(k): v for k, v in workspaces_copy.items()},
                    "settings": {str(k): v for k, v in settings_copy.items()},
                }
                temp_file = target_path.with_name(
                    f"{target_path.name}.tmp.{os.getpid()}.{threading.get_ident()}",
                )
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                # Retry loop handling transient file locks
                # (common on Windows antivirus / indexer)
                for attempt in range(3):
                    try:
                        os.replace(temp_file, target_path)
                        break
                    except PermissionError:
                        if attempt == 2:
                            raise
                        time.sleep(0.05)
            except Exception as e:
                print(f"[ERROR] Saving sessions.json: {e}")
                if temp_file is not None:
                    with contextlib.suppress(OSError):
                        temp_file.unlink(missing_ok=True)

    def get_setting(
        self,
        chat_id: int,
        key: str,
        default: str | None = None,
    ) -> str | None:
        with self._state_lock:
            if chat_id not in self.active_settings:
                self.active_settings[chat_id] = {
                    "model": config.DEFAULT_MODEL,
                    "effort": config.DEFAULT_EFFORT,
                    "mode": config.DEFAULT_MODE,
                }
            return self.active_settings[chat_id].get(key, default)

    def set_setting(self, chat_id: int, key: str, value: str) -> None:
        with self._state_lock:
            if chat_id not in self.active_settings:
                self.active_settings[chat_id] = {
                    "model": config.DEFAULT_MODEL,
                    "effort": config.DEFAULT_EFFORT,
                    "mode": config.DEFAULT_MODE,
                }
            self.active_settings[chat_id][key] = value
        self.save()

    def get_workspace(self, chat_id: int) -> str:
        with self._state_lock:
            return self.active_workspaces.get(chat_id) or config.DEFAULT_WORKSPACE

    def set_workspace(self, chat_id: int, workspace_path: str) -> None:
        with self._state_lock:
            self.active_workspaces[chat_id] = os.path.abspath(workspace_path)
        self.save()

    def get_lock(self, chat_id: int) -> threading.Lock:
        with self._state_lock:
            if chat_id not in self.chat_locks:
                self.chat_locks[chat_id] = threading.Lock()
            return self.chat_locks[chat_id]

    def get_chat_lock(self, chat_id: int) -> threading.Lock:
        return self.get_lock(chat_id)

    def register_process(self, chat_id: int, proc: subprocess.Popen[Any]) -> None:
        with self._state_lock:
            self.active_processes[chat_id] = proc

    def unregister_process(self, chat_id: int) -> subprocess.Popen[Any] | None:
        with self._state_lock:
            return self.active_processes.pop(chat_id, None)

    def get_process(self, chat_id: int) -> subprocess.Popen[Any] | None:
        with self._state_lock:
            return self.active_processes.get(chat_id)

    def get_token_usage(self, chat_id: int) -> dict[str, int]:
        with self._state_lock:
            if chat_id not in self.chat_token_usage:
                self.chat_token_usage[chat_id] = {
                    "session_tokens": 0,
                    "total_tokens": 0,
                }

            conv_id = self.active_conversations.get(chat_id)
            need_calc = (
                isinstance(conv_id, str)
                and conv_id
                and self.chat_token_usage[chat_id]["session_tokens"] == 0
            )

        if need_calc and isinstance(conv_id, str):
            tokens = calculate_session_tokens(conv_id)
            with self._state_lock:
                if chat_id in self.chat_token_usage:
                    self.chat_token_usage[chat_id]["session_tokens"] = tokens

        with self._state_lock:
            return dict(self.chat_token_usage[chat_id])

    def get_active_session(self, chat_id: int) -> str | bool | None:
        with self._state_lock:
            return self.active_conversations.get(chat_id)

    def set_active_session(self, chat_id: int, conv_id: str | bool) -> None:
        with self._state_lock:
            self.active_conversations[chat_id] = conv_id
            if chat_id not in self.chat_token_usage:
                self.chat_token_usage[chat_id] = {
                    "session_tokens": 0,
                    "total_tokens": 0,
                }
        self.save()
        if isinstance(conv_id, str) and conv_id:
            tokens = calculate_session_tokens(conv_id)
            with self._state_lock:
                if chat_id in self.chat_token_usage:
                    self.chat_token_usage[chat_id]["session_tokens"] = tokens

    def reset_session(self, chat_id: int) -> None:
        with self._state_lock:
            self.active_conversations.pop(chat_id, None)
            if chat_id in self.chat_token_usage:
                self.chat_token_usage[chat_id]["session_tokens"] = 0
        self.save()

    def cancel_chat_process(self, chat_id: int) -> bool:
        with self._state_lock:
            proc = self.active_processes.get(chat_id)
        if proc and proc.poll() is None:
            try:
                _terminate_process_and_group(proc)
                with self._state_lock:
                    self.active_processes.pop(chat_id, None)
                return True
            except Exception as e:
                print(f"[ERROR] Failed to kill process for chat {chat_id}: {e}")
                return False
        return False

    def cleanup_all_active_processes(self) -> None:
        with self._state_lock:
            procs = list(self.active_processes.items())
            self.active_processes.clear()
        for chat_id, proc in procs:
            try:
                if proc.poll() is None:
                    _terminate_process_and_group(proc)
            except Exception as e:
                print(f"[ERROR] Failed to cleanup process for chat {chat_id}: {e}")
