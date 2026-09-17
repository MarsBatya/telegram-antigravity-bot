import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import config

SESSION_FILE = os.path.join(os.path.dirname(__file__), "sessions.json")

active_conversations = {}
active_workspaces = {}
active_settings = {}  # chat_id -> {'model': ..., 'effort': ..., 'mode': ...}
chat_token_usage = {}  # chat_id -> {'session_tokens': 0, 'total_tokens': 0}
active_processes = {}  # chat_id -> subprocess.Popen instance

# Per-chat task queue and lock to prevent concurrent process collisions
chat_locks = {}

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def load_persistent_sessions():
    """Loads active conversation mapping, workspaces, and chat settings from persistent disk storage"""
    global active_conversations, active_workspaces, active_settings
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                convs = data.get("conversations", {})
                workspaces = data.get("workspaces", {})
                settings = data.get("settings", {})
                if not convs and not workspaces and isinstance(data, dict):
                    convs = data

                active_conversations = {int(k): v for k, v in convs.items()}
                active_workspaces = {int(k): v for k, v in workspaces.items()}
                active_settings = {int(k): v for k, v in settings.items()}
                return
        except Exception as e:
            print(f"[ERROR] Loading sessions.json: {e}")
    active_conversations = {}
    active_workspaces = {}
    active_settings = {}


def save_persistent_sessions():
    """Saves active conversation mapping, workspaces, and settings to persistent disk storage"""
    try:
        data = {
            "conversations": {str(k): v for k, v in active_conversations.items()},
            "workspaces": {str(k): v for k, v in active_workspaces.items()},
            "settings": {str(k): v for k, v in active_settings.items()},
        }
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[ERROR] Saving sessions.json: {e}")


load_persistent_sessions()


def get_chat_setting(chat_id: int, key: str, default=None):
    if chat_id not in active_settings:
        active_settings[chat_id] = {
            "model": config.DEFAULT_MODEL,
            "effort": config.DEFAULT_EFFORT,
            "mode": config.DEFAULT_MODE,
        }
    return active_settings[chat_id].get(key, default)


def set_chat_setting(chat_id: int, key: str, value: str):
    if chat_id not in active_settings:
        active_settings[chat_id] = {
            "model": config.DEFAULT_MODEL,
            "effort": config.DEFAULT_EFFORT,
            "mode": config.DEFAULT_MODE,
        }
    active_settings[chat_id][key] = value
    save_persistent_sessions()


def get_chat_workspace(chat_id: int) -> str:
    return active_workspaces.get(chat_id) or config.DEFAULT_WORKSPACE


def set_chat_workspace(chat_id: int, workspace_path: str):
    active_workspaces[chat_id] = os.path.abspath(workspace_path)
    save_persistent_sessions()


def get_chat_lock(chat_id: int):
    if chat_id not in chat_locks:
        chat_locks[chat_id] = threading.Lock()
    return chat_locks[chat_id]


def get_token_usage(chat_id: int):
    if chat_id not in chat_token_usage:
        chat_token_usage[chat_id] = {"session_tokens": 0, "total_tokens": 0}

    conv_id = active_conversations.get(chat_id)
    if isinstance(conv_id, str) and conv_id and chat_token_usage[chat_id]["session_tokens"] == 0:
        chat_token_usage[chat_id]["session_tokens"] = calculate_session_tokens(conv_id)

    return chat_token_usage[chat_id]


