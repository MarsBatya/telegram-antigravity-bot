# AGENTS.md

## Overview & Architecture

`telegram-antigravity-bot` is a Python Telegram bot interface for the Antigravity AI Agent CLI (`agy`). It enables remote server administration, code execution, multi-file editing, and session management directly from Telegram using `aiogram 3.x` (`aiogram v3`).

- **Runtime**: Python 3.12 (`>=3.10` in `pyproject.toml`) managed with `uv`.
- **Concurrency model**: Asynchronous `aiogram v3` event loop polling with background `asyncio` tasks and threadpool workers (`asyncio.to_thread`) for long-running CLI stream execution.
- **Execution engine**: Spawns `agy` CLI sub-processes via `subprocess.Popen`, parsing real-time line-delimited JSON events (`thought`, `tool_call`, `result`).
- **Persistence**: File-backed session mapping (`sessions.json`) tracking active conversations, workspace directories, and model settings per chat.

---

## Repository Map

- `main.py`: Primary Telegram bot entry point, Dispatcher setup, router registry, and long-polling runner.
- `app/`: Core application package containing modular domain packages:
  - `core/`:
    - `config.py`: Environment configuration loader (`.env`), Telegram user whitelist (`ALLOWED_USER_IDS`), proxy normalization, and default agent persona.
    - `model_manager.py`: Encapsulates AI model catalog discovery (`agy models`, CloudCode API tiered parsing), caching, and resolution (`ModelManager`), injected via aiogram v3 dependency injection.
    - `storage.py`: Thread-safe, file-backed session, workspace, setting, and process storage (`SessionStorage`), injected into handlers via aiogram v3 dependency injection.
  - `runner/`:
    - `stream_runner.py`: Subprocess runner for `agy` CLI streaming execution, stdout JSON event parser, session persistence, lock management, and live quota checking.
    - `agent_runner.py`: Public facade exporting stream runner utilities for execution and session management.
  - `handlers/`: Modular aiogram routers:
    - `commands.py`: General commands (`/start`, `/help`, `/status`, `/usage`, `/logs`, `/stop`, `/cancel`).
    - `settings.py`: Model, reasoning effort, and mode selectors (`/model`, `/effort`, `/mode`).
    - `explorer.py`: Interactive directory tree browser and workspace picker (`/tree`, `/workspace`).
    - `sessions.py`: Active session card, resume, new, rename, and deletion (`/resume`, `/new`, `/rename`, `/delete`).
    - `agent.py`: Agent execution orchestrator, text prompt runner, media downloader, and task modes (`/smash`, `/goal`, `/plan`).
  - `ui/`:
    - `callbacks.py`: Type-safe `CallbackData` subclasses for inline buttons.
    - `keyboards.py`: Interactive reply keyboard and inline keyboard builders.
  - `middlewares/`:
    - `auth.py`: Global authentication middleware (`AuthMiddleware`) verifying `ALLOWED_USER_IDS`.
  - `utils/`:
    - `bot_utils.py`: `PathMapper` for path encoding, progress bar formatting, command menu registration, and safe message chunking.
    - `formatter.py`: Converts agent markdown output into Telegram HTML (`<pre><code>`, `<b>`, `<i>`, `<blockquote expandable>`).
- `Dockerfile`: Multi-stage Dockerfile bundling python 3.12-slim, agy CLI, uv, and healthcheck.
- `docker-compose.yml`: Container orchestration with volumes, proxy passthrough, and resource limits.
- `docker-entrypoint.sh`: Container bootstrap script handling sessions.json initialization, proxy vars, and auth setup.
- `sessions.json`: Persisted chat sessions and workspace state (managed dynamically; do not manually overwrite).

---

## Essential Commands

### Environment & Package Management
```bash
# Sync dependencies via uv
uv sync

# Add a runtime or dev dependency
uv add <package>
uv add --dev <package>
```

### Running the Bot
```bash
# Run the bot in development
uv run python main.py

# Run via Docker Compose
docker compose up -d
docker compose logs -f
```

