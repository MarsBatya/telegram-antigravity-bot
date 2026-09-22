import base64
import contextlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import config
from app.core.model_manager import ModelManager
from app.core.storage import (
    SessionStorage,
    _terminate_process_and_group,
)
from app.core.storage import (
    calculate_session_tokens as calculate_session_tokens,
)
from app.utils.helpers import make_progress_bar

logger = logging.getLogger(__name__)

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
DEFAULT_BRAIN_DIR = str(Path.home() / ".gemini" / "antigravity-cli" / "brain")
DEFAULT_OAUTH_TOKEN_PATH = str(
    Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token",
)


def parse_reset_time(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = dt - now
        secs = int(diff.total_seconds())
        if secs <= 0:
            return "Refreshes soon"
        hours = secs // 3600
        mins = (secs % 3600) // 60
        if hours > 24:
            days = hours // 24
            h = hours % 24
            return f"Refreshes in {days}d {h}h"
        if hours > 0:
            return f"Refreshes in {hours}h {mins}m"
        return f"Refreshes in {mins}m"
    except Exception:
        return ""


def fetch_live_user_quota_summary(token_file: str | None = None) -> str:
    """Fetches real-time Models & Quota summary directly from Google Cloud
    Code PA API.
    """
    target_token_file = token_file or getattr(
        config,
        "OAUTH_TOKEN_PATH",
        DEFAULT_OAUTH_TOKEN_PATH,
    )
    if not os.path.exists(target_token_file):
        if getattr(config, "GEMINI_API_KEY", None) or os.getenv("GEMINI_API_KEY"):
            return (
                "ℹ️ <b>Live Quota Information:</b>\n"
                "<i>Live Cloud Code quota is only available with OAuth "
                "token authentication. You are currently connected via "
                "GEMINI_API_KEY (Gemini models only).</i>"
            )
        return "⚠️ <b>OAuth token file not found on server.</b>"

    try:
        with open(target_token_file, "r", encoding="utf-8") as f:
            token_data = json.load(f)

        access_token = token_data.get("token", {}).get("access_token")
        id_token = token_data.get("id_token", "")

        if not access_token:
            return "⚠️ <b>Invalid OAuth access token.</b>"

        email = "Unknown"
        if id_token and "." in id_token:
            with contextlib.suppress(Exception):
                payload_b64 = id_token.split(".")[1]
                payload_b64 += "=" * (-len(payload_b64) % 4)
                payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
                email = payload.get("email", email)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity-cli/1.1.9",
        }

        base_url = getattr(
            config,
            "CLOUDCODE_BASE_URL",
            "https://daily-cloudcode-pa.googleapis.com",
        ).rstrip("/")
        url = f"{base_url}/v1internal:retrieveUserQuotaSummary"
        req = urllib.request.Request(  # noqa: S310
            url,
            data=b"{}",
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))

        output = []
        output.append("└ <b>Models & Quota</b>")
        output.append(f"  <b>Account:</b> <code>{email}</code>\n")

        for group in data.get("groups", []):
            g_name = group.get("displayName", "").upper()
            g_desc = group.get("description", "")
            output.append(f"<b>{g_name}</b>")
            output.append(f"  <i>{g_desc}</i>\n")

            for bucket in group.get("buckets", []):
                b_name = bucket.get("displayName", "")
                disabled = bucket.get("disabled", False)
                rem_frac = bucket.get("remainingFraction", 0.0)
                pct = rem_frac * 100.0
                reset_str = parse_reset_time(bucket.get("resetTime"))
                b_desc = bucket.get("description", "")

                output.append(f"  <b>{b_name}</b>")
                if disabled:
                    output.append("    <code>[Disabled]</code>")
                    output.append(f"    <i>{b_desc}</i>\n")
                else:
                    output.append(f"    <code>{make_progress_bar(pct, 20)}</code>")
                    output.append(f"    {pct:.0f}% remaining · {reset_str}\n")

        return "\n".join(output)
    except Exception as e:
        return f"⚠️ <b>Failed to fetch live quota data:</b> <code>{str(e)}</code>"


def fetch_available_models_live(
    token_file: str | None = None,
    model_manager: ModelManager | None = None,
) -> list[dict[str, Any]]:
    """Fetches list of active models directly from agy CLI or Google Cloud Code API."""
    mgr = model_manager if model_manager is not None else ModelManager()
    return mgr.get_available_models(token_file=token_file)


