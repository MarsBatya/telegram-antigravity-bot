# Antigravity AI Agent Telegram Bot

Control your Linux server, coding execution, bug fixes, and development workflows remotely via Telegram, powered by the Google Antigravity AI CLI (`agy`).

## Features

- Remote AI coding agent: execute complex coding tasks, refactoring, and multi-file debugging directly from Telegram.
- Seamless session resumption: resume conversation sessions (/resume) without cluttering chat context.
- Persistent quick menu: interactive keyboard buttons (Active Session, Resume, New Session, Workspace, System & Usage, Help).
- Interactive workspace picker: switch server working directories instantly with inline buttons.
- Realtime token and system health: monitor token consumption, RAM usage, CPU load, and disk metrics.
- Authorized security: strict access control matching pre-configured Telegram user IDs via environment variables.

## Commands

| Command | Description |
|---|---|
| /start, /help | Show help |
| /model | Pick the AI model |
| /effort | Set reasoning effort (low / medium / high) |
| /mode | Set agent mode |
| /smash | Run the agent in "smash" mode |
| /goal | Set the current goal |
| /plan | Ask for a plan before execution |
| /tree, /ls | Browse workspace directories and files |
| /workspace | Show or switch the active workspace |
| /resume | Resume a past session |
| /new, /reset | Start a new session |
| /rename | Rename the current session |
| /delete | Delete a session |
| /stop, /cancel | Cancel the running task |
| /usage | Show Freebuff quota and model usage |
| /status | Show server metrics and session status |
| /doctor | Pre-flight health check & diagnostic doctor |
| /logs | Show recent bot logs |

Any other message is treated as a prompt for the agent.

## Requirements

- Python 3.10+ (Python 3.12 recommended) or Docker & Docker Compose
- The Antigravity CLI (`agy`) installed on the host (or automated inside Docker)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Quick Setup

### 1. Clone the repository

```bash
git clone https://github.com/MarsBatya/telegram-antigravity-bot.git
cd telegram-antigravity-bot
```

### 2. Configure environment variables

Create your configuration file from the example:

```bash
cp .env.example .env
```

Edit `.env` to configure your credentials:

```env
# Required: Telegram Bot Token (from @BotFather)
TELEGRAM_BOT_TOKEN=123456789:AA...your-token-from-botfather

# Optional on first run: leave empty to have the bot tell you your ID via /start!
ALLOWED_USER_IDS=123456789

# Optional: Antigravity CLI & Workspace settings (auto-detected if omitted)
# AGY_PATH=/root/.local/bin/agy
# DEFAULT_WORKSPACE=/root/workspace
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Bot token obtained from [@BotFather](https://t.me/BotFather) |
| `ALLOWED_USER_IDS` | No* | - | Comma-separated Telegram user IDs allowed to interact with the bot (*bot reports your ID on first `/start` if left blank) |
| `AGY_PATH` | No | Auto-detected | Path to the Antigravity CLI binary (auto-detected from PATH, `~/.local/bin/agy`, or Windows app dirs) |
| `DEFAULT_WORKSPACE` | No | `~/my-project` | Default working directory for the agent (or `/root/workspace` in Docker) |
| `GEMINI_API_KEY` | No | - | Gemini API key for headless authentication, only if you pay for tokens there |
| `HTTP_PROXY` | No | - | HTTP/HTTPS/SOCKS5 proxy URL for Telegram and `agy` requests |
| `HTTPS_PROXY` | No | - | HTTPS proxy URL (defaults to `HTTP_PROXY` if omitted) |
| `NO_PROXY` | No | `localhost,127.0.0.1,::1` | Comma-separated domains/IPs to bypass proxy |

---

## Authentication Options

The bot supports two authentication strategies for the Antigravity CLI (`agy`):

> [!NOTE]
> **Model Availability:**
> - When `GEMINI_API_KEY` is used, **only Gemini models** (e.g. Gemini 3.8, 3.7, 3.6, 3.1 Pro) are available.
> - For **Claude** and **GPT** models to be available, it is required to use an **OAuth token**.

### Option 1: Gemini API Key (Headless — Recommended for Docker & Servers)

Ideal for automated deployments, Docker containers, and headless VPS environments where a web browser is unavailable.

1. Obtain an API key from [Google AI Studio](https://aistudio.google.com/).
2. Add your key to `.env`:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```
3. When starting via Docker or the entrypoint script, `settings.json` is automatically configured with `"modelProvider": "gemini"` so `agy` runs directly without prompting for OAuth.

### Option 2: OAuth Token (Host Mount)

If you already use `agy` interactively on your host machine and have run `agy login`:

1. Your OAuth token is located on the host at:
   - Linux/macOS: `~/.gemini/antigravity-cli/antigravity-oauth-token`
2. **In Docker**: Mount the host token file into the container by adding it to the `volumes` section of `docker-compose.yml`:
   ```yaml
   volumes:
     - ~/.gemini/antigravity-cli/antigravity-oauth-token:/root/.gemini/antigravity-cli/antigravity-oauth-token:ro
   ```