### Testing
```bash
# Run the full test suite
uv run pytest

# Run a specific test file
uv run pytest tests/test_main.py

# Run a single test case with verbosity
uv run pytest tests/test_stream_runner.py -k "test_run_antigravity_stream" -v
```

## Linting & Formatting

Always use **ruff** for linting and formatting Python code in this project.

```bash
# Fix lint issues automatically
uv run ruff check --config /home/mars/python/.vscode/ruff.toml --fix .

# Format code
uv run ruff format --config /home/mars/python/.vscode/ruff.toml .
```

---

## Python Type Hinting Guidelines

All Python code in this repository must use strict, modern type annotations conforming to Python 3.10+ / 3.12+ standards:

1. **Modern Union Syntax (PEP 604)**:
   - Always use `T | None` instead of `Optional[T]`.
   - Use `A | B` instead of `Union[A, B]`.

2. **Built-in Generics (PEP 585)**:
   - Use standard collection types directly: `list[T]`, `dict[K, V]`, `set[T]`, `tuple[T, ...]`.
   - Do NOT import `List`, `Dict`, `Set`, `Tuple` from `typing`.

3. **Explicit Function Annotations**:
   - Annotate all function parameters and explicit return types across all modules and tests.
   - For functions with no return value, explicitly annotate `-> None`.
   - Do not use implicit optional arguments (e.g., `token: str = None`). Always write `token: str | None = None`.

4. **Specific Types Over `Any`**:
   - Avoid `Any` where concrete types, unions, or type aliases can be used.
   - For callbacks and functions passed as arguments, use `collections.abc.Callable` or `typing.Callable` (e.g., `Callable[[str, dict[str, Any]], None]`).
   - For Telegram entities, import types from `aiogram.types` (e.g., `Message`, `CallbackQuery`, `InlineKeyboardMarkup`).
   - Use `collections.abc.Generator` or `collections.abc.Iterator` for generator functions.

5. **Type Narrowing & Guards**:
   - Check against `None` explicitly using `is None` / `is not None` before accessing attributes.
   - Handle dictionary payloads and JSON responses with guarded checks (`isinstance(data, dict)`).

---

## Key Conventions & Constraints

- **Telegram Message Limits**: Telegram enforces a strict 4096-character limit per message. When sending streamed chunks or formatted output, route messages through `formatter.py` or chunking logic.
- **Callback Data Size**: Inline keyboard `callback_data` has a 64-byte limit. Always use `PathMapper` (in `bot_utils.py`) to map long filesystem paths to short tokens (e.g. `p1`, `p2`).
- **Thread Safety & Background Tasks**: Do not run blocking CLI executions directly on the asyncio event loop. Spawn tasks via `asyncio.create_task` and offload blocking subprocess streams via `asyncio.to_thread` with `stream_runner.chat_locks` to prevent duplicate concurrent processes per chat.
- **HTML Escaping**: Telegram parse mode is HTML (`parse_mode="HTML"`). All dynamic user inputs or agent outputs must have HTML-sensitive characters (`<`, `>`, `&`) properly escaped via `html.escape` unless already converted into valid Telegram HTML tags by `formatter.py`.
- **Authorized Access**: Any new handlers or administrative features must respect `ALLOWED_USER_IDS` authorization checks (managed centrally via `AuthMiddleware`).

---

## Safety & Boundaries

- **Credentials**: Never commit `.env` or OAuth tokens (`antigravity-oauth-token`). Always refer to `.env.example`.
- **Sessions File**: Do not manually delete or format `sessions.json` during test execution or development; use `stream_runner.load_persistent_sessions` and `save_persistent_sessions` or mock the file in tests.
- **Process Management**: Ensure subprocess cancellations properly terminate the child process group so orphaned `agy` CLI processes do not linger on the host.
- **Docker Root Execution**: The Docker container intentionally runs as `root` to grant the `agy` CLI sub-processes full flexibility to manage system packages, developer tooling, and workspace files without permission barriers.
