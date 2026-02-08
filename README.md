# Agent Zero Telegram Bot

A standalone Telegram bot that acts as a messaging bridge between Telegram and [Agent Zero](https://github.com/agent0ai/agent-zero). Chat with your AI agent from anywhere using Telegram.

## Overview

- **One bot = one project = one context** — Simple static configuration
- **Multi-user support** — Add 1-3 approved users who share the same conversation
- **Secure approval flow** — Admin approves users via CLI inside the container
- **Mobile-first** — Interact with Agent Zero from your phone without opening a browser
- **Persistent state** — Approved users and auto-created contexts survive restarts

## Features

- ✅ **Text messaging** — Send messages to Agent Zero and receive formatted responses
- ✅ **User approval system** — Verification codes for first-time users
- ✅ **Admin CLI** — Approve, list, and revoke users via command line
- ✅ **Auto-context creation** — Bot automatically creates and persists chat contexts
- ✅ **Markdown to HTML** — A0's markdown responses render beautifully in Telegram
- ✅ **Connection status** — `/status` command shows project, context, and connectivity

## Prerequisites

1. **Docker and Docker Compose** installed on your server
2. **Agent Zero instance** running and accessible on the same Docker network
3. **Telegram Bot Token** — Get one from [@BotFather](https://t.me/botfather)
4. **Agent Zero API Key** — Found in your A0 instance settings

## Quick Start

### 1. Clone and Configure

```bash
git clone <repository-url>
cd agent-zero-telegram

# Copy example config and edit
cp config.example.json config.json
nano config.json
```

### 2. Edit `config.json`

```json
{
    "telegram": {
        "bot_token": "YOUR_BOT_TOKEN_FROM_BOTFATHER",
        "approved_users": []
    },
    "agent_zero": {
        "host": "http://agent-zero",
        "port": 80,
        "api_key": "YOUR_AGENT_ZERO_API_KEY",
        "fixed_project_name": "my-project",
        "fixed_context_id": null
    }
}
```

**Configuration Options:**

| Field | Required | Description |
|-------|----------|-------------|
| `bot_token` | ✅ | From @BotFather |
| `approved_users` | ✅ | Start empty `[]`, populate after approvals |
| `host` | ✅ | Agent Zero hostname (Docker service name or IP) |
| `port` | ✅ | Agent Zero port (usually 80) |
| `api_key` | ✅ | Your A0 API key |
| `fixed_project_name` | ❌ | All messages use this project (null = A0 default) |
| `fixed_context_id` | ❌ | Use specific context (null = auto-create) |

### 3. Create Docker Network

```bash
docker network create a0-network
```

### 4. Start the Bot

```bash
docker-compose up -d
```

### 5. View Logs

```bash
docker-compose logs -f
```

## User Approval Workflow

### For New Users

1. User sends `/start` or any message to the bot
2. Bot replies with a verification code (e.g., `a3f9b2`)
3. User sends this code to the admin

### For Admin

```bash
# List pending approvals
docker exec agent-zero-telegram-bot python -m bot.cli pending

# Approve a user by code
docker exec agent-zero-telegram-bot python -m bot.cli approve a3f9b2

# List all approved users
docker exec agent-zero-telegram-bot python -m bot.cli users

# Revoke a user's access
docker exec agent-zero-telegram-bot python -m bot.cli revoke 123456789
```

After approval, the user receives a "✅ You've been approved!" message.

## Available Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with project info |
| `/help` | Show available commands |
| `/status` | Show connection status, project, and context ID |

## Project Structure

```
agent-zero-telegram/
├── bot/                    # Main Python package
│   ├── __main__.py        # Entry point
│   ├── main.py            # Bot initialization
│   ├── config.py          # Configuration models
│   ├── state.py           # State management
│   ├── a0_client.py       # Agent Zero API client
│   ├── formatters.py      # Markdown to HTML conversion
│   ├── cli.py             # Admin CLI commands
│   ├── middleware/        # Authentication middleware
│   └── routers/           # Message and command handlers
├── config.example.json    # Configuration template
├── config.json            # Your configuration (gitignored)
├── docker-compose.yml     # Docker Compose setup
├── Dockerfile             # Multi-stage build
├── requirements.txt       # Python dependencies
└── data/                  # Persistent state (gitignored)
```

## Configuration Scenarios

### Scenario A: Simple Setup (Auto-create everything)
```json
{
    "agent_zero": {
        "fixed_project_name": null,
        "fixed_context_id": null
    }
}
```
Bot will use A0 default project and auto-create a context on first message.

### Scenario B: Fixed Project, Auto Context
```json
{
    "agent_zero": {
        "fixed_project_name": "my-project",
        "fixed_context_id": null
    }
}
```
All messages go to `my-project`, context is auto-created and persisted.

### Scenario C: Fully Static (Production)
```json
{
    "agent_zero": {
        "fixed_project_name": "production",
        "fixed_context_id": "abc-123-context-id"
    }
}
```
All users share the exact same project and context.

## Troubleshooting

### Bot doesn't respond to messages

1. Check logs: `docker-compose logs -f`
2. Verify bot token is correct in `config.json`
3. Ensure you've been approved (check `docker exec ... bot.cli users`)

### "Agent Zero is not reachable" error

1. Verify Agent Zero container is running: `docker ps`
2. Check they're on the same network: `docker network inspect a0-network`
3. Test connectivity from bot container:
   ```bash
   docker exec agent-zero-telegram-bot python -c \
     "import aiohttp; import asyncio; \
      asyncio.run(aiohttp.ClientSession().get('http://agent-zero'))"
   ```

### Context not persisting

1. Check `data/` directory is writable: `ls -la data/`
2. Verify `state.json` is being created
3. Check logs for "State saved" messages

### User approval not working

1. Ensure code hasn't expired (10 minute limit)
2. Check pending codes: `docker exec ... bot.cli pending`
3. Verify config.json is being re-read (no restart needed)

## Development

### Run locally (without Docker)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit config
cp config.example.json config.json
# Edit config.json with your values

# Run the bot
python -m bot
```

### Run CLI commands locally

```bash
python -m bot.cli pending
python -m bot.cli approve <code>
python -m bot.cli users
python -m bot.cli revoke <user_id>
```

## Architecture

The bot follows a **static configuration** philosophy:

- **One bot per project** — No runtime project switching
- **Shared context** — All approved users collaborate in the same conversation
- **Minimal state** — Only pending verifications and auto-created context_id
- **Configuration over environment** — Single `config.json` file

See `specs/1-initial-implementation/architecture.md` for detailed design.

## Security Notes

- Bot token and API key never appear in logs
- Runs as non-root user inside container
- No inbound ports exposed (uses long polling)
- User approval requires server access (CLI)
- Verification codes expire after 10 minutes

## License

[Your License Here]

## Support

- Agent Zero Documentation: https://github.com/agent0ai/agent-zero
- Issues: [Repository Issues URL]