def fetch_bot_logs(lines_count: int = 30) -> str:
    """Fetches systemd service logs or local file logs for antigravity-bot."""
    journalctl_bin = shutil.which("journalctl") or ("/usr/bin/journalctl" if sys.platform != "win32" else None)
    if journalctl_bin:
        try:
            res = subprocess.run(  # noqa: S603
                [
                    journalctl_bin,
                    "-u",
                    "telegram-antigravity-bot",
                    "-u",
                    "antigravity-bot",
                    "-n",
                    str(lines_count),
                    "--no-pager",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.stdout and "-- No entries --" not in res.stdout:
                return res.stdout
            if res.stdout == "":
                return "📜 No recent logs."
        except Exception as e:
            if sys.platform != "win32":
                return f"❌ Failed to fetch logs: {e}"

    # Fallback: check project root log files
    log_candidates = [
        Path(config.PROJECT_ROOT) / "bot.log",
        Path(config.PROJECT_ROOT) / "app.log",
    ]
    for log_path in log_candidates:
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    tail = lines[-lines_count:]
                    return "".join(tail) if tail else "📜 Log file is empty."
            except Exception as e:
                return f"❌ Failed to read {log_path.name}: {e}"

    platform_name = "Windows" if sys.platform == "win32" else "Non-systemd"
    return (
        f"ℹ️ System logger (journalctl) is not available on {platform_name}.\n"
        f"To inspect logs via /logs, write output to 'bot.log' in the project root."
    )


def _parse_session_entry(folder: str) -> dict[str, str]:
    conv_id = os.path.basename(folder)
    transcript_file = os.path.join(
        folder,
        ".system_generated",
        "logs",
        "transcript.jsonl",
    )
    title = "Conversation Session"
    date_str = ""

    if os.path.exists(transcript_file):
        with contextlib.suppress(Exception):
            with open(transcript_file, "r", encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    if data.get("type") == "USER_INPUT":
                        content = data.get("content", "")
                        match = re.search(
                            r"<USER_REQUEST>(.*?)</USER_REQUEST>",
                            content,
                            re.DOTALL,
                        )
                        raw_text = match.group(1).strip() if match else content
                        title = raw_text[:50] + ("..." if len(raw_text) > 50 else "")

                        created_at = data.get("created_at", "")
                        if created_at:
                            with contextlib.suppress(Exception):
                                dt = datetime.strptime(
                                    created_at[:19],
                                    "%Y-%m-%dT%H:%M:%S",
                                )
                                date_str = dt.strftime("%d %b %H:%M")
                            if not date_str:
                                date_str = created_at[:10]
                        break

    if not date_str:
        mtime = os.path.getmtime(folder)
        date_str = datetime.fromtimestamp(mtime).strftime("%d %b %H:%M")

    return {"id": conv_id, "title": title, "date": date_str}


def get_recent_sessions(
    limit: int = 10,
    brain_dir: str | None = None,
) -> list[dict[str, str]]:
    """Scans brain directory for recent Antigravity conversation sessions"""
    target_brain = brain_dir or getattr(
        config,
        "BRAIN_DIR",
        DEFAULT_BRAIN_DIR,
    )
    if not os.path.exists(target_brain):
        return []

    sessions = []
    try:
        entries = [
            os.path.join(target_brain, d)
            for d in os.listdir(target_brain)
            if os.path.isdir(os.path.join(target_brain, d))
        ]
        entries.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        for folder in entries[:limit]:
            sessions.append(_parse_session_entry(folder))
    except Exception as e:
        print(f"[ERROR] Failed to list sessions: {e}")

    return sessions


def rename_session(conv_id: str, new_name: str, brain_dir: str | None = None) -> bool:
    """Updates the first USER_INPUT prompt in transcript.jsonl with new_name"""
    target_brain = brain_dir or getattr(
        config,
        "BRAIN_DIR",
        DEFAULT_BRAIN_DIR,
    )
    transcript_file = os.path.join(
        target_brain,
        conv_id,
        ".system_generated",
        "logs",
        "transcript.jsonl",
    )
    if not os.path.exists(transcript_file):
        return False

    try:
        lines = []
        renamed = False
        with open(transcript_file, "r", encoding="utf-8") as f:
            for line in f:
                if not renamed:
                    with contextlib.suppress(Exception):
                        data = json.loads(line)
                        if data.get("type") == "USER_INPUT":
                            content = data.get("content", "")
                            if "<USER_REQUEST>" in content:
                                new_content = re.sub(
                                    r"<USER_REQUEST>(.*?)</USER_REQUEST>",
                                    f"<USER_REQUEST>\n{new_name}\n</USER_REQUEST>",
                                    content,
                                    flags=re.DOTALL,
                                )
                                data["content"] = new_content
                            else:
                                data["content"] = f"<USER_REQUEST>\n{new_name}\n</USER_REQUEST>"
                            lines.append(json.dumps(data) + "\n")
                            renamed = True
                            continue
                lines.append(line)

        if not renamed:
            return False

        with open(transcript_file, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to rename session: {e}")
        return False


def delete_session(conv_id: str, brain_dir: str | None = None) -> bool:
    """Deletes conversation folder from brain directory"""
    target_brain = brain_dir or getattr(
        config,
        "BRAIN_DIR",
        DEFAULT_BRAIN_DIR,
    )
    folder = os.path.join(target_brain, conv_id)
    if os.path.exists(folder):
        try:
            shutil.rmtree(folder)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to delete session: {e}")
            return False
    return False


def get_full_session_history_formatted(
    conv_id: str,
    max_turns: int = 5,
    brain_dir: str | None = None,
) -> list[dict[str, str]]:  # noqa: C901
    """Reads transcript.jsonl for conv_id and returns the last max_turns pairs safely"""
    target_brain = brain_dir or getattr(
        config,
        "BRAIN_DIR",
        DEFAULT_BRAIN_DIR,
    )
    transcript_file = os.path.join(
        target_brain,
        conv_id,
        ".system_generated",
        "logs",
        "transcript.jsonl",
    )
    if not os.path.exists(transcript_file):
        return []

    turns = []
    current_turn = {"user": "", "ai": ""}

    try:
        with open(transcript_file, "r", encoding="utf-8") as f:
            for line in f:
                with contextlib.suppress(Exception):
                    data = json.loads(line)
                    msg_type = data.get("type")

                    if msg_type == "USER_INPUT":
                        content = data.get("content", "")
                        match = re.search(
                            r"<USER_REQUEST>(.*?)</USER_REQUEST>",
                            content,
                            re.DOTALL,
                        )
                        raw_user = match.group(1).strip() if match else content.strip()

                        if current_turn["user"] or current_turn["ai"]:
                            turns.append(current_turn)
                            current_turn = {"user": "", "ai": ""}
                        current_turn["user"] = raw_user

                    elif msg_type == "PLANNER_RESPONSE":
                        content = data.get("content", "")
                        if content:
                            if current_turn["ai"]:
                                current_turn["ai"] += "\n\n" + content.strip()
                            else:
                                current_turn["ai"] = content.strip()

        if current_turn["user"] or current_turn["ai"]:
            turns.append(current_turn)

        return turns[-max_turns:]
    except Exception as e:
        print(f"[ERROR] Failed to read full history: {e}")
        return []


_TOOL_STEP_CONFIG: dict[str, tuple[tuple[str, ...], str, str, str, str, int, str]] = {
    "run_command": (
        ("CommandLine",),
        "Running command: <code>{0}</code>",
        "Running command...",
        "Ran <code>{0}</code>",
        "Ran command",
        42,
        "raw",
    ),
    "view_file": (
        ("AbsolutePath", "TargetFile", "SearchPath"),
        "Reading <code>{0}</code>",
        "Reading file...",
        "Read <code>{0}</code>",
        "Read file",
        60,
        "file",
    ),
    "replace_file_content": (
        ("TargetFile",),
        "Editing <code>{0}</code>",
        "Editing file...",
        "Edited <code>{0}</code>",
        "Edited file",
        60,
        "file",
    ),
    "multi_replace_file_content": (
        ("TargetFile",),
        "Editing <code>{0}</code>",
        "Editing file...",
        "Edited <code>{0}</code>",
        "Edited file",
        60,
        "file",
    ),
    "write_to_file": (
        ("TargetFile",),
        "Writing <code>{0}</code>",
        "Writing file...",
        "Wrote <code>{0}</code>",
        "Wrote file",
        60,
        "file",
    ),
    "list_dir": (
        ("DirectoryPath",),
        "Listing directory <code>{0}</code>",
        "Listing directory...",
        "Listed directory <code>{0}</code>",
        "Listed directory",
        60,
        "dir",
    ),
    "grep_search": (
        ("Query", "Pattern"),
        "Searching for <code>{0}</code>",
        "Searching codebase...",
        "Searched <code>{0}</code>",
        "Searched codebase",
        32,
        "plain",
    ),
    "find_by_name": (
        ("Query", "Pattern"),
        "Searching for <code>{0}</code>",
        "Searching codebase...",
        "Searched <code>{0}</code>",
        "Searched codebase",
        32,
        "plain",
    ),
    "find_files": (
        ("Query", "Pattern"),
        "Searching for <code>{0}</code>",
        "Searching codebase...",
        "Searched <code>{0}</code>",
        "Searched codebase",
        32,
        "plain",
    ),
    "read_url_content": (
        ("Url",),
        "Reading web page <code>{0}</code>",
        "Reading web page...",
        "Read web page <code>{0}</code>",
        "Read web page",
        35,
        "plain",
    ),
    "read_browser_page": (
        ("Url",),
        "Reading web page <code>{0}</code>",
        "Reading web page...",
        "Read web page <code>{0}</code>",
        "Read web page",
        35,
        "plain",
    ),
    "search_web": (
        ("query",),
        "Searching web: <code>{0}</code>",
        "Searching web...",
        "Searched web: <code>{0}</code>",
        "Searched web",
        32,
        "plain",
    ),
    "call_mcp_tool": (
        ("ToolName", "name"),
        "Calling MCP tool <code>{0}</code>",
        "Calling MCP tool...",
        "Called MCP tool <code>{0}</code>",
        "Called MCP tool",
        40,
        "plain",
    ),
    "invoke_subagent": (
        ("Role", "TypeName"),
        "Invoking subagent: <code>{0}</code>",
        "Invoking subagent...",
        "Subagent completed: <code>{0}</code>",
        "Subagent completed",
        40,
        "plain",
    ),
    "generate_image": (
        ("ImageName",),
        "Generating image <code>{0}</code>",
        "Generating image...",
        "Generated image <code>{0}</code>",
        "Generated image",
        40,
        "image",
    ),
}


def _format_tool_param(
    params: dict[str, Any],
    keys: tuple[str, ...],
    max_len: int,
    kind: str,
) -> str:
    val = ""
    for k in keys:
        if k in params and params[k]:
            val = str(params[k]).strip()
            break
    if not val:
        return "image" if kind == "image" else ""
    if kind == "file":
        val = os.path.basename(val)
    elif kind == "dir":
        dname = os.path.basename(val.rstrip("/\\"))
        val = f"{dname}/" if dname else ""
    elif kind == "raw":
        if len(val) > 45:
            val = val[:42] + "..."
    elif kind == "plain":
        if len(val) > max_len + 3:
            val = val[:max_len] + "..."
    return val


def format_tool_step_description(
    tool_name: str,
    params: dict[str, Any],
    done: bool = False,
    duration_seconds: float | None = None,
) -> str:
    """Formats an individual tool execution into a readable HTML step snippet."""
    dur_str = f" <i>({duration_seconds:.2f}s)</i>" if (done and duration_seconds is not None) else ""
    if tool_name in _TOOL_STEP_CONFIG:
        keys, act_tmpl, act_def, done_tmpl, done_def, max_len, kind = _TOOL_STEP_CONFIG[tool_name]
        val = _format_tool_param(params, keys, max_len, kind)
        if done:
            base = done_tmpl.format(html.escape(val)) if val else done_def
            return f"{base}{dur_str}"
        return act_tmpl.format(html.escape(val)) if val else act_def

    raw_action = str(params.get("toolAction") or params.get("toolSummary") or "")
    if raw_action:
        disp_action = raw_action[:57] + "..." if len(raw_action) > 60 else raw_action
        return f"{html.escape(disp_action)}{dur_str}"

    clean_name = html.escape(tool_name.replace("_", " "))
    if len(clean_name) > 40:
        clean_name = clean_name[:37] + "..."
    if done:
        return f"{clean_name} finished{dur_str}"
    return f"Running {clean_name}..."


def format_progress_card(  # noqa: C901
    elapsed_seconds: int,
    completed_steps: list[str],
    active_activity: str,
    spinner_frame: str = "⠋",
    draft_preview: str = "",
) -> str:
    """Formats the real-time Telegram status card showing elapsed time
    and progress steps. Strictly bounds output length to stay under Telegram limits.
    """
    clean_draft = draft_preview.strip()
    preview_block = ""
    if clean_draft:
        preview_text = clean_draft if len(clean_draft) <= 220 else clean_draft[:200].rstrip() + "..."
        preview_escaped = html.escape(preview_text)
        preview_block = f"<blockquote expandable>{preview_escaped}</blockquote>"

    if not completed_steps:
        act_lower = active_activity.lower().strip()
        if preview_block:
            return f"✍️ <b>Drafting response...</b> <i>({elapsed_seconds}s)</i>\n\n{preview_block}"
        if act_lower.startswith("thinking"):
            return f"🧠 <b>Thinking...</b> <i>({elapsed_seconds}s)</i>"
        if act_lower.startswith("drafting"):
            return f"✍️ <b>Drafting response...</b> <i>({elapsed_seconds}s)</i>"
        disp_act = active_activity[:80] + "..." if len(active_activity) > 80 else active_activity
        return f"⚡ <b>Working...</b> <i>({elapsed_seconds}s)</i>\n\n{spinner_frame} <i>{disp_act}</i>"

    header = f"⚡ <b>Working...</b> <i>({elapsed_seconds}s)</i>"
    if len(completed_steps) > 5:
        earlier_count = len(completed_steps) - 4
        rendered_steps = [f"<i>... {earlier_count} earlier steps</i>"] + [f"✓ {s}" for s in completed_steps[-4:]]
    else:
        rendered_steps = [f"✓ {s}" for s in completed_steps]

    steps_block = "\n".join(rendered_steps)

    act_lower = active_activity.lower().strip()
    if preview_block:
        active_line = f"✍️ <b>Drafting response:</b>\n{preview_block}"
    elif act_lower.startswith("drafting"):
        active_line = "✍️ <i>Drafting response...</i>"
    elif act_lower.startswith("thinking"):
        active_line = f"{spinner_frame} <i>Thinking next step...</i>"
    elif act_lower == "done":
        active_line = ""
    else:
        disp_act = active_activity[:80] + "..." if len(active_activity) > 80 else active_activity
        active_line = f"{spinner_frame} <i>{disp_act}</i>"

    card = f"{header}\n\n{steps_block}\n\n{active_line}" if active_line else f"{header}\n\n{steps_block}"
    if len(card) > 3500:
        card = card[:3400] + "\n<i>... (truncated)</i>"
    return card


def _determine_stream_activity(
    tool_name: str,
    args: dict[str, Any],
) -> str:
    """Backward compatibility helper for plain text activity string."""
    desc = format_tool_step_description(tool_name, args, done=False)
    return re.sub(r"<[^>]+>", "", desc)


class StreamProgressTracker:
    """Tracks streaming steps and flushes rate-limited progress updates to Telegram."""

    def __init__(
        self,
        progress_callback: Callable[[str], None] | None = None,
        throttle_interval: float = 1.2,
    ) -> None:
        self.progress_callback = progress_callback
        self.throttle_interval = throttle_interval
        self.start_time = time.time()
        self.completed_steps: list[str] = []
        self.active_activity: str = "Thinking..."
        self.draft_preview: str = ""
        self.spinner_idx = 0
        self.last_update_time = 0.0
        self.last_card_text = ""
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.ticker_thread: threading.Thread | None = None

        if self.progress_callback is not None:
            self.ticker_thread = threading.Thread(
                target=self._ticker_loop,
                name="agy-progress-ticker",
                daemon=True,
            )
            self.ticker_thread.start()
            self.flush(force=True)

    def _ticker_loop(self) -> None:
        while not self.stop_event.wait(timeout=self.throttle_interval):
            self.flush(force=True)

    def set_activity(self, activity: str, force: bool = False) -> None:
        with self.lock:
            self.active_activity = activity
        self.flush(force=force)

    def append_draft(self, delta: str) -> None:
        with self.lock:
            self.draft_preview += delta
            self.active_activity = "Drafting response..."
        self.flush()

    def add_completed_step(
        self,
        step_desc: str,
        next_activity: str = "Thinking next step...",
        force: bool = False,
    ) -> None:
        with self.lock:
            self.completed_steps.append(step_desc)
            self.active_activity = next_activity
        self.flush(force=force)

    def flush(self, force: bool = False) -> None:
        if self.progress_callback is None:
            return

        with self.lock:
            if self.stop_event.is_set():
                return
            now = time.time()
            if not force and (now - self.last_update_time < self.throttle_interval):
                return

            elapsed = int(now - self.start_time)
            spinner = SPINNER_FRAMES[self.spinner_idx % len(SPINNER_FRAMES)]
            self.spinner_idx += 1

            card = format_progress_card(
                elapsed_seconds=elapsed,
                completed_steps=self.completed_steps,
                active_activity=self.active_activity,
                spinner_frame=spinner,
                draft_preview=self.draft_preview,
            )

            if card == self.last_card_text:
                return

            self.last_update_time = now
            self.last_card_text = card

        with contextlib.suppress(Exception):
            self.progress_callback(card)

    def stop(self) -> None:
        self.stop_event.set()
        if self.ticker_thread and self.ticker_thread.is_alive():
            self.ticker_thread.join(timeout=0.5)


def run_antigravity_stream(  # noqa: C901
    prompt: str,
    chat_id: int,
    workspace_dir: str | None = None,
    progress_callback: Callable[[str], None] | None = None,
    *,
    storage: SessionStorage,
) -> tuple[str, dict[str, Any], list[str]]:
    """Runs agy with stream-json propagating --model, --effort, and --mode
    flags with animated spinners.
    """
    agy_exec = shutil.which(config.AGY_PATH) or config.AGY_PATH
    if not os.path.exists(agy_exec) and not shutil.which(config.AGY_PATH):
        return f"❌ agy executable not found at <code>{config.AGY_PATH}</code>", {}, []

    target_storage = storage
    lock = target_storage.get_lock(chat_id)
    with lock:
        cwd = workspace_dir or target_storage.get_workspace(chat_id)
        Path(cwd).mkdir(parents=True, exist_ok=True)

        model = target_storage.get_setting(chat_id, "model", config.DEFAULT_MODEL) or config.DEFAULT_MODEL
        effort = target_storage.get_setting(chat_id, "effort", config.DEFAULT_EFFORT) or config.DEFAULT_EFFORT
        mode = target_storage.get_setting(chat_id, "mode", config.DEFAULT_MODE) or config.DEFAULT_MODE

        conv_target = target_storage.get_active_session(chat_id)
        is_new_conversation = not conv_target

        directives: list[str] = []
        if is_new_conversation:
            persona_directive = getattr(config, "SYSTEM_PERSONA_PROMPT", "").strip()
            if persona_directive:
                directives.append(persona_directive)

        directives.append(
            f"[SYSTEM DIRECTIVE - TARGET WORKSPACE: {cwd}]\n"
            f"Note: User active target workspace directory is strictly set to '{cwd}'. "
            f"All relative paths, file scans, searches, reads, edits, and commands "
            f"MUST take place inside '{cwd}'.",
        )

        prompt_prefix = "\n\n".join(directives)
        augmented_prompt = f"{prompt_prefix}\n\n{prompt}"

        cmd = [
            agy_exec,
            "-p",
            augmented_prompt,
            "--add-dir",
            cwd,
            "--model",
            model,
            "--effort",
            effort,
            "--mode",
            mode,
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ]

        if isinstance(conv_target, str) and conv_target:
            cmd.extend(["--conversation", conv_target])
        elif conv_target is True:
            cmd.append("-c")

        try:
            is_win = sys.platform == "win32"
            use_shell = is_win and agy_exec.lower().endswith((".cmd", ".bat"))
            logger.info(
                "Starting agy stream execution: chat_id=%s, model=%s, effort=%s, mode=%s, cwd=%s, conv=%s",
                chat_id,
                model,
                effort,
                mode,
                cwd,
                conv_target,
            )
            process = subprocess.Popen(  # noqa: S603
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,
                shell=use_shell,
            )
            target_storage.register_process(chat_id, process)
            logger.info("Spawned agy process PID=%d for chat %s", process.pid, chat_id)

            final_response = ""
            turn_usage = {}
            generated_files = []
            step_counter = 0
            raw_output_buffer: deque[str] = deque(maxlen=40)

            start_time = time.time()
            max_duration = 600  # 10 minutes timeout watchdog

            tracker = StreamProgressTracker(
                progress_callback=progress_callback,
                throttle_interval=1.2,
            )
            tracker.set_activity("Engine launched · Initializing...", force=True)

            try:
                for line in iter(process.stdout.readline, ""):
                    if time.time() - start_time > max_duration:
                        logger.warning(
                            "agy process execution timed out after %ds [chat %s]",
                            max_duration,
                            chat_id,
                        )
                        _terminate_process_and_group(process)
                        return (
                            "execution cancelled: timed out after 10 minutes 😅",
                            {},
                            [],
                        )

                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        raw_output_buffer.append(line)
                        logger.warning(
                            "CLI raw non-JSON output [chat %s]: %s",
                            chat_id,
                            line,
                        )
                        continue

                    event_type = data.get("event")

                    if event_type == "init":
                        conv_id = data.get("conversation_id")
                        tools = data.get("init", {}).get("tools", [])
                        logger.info(
                            "agy init event [chat %s]: conv_id=%s, tools=%d",
                            chat_id,
                            conv_id,
                            len(tools),
                        )
                        if conv_id:
                            target_storage.set_active_session(chat_id, conv_id)
                        tracker.set_activity(
                            "Connected · Analyzing request...",
                            force=True,
                        )

                    elif event_type == "step_update":
                        step = data.get("step_update", {})
                        step_type = step.get("step_type", "")
                        step_counter += 1
                        state = step.get("state", "")
                        dur = step.get("duration_seconds")
                        usage = step.get("usage")

                        if usage:
                            turn_usage = usage

                        logger.debug(
                            "agy step_update [chat %s]: type=%s, state=%s, dur=%s",
                            chat_id,
                            step_type,
                            state,
                            dur,
                        )

                        if step_type == "agent_response":
                            delta = step.get("text_delta") or step.get("response") or step.get("text")
                            if delta:
                                if not final_response:
                                    logger.info(
                                        "First response text delta received [chat %s]",
                                        chat_id,
                                    )
                                final_response += delta
                                tracker.append_draft(delta)
                            elif state == "DONE":
                                thk = (usage or {}).get("thinking_tokens", 0)
                                if thk > 0:
                                    logger.info(
                                        "Reasoning step done [chat %s]: thinking_tokens=%d, dur=%.2fs",
                                        chat_id,
                                        thk,
                                        dur or 0.0,
                                    )
                                    tracker.set_activity(
                                        f"Reasoned next action ({thk} tokens)...",
                                    )
                                else:
                                    tracker.set_activity("Thinking next step...")

                        tool_name = (
                            step.get("tool_name")
                            or (step.get("tool_info") or {}).get("name")
                            or (step.get("tool_call") or {}).get("name")
                            or (step.get("tool") or {}).get("name")
                            or ""
                        )
                        tool_info = step.get("tool_info") or {}
                        params = (
                            tool_info.get("parameters")
                            or (step.get("tool_call") or {}).get("args")
                            or (step.get("tool") or {}).get("args")
                            or {}
                        )

                        if tool_name:
                            if tool_name in [
                                "write_to_file",
                                "generate_image",
                                "multi_replace_file_content",
                            ]:
                                target = params.get("TargetFile") or params.get(
                                    "ImageName",
                                )
                                if target and os.path.exists(target) and target not in generated_files:
                                    generated_files.append(target)

                            if state == "ACTIVE":
                                logger.info(
                                    "Tool ACTIVE [chat %s]: %s",
                                    chat_id,
                                    tool_name,
                                )
                                desc = format_tool_step_description(
                                    tool_name,
                                    params,
                                    done=False,
                                )
                                tracker.set_activity(desc)
                            elif state == "DONE":
                                logger.info(
                                    "Tool DONE [chat %s]: %s in %.3fs",
                                    chat_id,
                                    tool_name,
                                    dur or 0.0,
                                )
                                desc = format_tool_step_description(
                                    tool_name,
                                    params,
                                    done=True,
                                    duration_seconds=dur,
                                )
                                tracker.add_completed_step(
                                    desc,
                                    next_activity="Thinking next step...",
                                )
                            elif state == "ERROR" or step.get("error"):
                                err_text = (
                                    step.get("error")
                                    or (tool_info.get("error") if isinstance(tool_info, dict) else "")
                                    or "Execution failed"
                                )
                                logger.error(
                                    "Tool ERROR [chat %s]: %s: %s",
                                    chat_id,
                                    tool_name,
                                    err_text,
                                )
                                desc = f"❌ {html.escape(tool_name)}: {html.escape(str(err_text))}"
                                tracker.add_completed_step(
                                    desc,
                                    next_activity="Thinking next step...",
                                )
                            else:
                                desc = format_tool_step_description(
                                    tool_name,
                                    params,
                                    done=False,
                                )
                                tracker.set_activity(desc)

                    elif event_type == "result":
                        res = data.get("result", {})
                        status = res.get("status", "")
                        res_err = res.get("error", "")
                        res_text = res.get("response", "")
                        logger.info(
                            "Stream result [chat %s]: status=%s, turns=%s, dur=%.2fs, usage=%s",
                            chat_id,
                            status,
                            res.get("num_turns"),
                            res.get("duration_seconds", 0.0),
                            res.get("usage"),
                        )
                        if status == "ERROR" or res_err:
                            logger.error(
                                "CLI result reported error [chat %s]: %s",
                                chat_id,
                                res_err,
                            )
                            err_desc = html.escape(res_err or "Execution failed")
                            final_response = f"❌ <b>Antigravity Error:</b>\n<code>{err_desc}</code>"
                        elif res_text:
                            final_response = res_text
                        if res.get("usage"):
                            turn_usage = res.get("usage")
                        tracker.set_activity("Done", force=True)
            finally:
                tracker.stop()
                if process.stdout and not getattr(process.stdout, "closed", True):
                    with contextlib.suppress(Exception):
                        process.stdout.close()
                wait_res = None
                with contextlib.suppress(Exception):
                    wait_res = process.wait()
                target_storage.unregister_process(chat_id)

            ret_code = (
                process.returncode
                if isinstance(process.returncode, int)
                else (wait_res if isinstance(wait_res, int) else 0)
            )
            if ret_code != 0:
                logger.error(
                    "agy process PID %s exited with code %d [chat %s]",
                    getattr(process, "pid", "unknown"),
                    ret_code,
                    chat_id,
                )
                if not final_response or not final_response.strip().startswith("❌"):
                    err_details = "\n".join(raw_output_buffer).strip()
                    if err_details:
                        final_response = (
                            f"❌ <b>Antigravity CLI Failed (Exit Code {ret_code}):"
                            f"</b>\n<pre><code>{html.escape(err_details[:1500])}"
                            f"</code></pre>"
                        )
                    else:
                        final_response = f"❌ <b>Antigravity CLI Failed (Exit Code {ret_code})</b>"
            elif not final_response or not final_response.strip():
                if tracker.completed_steps:
                    final_response = "✅ Task completed (no output text produced)."
                else:
                    err_details = "\n".join(raw_output_buffer).strip()
                    if err_details:
                        final_response = (
                            f"⚠️ <b>Execution completed with warnings:</b>\n"
                            f"<pre><code>{html.escape(err_details[:1000])}</code></pre>"
                        )
                    else:
                        final_response = "sure, is there anything else I can help with?"

            if not target_storage.get_active_session(chat_id):
                target_storage.set_active_session(chat_id, True)

            usage_stats = target_storage.get_token_usage(chat_id)
            if turn_usage and turn_usage.get("total_tokens"):
                t_tok = turn_usage["total_tokens"]
                usage_stats["session_tokens"] += t_tok
                usage_stats["total_tokens"] += t_tok

            if tracker.completed_steps:
                turn_usage["steps"] = list(tracker.completed_steps)

            resp_text = final_response.strip()
            logger.info(
                "Completed agy run [chat %s]: resp_len=%d, steps=%d",
                chat_id,
                len(resp_text),
                len(tracker.completed_steps),
            )
            return resp_text, turn_usage, generated_files

        except Exception as e:
            target_storage.unregister_process(chat_id)
            logger.exception(
                "Failed to run Antigravity stream [chat %s]: %s",
                chat_id,
                e,
            )
            return f"❌ <b>Failed to run Antigravity:</b> {str(e)}", {}, []