def calculate_session_tokens(conv_id: str) -> int:
    """Calculates total tokens accumulated in a conversation session from transcript.jsonl"""
    transcript_file = os.path.join(
        "/root/.gemini/antigravity-cli/brain", conv_id, ".system_generated", "logs", "transcript.jsonl"
    )
    if not os.path.exists(transcript_file):
        return 0

    total_tokens = 0
    try:
        with open(transcript_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get("type") == "PLANNER_RESPONSE":
                        usage = data.get("usage")
                        if isinstance(usage, dict) and "total_tokens" in usage:
                            total_tokens += usage.get("total_tokens", 0)
                except Exception:
                    pass
    except Exception as e:
        print(f"[ERROR] Failed to calculate session tokens: {e}")
    return total_tokens


def make_ascii_bar(pct: float, length: int = 20) -> str:
    filled = int(round(length * pct / 100))
    filled = max(0, min(length, filled))
    return "█" * filled + "░" * (length - filled)


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
        elif hours > 0:
            return f"Refreshes in {hours}h {mins}m"
        else:
            return f"Refreshes in {mins}m"
    except Exception:
        return ""


def fetch_live_user_quota_summary() -> str:
    """Fetches real-time Models & Quota summary directly from Google Cloud Code PA API"""
    token_file = "/root/.gemini/antigravity-cli/antigravity-oauth-token"
    if not os.path.exists(token_file):
        return "⚠️ <b>OAuth token file not found on server.</b>"

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            token_data = json.load(f)

        access_token = token_data.get("token", {}).get("access_token")
        id_token = token_data.get("id_token", "")

        if not access_token:
            return "⚠️ <b>Invalid OAuth access token.</b>"

        email = "daffaventure@gmail.com"
        if id_token and "." in id_token:
            try:
                payload_b64 = id_token.split(".")[1]
                payload_b64 += "=" * (-len(payload_b64) % 4)
                payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
                email = payload.get("email", email)
            except Exception:
                pass

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity-cli/1.1.9",
        }

        url = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
        req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=10) as resp:
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
                bar = make_ascii_bar(pct)
                reset_str = parse_reset_time(bucket.get("resetTime"))
                b_desc = bucket.get("description", "")

                output.append(f"  <b>{b_name}</b>")
                if disabled:
                    output.append("    <code>[Disabled]</code>")
                    output.append(f"    <i>{b_desc}</i>\n")
                else:
                    output.append(f"    <code>[{bar}] {pct:.2f}%</code>")
                    output.append(f"    {pct:.0f}% remaining · {reset_str}\n")

        return "\n".join(output)
    except Exception as e:
        return f"⚠️ <b>Failed to fetch live quota data:</b> <code>{str(e)}</code>"


def fetch_available_models_live() -> list:
    """Fetches list of active models directly from Google Cloud Code API"""
    token_file = "/root/.gemini/antigravity-cli/antigravity-oauth-token"
    if not os.path.exists(token_file):
        return []

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            token_data = json.load(f)

        access_token = token_data.get("token", {}).get("access_token")
        if not access_token:
            return []

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity-cli/1.1.9",
        }

        url = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
        req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        models = []
        for m_id, m_info in data.get("models", {}).items():
            disp = m_info.get("displayName")
            if disp:
                models.append(
                    {
                        "id": m_id,
                        "displayName": disp,
                        "supportsThinking": m_info.get("supportsThinking", False),
                        "recommended": m_info.get("recommended", False),
                    }
                )

        models.sort(key=lambda x: (not x["recommended"], x["displayName"]))
        return models
    except Exception as e:
        print(f"[ERROR] fetch_available_models_live: {e}")
        return []


