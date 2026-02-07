# Agent Zero Telegram Bot — Research & Brainstorming

> **Goal**: Build a standalone Telegram bot that lets a user interact with a running Agent Zero instance via Telegram commands and messages.

---

## Table of Contents

1. [Agent Zero API Analysis](#1-agent-zero-api-analysis)
2. [Telegram Bot Framework Selection](#2-telegram-bot-framework-selection)
3. [Architecture & Integration Design](#3-architecture--integration-design)
4. [Command Design](#4-command-design)
5. [Technical Implementation Plan](#5-technical-implementation-plan)
6. [Docker Deployment Strategy](#6-docker-deployment-strategy)
7. [Open Questions & Considerations](#7-open-questions--considerations)

---

## 1. Agent Zero API Analysis

### API Routing Convention

Agent Zero registers API handlers automatically from Python files in `python/api/`. The URL path is derived from the filename:
- `api_message.py` → `POST /api_message`
- `projects.py` → `POST /projects`
- `chat_create.py` → `POST /chat_create`
- `poll.py` → `POST /poll`
- `api_reset_chat.py` → `POST /api_reset_chat`
- `api_terminate_chat.py` → `POST /api_terminate_chat`

### Authentication

Endpoints that require API key auth use the `X-API-KEY` header (or `api_key` in JSON body). The valid key is the `mcp_server_token` from A0 settings.

```python
# Two ways to authenticate:
# 1. Header (preferred)
headers = {"X-API-KEY": "your-mcp-server-token"}

# 2. JSON body
{"api_key": "your-mcp-server-token", ...}
```

### Key Endpoints

#### `POST /api_message` — Send a message to Agent Zero (External API)

**Auth**: API key required, no web auth, no CSRF.

**Request body**:
```json
{
    "context_id": "optional-existing-context-id",
    "message": "Hello, Agent Zero!",
    "attachments": [
        {
            "filename": "file.txt",
            "base64": "base64-encoded-content"
        }
    ],
    "lifetime_hours": 24,
    "project_name": "optional-project-name",
    "agent_profile": "optional-agent-profile"
}
```

**Response**:
```json
{
    "context_id": "generated-or-existing-context-id",
    "response": "Agent Zero's response text"
}
```

**Key behaviors**:
- If `context_id` is empty/omitted, creates a **new** context (chat)
- If `context_id` is provided, continues the existing conversation
- `project_name` can only be set on the **first message** of a context
- `agent_profile` must match existing context if context already exists
- `lifetime_hours` controls auto-cleanup of the chat (default 24h)
- The call is **synchronous** — it waits for the agent to finish processing and returns the full response
- Attachments are base64-encoded and saved to `/a0/usr/uploads/`

#### `POST /projects` — Manage projects

**Auth**: Web auth + CSRF (standard UI endpoint).

**Actions**:
```json
// List all projects
{"action": "list"}
// Response: {"ok": true, "data": [{"name": "...", "title": "...", ...}]}

// List as options (key/label pairs)
{"action": "list_options"}
// Response: {"ok": true, "data": [{"key": "project_name", "label": "Project Title"}]}

// Activate project on a context
{"action": "activate", "context_id": "ctx-id", "name": "project_name"}

// Deactivate project on a context
{"action": "deactivate", "context_id": "ctx-id"}
```

**⚠️ Important**: The `/projects` endpoint uses standard web auth (session cookies + CSRF), NOT API key auth. This means we **cannot** directly call it from the Telegram bot with just an API key.

**Workaround options**:
1. The `/api_message` endpoint accepts `project_name` on first message — so we can activate a project when creating a new chat
2. We could propose a PR to add API-key-authenticated project management endpoints
3. We can list projects by reading the filesystem directly: projects live in `/a0/usr/projects/<name>/`

#### `POST /chat_create` — Create a new chat

**Auth**: Web auth + CSRF (standard UI endpoint).

**Request**:
```json
{"current_context": "optional-current-ctx", "new_context": "optional-guid"}
```

**Note**: Since `/api_message` auto-creates contexts when `context_id` is empty, we don't strictly need this endpoint. Just sending a message without a context_id creates a new chat.

#### `POST /api_reset_chat` — Reset a chat (clear history)

**Auth**: API key required.

**Request**:
```json
{"context_id": "ctx-id-to-reset"}
```

#### `POST /api_terminate_chat` — Delete a chat entirely

**Auth**: API key required.

**Request**:
```json
{"context_id": "ctx-id-to-delete"}
```

#### `POST /poll` — Get current state snapshot

**Auth**: Web auth + CSRF.

**Request**:
```json
{"context": "ctx-id", "log_from": 0, "notifications_from": 0, "timezone": "UTC"}
```

**Returns**: Full state including list of all contexts (chats), logs, notifications.

### API Endpoints Summary for Bot

| Feature | Endpoint | Auth | Usable from Bot? |
|---------|----------|------|-------------------|
| Send message | `POST /api_message` | API Key | ✅ Yes |
| Reset chat | `POST /api_reset_chat` | API Key | ✅ Yes |
| Delete chat | `POST /api_terminate_chat` | API Key | ✅ Yes |
| List projects | `POST /projects` | Web Auth | ❌ Not directly |
| Activate project | `POST /projects` | Web Auth | ❌ Not directly |
| Create chat | `POST /chat_create` | Web Auth | ⚠️ Use /api_message instead |
| Poll state/chats | `POST /poll` | Web Auth | ❌ Not directly |

### Filesystem-Based Alternatives

Since the bot runs on the same VPS (or can mount the same volumes), we can read A0's filesystem:

- **List projects**: Read directories in `/a0/usr/projects/` (or the mapped host path)
- **List chats**: Read directories in `/a0/usr/chats/` — each subfolder is a context ID containing `chat.json`
- **Chat metadata**: Parse `chat.json` for name, created_at, last_message, project data

However, filesystem access from a separate container requires shared Docker volumes.

---

## 2. Telegram Bot Framework Selection

### Recommendation: **aiogram 3.x**

| Aspect | aiogram 3.x | python-telegram-bot |
|--------|-------------|---------------------|
| Async | Native asyncio/aiohttp | Async via asyncio (v20+) |
| Performance | Superior for concurrent ops | Good |
| Architecture | Routers, middleware, FSM built-in | Handlers, persistence |
| Telegram API | Fast updates to latest Bot API | Slightly slower updates |
| Best for | Production async bots | Beginners, simpler bots |

**Why aiogram**:
- Native async — perfect since we need to make async HTTP calls to A0's API
- Router-based architecture for clean command organization
- FSM (Finite State Machine) for tracking conversation state per user
- Middleware support for injecting the API client session
- Active development, fast Telegram Bot API updates

### Key Dependencies

```
aiogram>=3.15
aiohttp>=3.9
python-dotenv>=1.0
```

---

## 3. Architecture & Integration Design

### High-Level Architecture

```
┌─────────────────┐     Telegram API      ┌──────────────────┐
│   Telegram App   │ ◄──────────────────► │  Telegram Servers  │
│   (User Phone)   │                      └────────┬─────────┘
└─────────────────┘                                │
                                                   │ Long Polling
                                                   ▼
                                          ┌──────────────────┐
                                          │  Telegram Bot     │
                                          │  (Python/aiogram) │
                                          │  Docker Container │
                                          └────────┬─────────┘
                                                   │
                                                   │ HTTP POST
                                                   │ (aiohttp)
                                                   ▼
                                          ┌──────────────────┐
                                          │  Agent Zero       │
                                          │  Docker Container │
                                          │  Port 80/50080   │
                                          └──────────────────┘
```

### Communication Pattern

1. **User sends message/command** in Telegram
2. **Bot receives** via long polling (aiogram `start_polling`)
3. **Bot sends HTTP POST** to A0's `/api_message` endpoint with `X-API-KEY`
4. **A0 processes** the message (this can take seconds to minutes)
5. **A0 returns** the response synchronously
6. **Bot forwards** the response back to the Telegram user

### State Management

The bot needs to track per-user state:

| State | Storage | Purpose |
|-------|---------|--------|
| Current A0 context_id | In-memory dict or FSM | Which A0 chat the user is talking to |
| Current project | In-memory dict or FSM | Which project is active |
| Available chats | Fetched on-demand | For /chats command |
| Available projects | Fetched on-demand | For /projects command |

**Simple approach**: Use a Python dict `{telegram_user_id: {"context_id": "...", "project": "..."}}`
Persist to a JSON file for restart survival.

### Long-Running Responses

A0's `/api_message` is synchronous and can take a long time (agent might run code, browse web, etc.).

**Strategy**:
1. Send a "⏳ Processing..." message immediately to the user
2. Make the HTTP call to A0 in the background (async)
3. When A0 responds, edit or reply with the actual response
4. Handle timeouts gracefully (A0 might take 2-5+ minutes)

```python
@router.message()
async def handle_message(message: Message):
    processing_msg = await message.answer("⏳ Processing...")
    try:
        result = await a0_client.send_message(context_id, message.text)
        await processing_msg.edit_text(format_response(result))
    except asyncio.TimeoutError:
        await processing_msg.edit_text("⏰ Request timed out. Agent may still be processing.")
```

---

## 4. Command Design

### Phase 1 Commands (MVP)

#### `/start`
- Welcome message
- Auto-create a new A0 chat context
- Store the context_id for this Telegram user

#### `/new [project_name]`
- Create a new A0 chat
- Optionally activate a project on it
- Implementation: Send a message to `/api_message` with empty `context_id` and optional `project_name`

```
User: /new
Bot: 🆕 New chat created! Context: abc-123

User: /new my_project
Bot: 🆕 New chat created with project "my_project"! Context: abc-123
```

#### `/chats`
- List available A0 chats
- Show inline keyboard buttons to switch between chats
- **Implementation challenge**: No API-key-authenticated endpoint to list chats
- **Solution**: Read chat folders from shared Docker volume, or maintain our own chat registry

```
User: /chats
Bot: 📋 Your chats:
  [Chat 1 - 2h ago] [Chat 2 - 1d ago] [Chat 3 - 3d ago]
  Tap to switch.
```

#### `/projects`
- List available A0 projects
- Show inline keyboard to select a project for the next new chat
- **Implementation**: Read project directories from shared volume, or add an API endpoint

```
User: /projects
Bot: 📁 Available projects:
  [agent_zero] [my_project] [research]
  Select to use with /new
```

### Phase 2 Commands (Future)

| Command | Description |
|---------|-------------|
| `/reset` | Reset current chat (clear history) |
| `/delete` | Delete current chat |
| `/status` | Show current chat info, active project |
| `/help` | List all commands |
| `/cancel` | Cancel current processing |
| `/attach` | Send a file to A0 |

### Regular Messages

Any non-command message is forwarded to A0 via `/api_message` using the user's current `context_id`.

---

## 5. Technical Implementation Plan

### Project Structure

```
agent-zero-telegram/
├── bot/
│   ├── __init__.py
│   ├── main.py              # Entry point, bot initialization, polling
│   ├── config.py             # Load config from JSON/env
│   ├── a0_client.py          # aiohttp client for A0 API
│   ├── state.py              # User state management (context tracking)
│   ├── formatters.py         # Format A0 responses for Telegram
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── commands.py       # /start, /new, /chats, /projects, /help
│   │   └── messages.py       # Regular message forwarding
│   └── middleware/
│       ├── __init__.py
│       └── auth.py           # Optional: restrict to allowed Telegram user IDs
├── config.json               # Configuration file
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
└── research.md               # This file
```

### Config File (`config.json`)

```json
{
    "telegram": {
        "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
        "allowed_user_ids": [123456789],
        "parse_mode": "Markdown"
    },
    "agent_zero": {
        "host": "http://agent-zero",
        "port": 80,
        "api_key": "YOUR_MCP_SERVER_TOKEN",
        "default_project": null,
        "timeout_seconds": 300,
        "lifetime_hours": 24
    },
    "state_file": "/data/state.json"
}
```

### A0 Client (`a0_client.py`)

```python
import aiohttp
from typing import Optional

class AgentZeroClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-API-KEY": self.api_key},
                timeout=self.timeout
            )
        return self._session

    async def send_message(
        self,
        message: str,
        context_id: str = "",
        project_name: str = None,
        attachments: list = None
    ) -> dict:
        session = await self.get_session()
        payload = {
            "message": message,
            "context_id": context_id,
        }
        if project_name:
            payload["project_name"] = project_name
        if attachments:
            payload["attachments"] = attachments

        async with session.post(
            f"{self.base_url}/api_message",
            json=payload
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def reset_chat(self, context_id: str) -> dict:
        session = await self.get_session()
        async with session.post(
            f"{self.base_url}/api_reset_chat",
            json={"context_id": context_id}
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def terminate_chat(self, context_id: str) -> dict:
        session = await self.get_session()
        async with session.post(
            f"{self.base_url}/api_terminate_chat",
            json={"context_id": context_id}
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
```

### Response Formatting

A0 returns markdown-formatted responses. Telegram supports a subset of Markdown.

**Challenges**:
- A0 uses full Markdown (headers, tables, code blocks, LaTeX)
- Telegram MarkdownV2 has strict escaping rules
- Long responses may exceed Telegram's 4096 character limit

**Strategy**:
1. Use `parse_mode="HTML"` (more forgiving than MarkdownV2)
2. Convert A0 markdown to Telegram HTML (or strip unsupported formatting)
3. Split long messages into chunks at natural boundaries (paragraphs, code blocks)
4. Send code blocks as separate messages or as documents

---

## 6. Docker Deployment Strategy

### Approach: Separate Container, Same Docker Network

The Telegram bot runs in its own minimal container alongside Agent Zero on the same Docker network.

```yaml
# docker-compose.yml (bot only — A0 runs separately)
version: '3.8'

services:
  telegram-bot:
    build: .
    container_name: a0-telegram-bot
    restart: unless-stopped
    environment:
      - CONFIG_PATH=/app/config.json
    volumes:
      - ./config.json:/app/config.json:ro
      - bot-data:/data  # Persist state
    networks:
      - a0-network  # Same network as Agent Zero

volumes:
  bot-data:

networks:
  a0-network:
    external: true  # Created by A0's docker-compose
```

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY config.json .

CMD ["python", "-m", "bot.main"]
```

### Network Connectivity

Since both containers are on the same Docker network:
- Bot reaches A0 via Docker service name: `http://agent-zero:80` (or whatever the A0 container name is)
- No need to expose A0's port to the host for the bot
- Long polling means the bot doesn't need any inbound ports

### Alternative: Same Container

Could also run the bot as a background process inside the A0 container, but separate containers are cleaner and follow Docker best practices.

---

## 7. Open Questions & Considerations

### Critical Questions

1. **Chat listing without web auth**: The `/poll` and `/projects` endpoints require web auth. Options:
   - a) Add new API-key-authenticated endpoints to A0 (PR opportunity)
   - b) Share Docker volumes and read filesystem directly
   - c) The bot maintains its own registry of chats it created
   - **Recommended**: Option (c) for MVP — the bot tracks all chats it creates in its own state file. This is simplest and doesn't require A0 changes.

2. **Project listing**: Same issue as chat listing.
   - For MVP: hardcode project list in config, or read from shared volume
   - Long-term: API endpoint with API key auth

3. **Response timeout**: A0 can take minutes to respond. `aiohttp` default timeout may be too short.
   - Set timeout to 300s (5 min) or higher
   - Show typing indicator while waiting
   - Consider a polling approach: send message async, then poll for completion

4. **Multi-user support**: Should the bot support multiple Telegram users?
   - MVP: Single user (restrict via `allowed_user_ids` in config)
   - Future: Multi-user with per-user state and context isolation

5. **Message length**: Telegram has a 4096 char limit per message.
   - Split long A0 responses into multiple messages
   - Or send as a document/file for very long responses

### Security Considerations

- **Bot token**: Store in config.json or env var, never commit
- **API key**: Same — config.json or env var
- **User restriction**: `allowed_user_ids` whitelist to prevent unauthorized access
- **No inbound ports**: Long polling means no attack surface from the internet

### Future Enhancements

- **Inline keyboards** for chat/project selection (better UX than text commands)
- **File attachments**: Forward Telegram photos/documents to A0 as base64 attachments
- **Streaming responses**: Poll A0 for partial results and update the Telegram message progressively
- **Notification forwarding**: A0 notifications → Telegram messages
- **Voice messages**: Transcribe Telegram voice → send text to A0
- **Image responses**: If A0 generates images, send them as Telegram photos

---

## Sources & References

- [aiogram 3.x Documentation](https://docs.aiogram.dev/en/latest/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- Agent Zero source code: `python/api/api_message.py`, `python/api/projects.py`, `python/api/chat_create.py`
- Agent Zero API auth: `run_ui.py` — `requires_api_key` decorator uses `X-API-KEY` header with `mcp_server_token`
- Perplexity research on aiogram 3.x best practices (Feb 2025)

---

## 8. Telegram Authentication & User Verification

### Research Findings (Perplexity, Feb 2025)

### The Problem

The Telegram bot needs to restrict access to authorized users only. Since this is a private bot acting as an interface to a powerful AI agent, unauthorized access must be prevented.

### Proposed Flow: First-Time Verification with CLI Approval

**Concept**: When the bot receives a message from an unknown sender, it generates a 6-character verification code and sends it back via Telegram. The server admin then approves the user by running a CLI command in the bot's container.

#### Step-by-step:

1. **Unknown user sends first message** to the bot
2. **Bot generates a 6-char alphanumeric code** (using `secrets` module for crypto-safe randomness)
3. **Bot sends the code** back to the user on Telegram: "Your verification code is: `ABC123`. Please ask the admin to approve you."
4. **Bot logs the pending verification** with user_id, username, code, and timestamp
5. **Admin runs CLI command** in the bot container: `python -m bot.cli approve ABC123`
6. **Bot stores the approved `sender_id`** in config.json
7. **Bot notifies the user** on Telegram: "✅ You've been approved!"
8. **All subsequent messages** from this sender_id are processed normally

#### Key Design Decisions:

- **Store `sender_id` in config.json** alongside A0 host/port settings
- **CLI-based approval** (not Telegram command) — more secure, requires server access
- **Code expiry**: 10 minutes to prevent stale codes
- **Silent rejection**: After initial code message, ignore all messages from unapproved users
- **Multiple users**: Support a list of approved sender_ids

### Config.json Structure (Updated)

```json
{
    "telegram": {
        "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
        "approved_users": [],
        "parse_mode": "HTML"
    },
    "agent_zero": {
        "host": "http://agent-zero",
        "port": 80,
        "api_key": "YOUR_MCP_SERVER_TOKEN",
        "default_project": null,
        "timeout_seconds": 300,
        "lifetime_hours": 24
    },
    "state_file": "/data/state.json"
}
```

### Implementation Pattern (aiogram 3.x)

#### Middleware-Based Auth

Use aiogram's outer middleware to check every incoming update against the approved users list before any handler runs:

```python
class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = extract_user_id(event)
        if user_id not in approved_users:
            if user_id not in pending_verifications:
                # Generate code, send to user, store pending
                code = generate_6char_code()
                store_pending(user_id, code)
                await send_verification_message(user_id, code)
            return  # Block all handlers for unapproved users
        return await handler(event, data)
```

#### CLI Approval Script

```bash
# Run inside the bot container:
python -m bot.cli approve ABC123

# Or list pending verifications:
python -m bot.cli pending
```

The CLI script:
1. Reads pending verifications from state file
2. Finds the matching code
3. Moves the user_id to `approved_users` in config.json
4. Optionally sends a Telegram notification to the user (requires bot token)

### Security Best Practices

- Use `secrets.choice()` not `random.choice()` for code generation
- Expire codes after 10 minutes
- Rate-limit code generation (max 1 per minute per user)
- Silent rejection after initial code message (don't leak bot existence)
- CLI approval requires Docker exec access = server-level security
- Store approved user IDs as integers (Telegram user IDs are numeric)