3. **Local Run**: The local `agy` binary will automatically find your existing token in `~/.gemini/antigravity-cli/`.

---

## Proxy Configuration

If your server or network requires an HTTP, HTTPS, or SOCKS proxy to reach the Telegram API or Google Gemini endpoints:

1. Specify your proxy URL in `.env`:
   ```env
   HTTP_PROXY=http://127.0.0.1:10808
   HTTPS_PROXY=http://127.0.0.1:10808
   NO_PROXY=localhost,127.0.0.1,::1
   ```
   *(SOCKS5 proxies are also supported for Telegram polling: `socks5://127.0.0.1:10808`)*

2. **How it works**:
   - **Telegram polling**: `aiogram` routes network requests through `aiohttp-socks` using `HTTP_PROXY`.
   - **Docker & Subprocesses**: The Docker entrypoint script normalizes and exports uppercase and lowercase proxy variables (`HTTP_PROXY`, `http_proxy`, `HTTPS_PROXY`, `https_proxy`, `ALL_PROXY`, `all_proxy`, `NO_PROXY`, `no_proxy`), ensuring `agy` CLI subprocesses seamlessly inherit proxy settings.

---

## How to Run

### Method 1: Docker Compose (Recommended)

Run the bot inside an isolated Docker container with the `agy` CLI pre-installed, automatic signal handling (`init: true`), and data persistence:

```bash
# 1. Build and start container in the background
docker compose up -d

# 2. View live logs
docker compose logs -f

# 3. Check container health status
docker compose ps

# 4. Stop the bot cleanly
docker compose down
```

**Persistent Volumes in Docker:**
- `agy-data`: Persists agent brain memory, conversations, and settings (`/root/.gemini/antigravity-cli`).
- `bot-sessions`: Preserves active chat session IDs and state across container restarts (`/app/data/sessions.json`).
- `bot-workspace`: Working directory where the agent creates and edits files (`/root/workspace`). To inspect or edit files directly on your host machine, you can bind-mount a host folder (e.g. `./workspace:/root/workspace`) by uncommenting Option B in `docker-compose.yml`.

### Method 2: Local Development with `uv`

Ensure you have installed the Antigravity CLI on your machine:
```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

Run the bot with `uv`:
```bash
# Sync dependencies
uv sync

# Run fast tests only (default — skips slow/aiogram tests)
uv run pytest

# Run all tests including slow ones
uv run pytest --run-slow

# Format and check code
uv run ruff format .
uv run ruff check .

# Start the bot
uv run python main.py
```

### Method 3: Systemd Service (VPS Deployment)

Create `/etc/systemd/system/telegram-antigravity-bot.service`:

```ini
[Unit]
Description=Antigravity AI Agent Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/telegram-antigravity-bot
ExecStart=/root/.local/bin/uv run python /root/telegram-antigravity-bot/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-antigravity-bot.service
sudo journalctl -u telegram-antigravity-bot.service -f
```

## Security

> [!CAUTION]
> **Unrestricted Agent Permissions — Read Before Running**
>
> This bot runs the Antigravity CLI with `--dangerously-skip-permissions`, which **auto-approves every tool call** without prompting — including shell commands, file writes, file deletions, and network requests. This is required because `agy` runs in headless mode (no TTY) where interactive permission prompts are impossible; without this flag, all write operations would be silently denied and the agent would be unable to do any useful work.
>
> **What this means in practice:** if you ask the agent to "clean up old files" or "fix my config", it can and will modify or delete files on the host filesystem without asking for confirmation. **Do not trust the bot with access to sensitive system files, credentials, or data you cannot afford to lose.**
>
> **How to stay safe:**
> - 🐳 **Use Docker** (strongly recommended) — the container isolates the agent's filesystem so it cannot touch your host files.
> - 📁 **Point workspaces to dedicated project directories only** — never set `DEFAULT_WORKSPACE` to `/`, `~`, or paths containing personal files, SSH keys, or system configs.
> - 🔒 **Keep `ALLOWED_USER_IDS` tight** — only your own Telegram account should have access; anyone with access can execute arbitrary commands on the host.
> - 💾 **Back up important data** — treat the agent like a junior dev with root access: helpful but capable of mistakes.

- **Strict User Authorization**: The bot rejects messages from any user not listed in `ALLOWED_USER_IDS` and logs unauthorized attempts. Leaving this empty on first run allows you to safely discover your Telegram ID via `/start`.
- **Private Chat Only**: The bot operates strictly in private 1-on-1 chats and rejects group/channel messages to prevent group members from triggering or inspecting server execution.
- **Bot Token**: The bot token is read from `.env`, which is strictly excluded from version control.
- **Docker vs. Host PC Safety**:
  - When running unattended on a VPS or remote machine, **Docker Compose is strongly recommended** for filesystem containment.
  - The Docker container runs as `root` intentionally to give the `agy` CLI sub-processes full flexibility to manage developer tooling and dependencies without permission barriers.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