def fetch_bot_logs(lines_count: int = 30) -> str:
    """Fetches systemd service logs for antigravity-bot"""
    try:
        res = subprocess.run(
            ["journalctl", "-u", "antigravity-bot", "-n", str(lines_count), "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.stdout:
            return res.stdout
        return "📜 No recent logs."
    except Exception as e:
        return f"❌ Failed to fetch logs: {e}"


def cancel_chat_process(chat_id: int) -> bool:
    """Cancels the active agy child process for a given chat_id"""
    proc = active_processes.get(chat_id)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            time.sleep(0.5)
            if proc.poll() is None:
                proc.kill()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to kill process for chat {chat_id}: {e}")
            return False
    return False


def get_recent_sessions(limit=10):
    """Scans brain directory for recent Antigravity conversation sessions"""
    brain_dir = "/root/.gemini/antigravity-cli/brain"
    if not os.path.exists(brain_dir):
        return []

    sessions = []
    try:
        entries = [
            os.path.join(brain_dir, d) for d in os.listdir(brain_dir) if os.path.isdir(os.path.join(brain_dir, d))
        ]
        entries.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        for folder in entries[:limit]:
            conv_id = os.path.basename(folder)
            transcript_file = os.path.join(folder, ".system_generated", "logs", "transcript.jsonl")

            title = "Conversation Session"
            date_str = ""

            if os.path.exists(transcript_file):
                try:
                    with open(transcript_file, "r", encoding="utf-8") as f:
                        for line in f:
                            data = json.loads(line)
                            if data.get("type") == "USER_INPUT":
                                content = data.get("content", "")
                                match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
                                if match:
                                    raw_text = match.group(1).strip()
                                    title = raw_text[:50] + ("..." if len(raw_text) > 50 else "")
                                else:
                                    title = content[:50] + ("..." if len(content) > 50 else "")

                                created_at = data.get("created_at", "")
                                if created_at:
                                    try:
                                        dt = datetime.strptime(created_at[:19], "%Y-%m-%dT%H:%M:%S")
                                        date_str = dt.strftime("%d %b %H:%M")
                                    except Exception:
                                        date_str = created_at[:10]
                                break
                except Exception:
                    pass

            if not date_str:
                mtime = os.path.getmtime(folder)
                date_str = datetime.fromtimestamp(mtime).strftime("%d %b %H:%M")

            sessions.append({"id": conv_id, "title": title, "date": date_str})
    except Exception as e:
        print(f"[ERROR] Failed to list sessions: {e}")

    return sessions


def rename_session(conv_id: str, new_name: str) -> bool:
    """Updates the first USER_INPUT prompt in transcript.jsonl with new_name"""
    transcript_file = os.path.join(
        "/root/.gemini/antigravity-cli/brain", conv_id, ".system_generated", "logs", "transcript.jsonl"
    )
    if not os.path.exists(transcript_file):
        return False

    try:
        lines = []
        with open(transcript_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i == 0:
                    try:
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
                            continue
                    except Exception:
                        pass
                lines.append(line)

        with open(transcript_file, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to rename session: {e}")
        return False


def delete_session(conv_id: str) -> bool:
    """Deletes conversation folder from brain directory"""
    folder = os.path.join("/root/.gemini/antigravity-cli/brain", conv_id)
    if os.path.exists(folder):
        try:
            shutil.rmtree(folder)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to delete session: {e}")
            return False
    return False


def get_full_session_history_formatted(conv_id: str, max_turns: int = 5) -> list:
    """Reads transcript.jsonl for conv_id and returns the last max_turns pairs safely"""
    transcript_file = os.path.join(
        "/root/.gemini/antigravity-cli/brain", conv_id, ".system_generated", "logs", "transcript.jsonl"
    )
    if not os.path.exists(transcript_file):
        return []

    turns = []
    current_turn = {"user": "", "ai": ""}

    try:
        with open(transcript_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    msg_type = data.get("type")

                    if msg_type == "USER_INPUT":
                        content = data.get("content", "")
                        match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
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
                except Exception:
                    pass

        if current_turn["user"] or current_turn["ai"]:
            turns.append(current_turn)

        return turns[-max_turns:]
    except Exception as e:
        print(f"[ERROR] Failed to read full history: {e}")
        return []


def run_antigravity_stream(prompt: str, chat_id: int, workspace_dir: str = None, progress_callback=None) -> tuple:
    """Runs agy with stream-json propagating --model, --effort, and --mode flags with animated spinners"""
    if not os.path.exists(config.AGY_PATH):
        return f"❌ agy executable not found at <code>{config.AGY_PATH}</code>", {}, []

    lock = get_chat_lock(chat_id)
    with lock:
        cwd = workspace_dir or get_chat_workspace(chat_id)
        os.makedirs(cwd, exist_ok=True)

        model = get_chat_setting(chat_id, "model", config.DEFAULT_MODEL)
        effort = get_chat_setting(chat_id, "effort", config.DEFAULT_EFFORT)
        mode = get_chat_setting(chat_id, "mode", config.DEFAULT_MODE)

        persona_directive = getattr(config, "SYSTEM_PERSONA_PROMPT", "")
        augmented_prompt = (
            f"{persona_directive}\n\n"
            f"[SYSTEM DIRECTIVE - TARGET WORKSPACE: {cwd}]\n"
            f"Note: User active target workspace directory is strictly set to '{cwd}'. "
            f"All relative paths, file scans, searches, reads, edits, and commands MUST take place inside '{cwd}'.\n\n"
            f"{prompt}"
        )

        cmd = [
            config.AGY_PATH,
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

        conv_target = active_conversations.get(chat_id)
        if isinstance(conv_target, str) and conv_target:
            cmd.extend(["--conversation", conv_target])
        elif conv_target is True:
            cmd.append("-c")

        try:
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )

            final_response = ""
            last_update_time = 0
            current_activity = "thinking..."
            turn_usage = {}
            generated_files = []
            step_counter = 0

            start_time = time.time()
            max_duration = 600  # 10 minutes timeout watchdog

            for line in iter(process.stdout.readline, ""):
                if time.time() - start_time > max_duration:
                    process.kill()
                    return "execution cancelled: timed out after 10 minutes 😅", {}, []

                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    event_type = data.get("event")

                    if event_type == "init":
                        conv_id = data.get("conversation_id")
                        if conv_id:
                            active_conversations[chat_id] = conv_id
                            save_persistent_sessions()

                    elif event_type == "step_update":
                        step = data.get("step_update", {})
                        step_type = step.get("step_type", "")
                        step_counter += 1

                        if step.get("usage"):
                            turn_usage = step.get("usage")

                        if step_type == "agent_response":
                            delta = step.get("text_delta") or step.get("response") or step.get("text")
                            if delta:
                                final_response += delta

                        tool_call = step.get("tool_call") or step.get("tool") or {}
                        tool_name = tool_call.get("name", step_type)
                        args = tool_call.get("args", {})

                        if tool_name in ["write_to_file", "generate_image", "multi_replace_file_content"]:
                            target = args.get("TargetFile") or args.get("ImageName")
                            if target and os.path.exists(target):
                                generated_files.append(target)

                        # Build simple, human-like activity status
                        raw_action = args.get("toolAction") or args.get("toolSummary")
                        target_file = args.get("TargetFile") or args.get("AbsolutePath") or args.get("SearchPath")
                        fname = os.path.basename(target_file) if target_file else ""

                        if tool_name == "view_file":
                            current_activity = f"reading {fname}" if fname else "reading file..."
                        elif tool_name in ["replace_file_content", "multi_replace_file_content", "write_to_file"]:
                            current_activity = f"editing {fname}" if fname else "writing changes..."
                        elif tool_name in ["grep_search", "find_files"]:
                            query = args.get("Query", "")
                            current_activity = f"searching {query}" if query else "searching..."
                        elif tool_name == "run_command":
                            current_activity = "running command..."
                        elif raw_action:
                            current_activity = raw_action.lower()
                        else:
                            current_activity = "drafting response..."

                        now = time.time()
                        if progress_callback and (now - last_update_time >= 1.2):
                            try:
                                progress_callback(f"<i>{current_activity}</i>")
                            except Exception:
                                pass
                            last_update_time = now

                    elif event_type == "result":
                        res = data.get("result", {})
                        res_text = res.get("response", "")
                        if res_text:
                            final_response = res_text
                        if res.get("usage"):
                            turn_usage = res.get("usage")

                except json.JSONDecodeError:
                    pass

            process.stdout.close()
            process.wait()
            active_processes.pop(chat_id, None)

            if not active_conversations.get(chat_id):
                active_conversations[chat_id] = True
                save_persistent_sessions()

            usage_stats = get_token_usage(chat_id)
            if turn_usage and turn_usage.get("total_tokens"):
                t_tok = turn_usage["total_tokens"]
                usage_stats["session_tokens"] += t_tok
                usage_stats["total_tokens"] += t_tok

            resp_text = (
                final_response.strip()
                if final_response and final_response.strip()
                else "sure, is there anything else I can help with?"
            )
            return resp_text, turn_usage, generated_files

        except Exception as e:
            active_processes.pop(chat_id, None)
            return f"❌ <b>Failed to run Antigravity:</b> {str(e)}", {}, []


def run_smash_stream(prompt: str, chat_id: int, workspace_dir: str = None, progress_callback=None) -> tuple:
    smash_prompt = (
        "💥 SMASH MODE INSTRUCTION: Complete the following task with maximum effort, thoroughness, and speed. "
        "Fix all bugs, resolve any broken code/tests, build the project, and do not stop until everything runs 100% cleanly:\n\n"
        f"{prompt}"
    )
    return run_antigravity_stream(smash_prompt, chat_id, workspace_dir, progress_callback)


def resume_stream(prompt: str, chat_id: int, workspace_dir: str = None, progress_callback=None) -> tuple:
    resume_prompt = prompt if prompt else "Continue the work and context from the last unfinished point."
    return run_antigravity_stream(resume_prompt, chat_id, workspace_dir, progress_callback)


def set_active_session(chat_id: int, conv_id: str):
    active_conversations[chat_id] = conv_id
    save_persistent_sessions()
    if chat_id not in chat_token_usage:
        chat_token_usage[chat_id] = {"session_tokens": 0, "total_tokens": 0}
    chat_token_usage[chat_id]["session_tokens"] = calculate_session_tokens(conv_id)


def reset_session(chat_id: int):
    active_conversations.pop(chat_id, None)
    save_persistent_sessions()
    if chat_id in chat_token_usage:
        chat_token_usage[chat_id]["session_tokens"] = 0
