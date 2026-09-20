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
| /logs | Show recent bot logs |

Any other message is treated as a prompt for the agent.

## Requirements

- Python 3.8+
- The Antigravity CLI (`agy`) installed on the server
- A Telegram bot token from @BotFather

## Quick Setup

### 1. Clone the repository

```bash
git clone https://github.com/daffaroffi/telegram-antigravity-bot.git
cd telegram-antigravity-bot
```

### 2. Configure environment variables

Create your configuration file from the example:

```bash
cp .env.example .env
```

Then edit `.env` and fill in your values:

```env
TELEGRAM_BOT_TOKEN=123456789:AA...your-token-from-botfather
ALLOWED_USER_IDS=8927082329
AGY_PATH=/root/.local/bin/agy
DEFAULT_WORKSPACE=/root/my-project
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Bot token from @BotFather |
| `ALLOWED_USER_IDS` | Yes | - | Comma-separated Telegram user IDs allowed to use the bot |
| `AGY_PATH` | No | `/root/.local/bin/agy` | Path to the Antigravity CLI binary |
| `DEFAULT_WORKSPACE` | No | `/root/my-project` | Default working directory for the agent |
| `HTTP_PROXY` | No | - | Optional HTTP/HTTPS/SOCKS5 proxy URL for Telegram connection |

### 3. Install dependencies and run

Using `uv` (recommended):

```bash
# Sync dependencies
uv sync

# Run tests
uv run pytest

# Format code
uv run ruff format

# Start bot (either bot.py or main.py)
uv run python bot.py
# or: uv run python main.py
```

Or using standard `venv`:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bot.py
```

### 4. Run as a systemd service (recommended for a VPS)

Create `/etc/systemd/system/telegram-antigravity-bot.service`:

```ini
[Unit]
Description=Antigravity AI Agent Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/my-project/telegram-antigravity-bot
ExecStart=/root/my-project/telegram-antigravity-bot/venv/bin/python /root/my-project/telegram-antigravity-bot/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-antigravity-bot.service
sudo systemctl start telegram-antigravity-bot.service
```

## Security

- The bot rejects messages from any user not listed in `ALLOWED_USER_IDS` and logs unauthorized attempts.
- The bot token is read from `.env`, which is excluded from version control.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
