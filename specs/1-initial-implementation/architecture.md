# Architecture — Agent Zero Telegram Bot

> **Version**: 1.0 — Initial Implementation  
> **Date**: 2025-02-07  
> **Status**: Approved for implementation

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Technology Choices](#2-technology-choices)
3. [Component Breakdown](#3-component-breakdown)
4. [Data Flow](#4-data-flow)
5. [Directory Structure](#5-directory-structure)
6. [Configuration Schema](#6-configuration-schema)
7. [State Management](#7-state-management)
8. [Docker Deployment](#8-docker-deployment)
9. [Error Handling Strategy](#9-error-handling-strategy)
10. [Security Considerations](#10-security-considerations)

---

## 1. System Overview

The Agent Zero Telegram Bot is a standalone Python service that bridges Telegram messaging with a running Agent Zero (A0) instance. Users interact with A0 through Telegram commands and natural language messages. The bot runs in its own Docker container alongside A0 on the same Docker network.

### High-Level Architecture

```
┌──────────────┐         Telegram Bot API          ┌───────────────────┐
│  User Phone  │ ◄──────────────────────────────► │  Telegram Servers  │
│  (Telegram)  │        HTTPS (managed by TG)      └─────────┬─────────┘
└──────────────┘                                             │
                                                             │ Long Polling
                                                             │ (outbound HTTPS)
                                                             ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Docker Network: a0-network                      │
│                                                                        │
│  ┌─────────────────────────────────┐    HTTP POST     ┌─────────────┐ │
│  │  a0-telegram-bot                │ ──────────────► │  agent-zero  │ │
│  │  ┌───────────────────────────┐  │  /api_message    │              │ │
│  │  │ aiogram 3.x (polling)    │  │  /api_reset_chat │  Port 80     │ │
│  │  │ Auth Middleware           │  │  /api_terminate  │  (internal)  │ │
│  │  │ A0 Client (aiohttp)      │  │  X-API-KEY auth  │              │ │
│  │  │ State Manager             │  │ ◄────────────── │              │ │
│  │  │ Config Manager            │  │  JSON responses  └─────────────┘ │
│  │  └───────────────────────────┘  │                                   │
│  │  Volumes:                       │                                   │
│  │   /app/config.json (bind mount) │                                   │
│  │   /data/ (named volume)         │                                   │
│  └─────────────────────────────────┘                                   │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | aiogram 3.x | Native async, middleware support, FSM, active development |
| Polling vs Webhooks | Long polling | No inbound ports needed, simpler Docker setup, no TLS config |
| A0 communication | HTTP REST via aiohttp | Only API-key-authenticated endpoints used; no web auth dependency |
| Auth model | First-time code verification + CLI approval | Server-level security; no Telegram admin commands that could be spoofed |
| State persistence | Local JSON file | Simple, no database dependency for a single-user/small-user bot |
| Config persistence | Single config.json | Bind-mounted; editable from host; holds both secrets and approved users |
| Deployment | Separate container, same network | Clean separation; independent lifecycle; Docker best practice |

---

## 2. Technology Choices

### Runtime & Language

| Component | Choice | Version |
|-----------|--------|---------|
| Language | Python | 3.12+ |
| Base image | `python:3.12-slim` | Minimal footprint |
| Package manager | pip | Standard |

### Dependencies

| Package | Purpose | Version |
|---------|---------|--------|
| `aiogram` | Telegram Bot framework (async, routers, middleware) | ≥3.15 |
| `aiohttp` | Async HTTP client for A0 API calls | ≥3.9 |
| `pydantic` | Config and state schema validation | ≥2.0 |

**Why these and nothing else:**
- `aiogram` bundles `aiohttp` internally, so we get the HTTP client for free.
- `pydantic` gives us typed config/state models with validation and JSON serialization — prevents config typos from causing runtime errors.
- No database driver, no Redis, no ORM. This is a small bot — JSON files are sufficient.

---

## 3. Component Breakdown

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                      bot package                         │
│                                                          │
│  ┌──────────┐   ┌──────────────┐   ┌─────────────────┐  │
│  │  main.py │──►│  Bot Core    │──►│  Routers        │  │
│  │ (entry)  │   │  (Dispatcher │   │  ├─ commands.py  │  │
│  └──────────┘   │   + Bot)     │   │  └─ messages.py  │  │
│                  └──────┬───────┘   └────────┬────────┘  │
│                         │                    │           │
│                         ▼                    ▼           │
│                  ┌──────────────┐   ┌─────────────────┐  │
│                  │  Middleware   │   │  A0 Client      │  │
│                  │  └─ auth.py  │   │  (aiohttp)      │  │
│                  └──────┬───────┘   └────────┬────────┘  │
│                         │                    │           │
│                         ▼                    │           │
│                  ┌──────────────┐             │           │
│                  │  Config Mgr  │◄────────────┘           │
│                  │  (Pydantic)  │                         │
│                  └──────┬───────┘                         │
│                         │                                │
│                         ▼                                │
│                  ┌──────────────┐                         │
│                  │  State Mgr   │                         │
│                  │  (JSON file) │                         │
│                  └──────────────┘                         │
│                                                          │
│  ┌──────────┐                                            │
│  │  cli.py  │  (standalone CLI — runs outside bot loop)  │
│  └──────────┘                                            │
└─────────────────────────────────────────────────────────┘
```

### 3.1 Bot Core (`main.py`)

**Responsibility**: Application entry point. Wires everything together and starts polling.

**Behavior**:
1. Load config from `config.json`
2. Initialize `Bot` and `Dispatcher` (aiogram)
3. Create `A0Client` instance (shared aiohttp session)
4. Register middleware (auth)
5. Include routers (commands, messages)
6. Start long polling
7. On shutdown: close aiohttp session, flush state

**Key detail**: The `A0Client` and `ConfigManager` instances are injected into handlers via aiogram's built-in dependency injection (`workflow_data` on the Dispatcher).

### 3.2 Auth Middleware (`middleware/auth.py`)

**Responsibility**: Gate every incoming Telegram update. Only approved users reach handlers.

**Type**: aiogram outer middleware on the `Message` update type.

**Behavior**:
- Extract `sender_id` from the incoming message
- If `sender_id` is in `config.approved_users` → pass through to handler
- If `sender_id` has a pending verification → silently drop (do nothing)
- If `sender_id` is unknown:
  1. Generate a 6-character alphanumeric code (`secrets.token_hex(3)` → 6 hex chars)
  2. Store `{code: {user_id, username, timestamp}}` in state file under `pending_verifications`
  3. Send Telegram message: "Your verification code is: `XXXXXX`. Ask the admin to run: `approve XXXXXX`"
  4. Drop the update (do not pass to handler)

**Rate limiting**: Max 1 code per user per 60 seconds. If a code already exists and hasn't expired, silently drop.

**Code expiry**: 10 minutes. Expired codes are cleaned up lazily on next access.

### 3.3 A0 Client (`a0_client.py`)

**Responsibility**: Async HTTP client wrapping all Agent Zero API calls.

**Interface**:

```python
class A0Client:
    async def send_message(
        message: str,
        context_id: str = "",
        project_name: str | None = None,
        attachments: list[dict] | None = None,
    ) -> A0Response  # {context_id: str, response: str}

    async def reset_chat(context_id: str) -> None
    async def terminate_chat(context_id: str) -> None
    async def close() -> None  # cleanup session
```

**Implementation details**:
- Single `aiohttp.ClientSession` created on first use, reused for all requests
- `X-API-KEY` header set on the session (applies to all requests)
- Timeout: configurable, default 300s (5 minutes) — A0 responses are synchronous and can be slow
- All methods raise typed exceptions (`A0ConnectionError`, `A0APIError`, `A0TimeoutError`)

### 3.4 Routers

#### `routers/commands.py` — Command Handlers

| Command | Handler | Behavior |
|---------|---------|----------|
| `/start` | `cmd_start` | Welcome message. If no active context, create one via A0. |
| `/new [project]` | `cmd_new` | Create new A0 chat. Optional project name. Store new context_id in state. |
| `/reset` | `cmd_reset` | Reset current chat history via `/api_reset_chat`. |
| `/delete` | `cmd_delete` | Terminate current chat via `/api_terminate_chat`. Clear from state. |
| `/status` | `cmd_status` | Show current context_id, active project, user info. |
| `/help` | `cmd_help` | List all commands with descriptions. |

#### `routers/messages.py` — Message Handler

**Catches**: All non-command text messages from approved users.

**Flow**:
1. Look up user's current `context_id` from state
2. If no context exists, auto-create one (send with empty `context_id`)
3. Send "⏳ Processing..." reply immediately
4. Call `a0_client.send_message(text, context_id)`
5. Format A0's response for Telegram
6. Edit the "Processing..." message with the actual response
7. If response exceeds 4096 chars, split into multiple messages

### 3.5 CLI Tool (`cli.py`)

**Responsibility**: Admin command-line interface for user approval. Runs as a standalone script, not inside the bot's event loop.

**Commands**:

```bash
# Approve a pending user by verification code
python -m bot.cli approve <CODE>

# List all pending verifications
python -m bot.cli pending

# List all approved users
python -m bot.cli users

# Revoke an approved user by Telegram user ID
python -m bot.cli revoke <USER_ID>
```

**Implementation**:
- Uses `argparse` for CLI parsing
- Reads/writes `config.json` directly (for approved_users)
- Reads/writes state file directly (for pending_verifications)
- For the `approve` command: optionally sends a Telegram notification to the user via the Bot API (requires `bot_token` from config — uses a one-shot synchronous HTTP call or a small async helper)

**Important**: The CLI operates on the same `config.json` and state file as the running bot. The bot watches/reloads config on change (or the CLI triggers a reload signal). Simplest approach: the bot re-reads `config.json` on every auth check (file is tiny, I/O is negligible).

### 3.6 Config Manager (`config.py`)

**Responsibility**: Load, validate, and provide access to configuration.

**Implementation**: Pydantic models that load from and save to `config.json`.

```python
class TelegramConfig(BaseModel):
    bot_token: str
    approved_users: list[int] = []
    parse_mode: str = "HTML"

class AgentZeroConfig(BaseModel):
    host: str = "http://agent-zero"
    port: int = 80
    api_key: str
    default_project: str | None = None
    timeout_seconds: int = 300
    lifetime_hours: int = 24

class BotConfig(BaseModel):
    telegram: TelegramConfig
    agent_zero: AgentZeroConfig
    state_file: str = "/data/state.json"
```

**Key behaviors**:
- `load(path) -> BotConfig`: Read and validate config.json
- `save(path)`: Write current config back (used by CLI to persist approved users)
- The bot re-reads `approved_users` from disk on every auth middleware call (cheap for a small file, ensures CLI changes are picked up immediately without restart)

### 3.7 State Manager (`state.py`)

**Responsibility**: Track runtime state that must survive restarts.

**Schema**:

```python
class PendingVerification(BaseModel):
    user_id: int
    username: str | None = None
    code: str
    created_at: datetime

class UserState(BaseModel):
    context_id: str | None = None
    project: str | None = None

class BotState(BaseModel):
    pending_verifications: dict[str, PendingVerification] = {}  # code -> verification
    users: dict[int, UserState] = {}  # telegram_user_id -> state
```

**Persistence**: JSON file at the path specified by `config.state_file` (default `/data/state.json`).

**Write strategy**: Write-on-change with atomic file replacement (`write to tmp + rename`). No periodic flush needed — state changes are infrequent.

### 3.8 Response Formatter (`formatters.py`)

**Responsibility**: Convert A0's markdown responses into Telegram-safe HTML.

**Challenges**:
- A0 outputs full Markdown (headers, tables, code blocks, bold, italic, links, LaTeX)
- Telegram's HTML mode supports: `<b>`, `<i>`, `<code>`, `<pre>`, `<a>`, `<blockquote>`
- Telegram message limit: 4096 characters

**Strategy**:
1. Convert Markdown → Telegram HTML (lightweight conversion, not a full parser)
   - `**bold**` → `<b>bold</b>`
   - `` `code` `` → `<code>code</code>`
   - Code blocks → `<pre>code</pre>`
   - `# Headers` → `<b>Header</b>` (Telegram has no header tag)
   - Links → `<a href="...">text</a>`
   - Strip unsupported elements (tables → plain text, LaTeX → raw text)
2. Split messages at 4096-char boundaries, preferring splits at paragraph breaks
3. If a single code block exceeds the limit, send it as a document/file

---

## 4. Data Flow

### 4.1 Message Flow (Happy Path)

```
User (Telegram)          Bot                          Agent Zero
     │                    │                                │
     │  "Summarize X"     │                                │
     │───────────────────►│                                │
     │                    │  [Auth middleware: approved ✓]  │
     │                    │                                │
     │  "⏳ Processing..." │                                │
     │◄───────────────────│                                │
     │                    │  POST /api_message             │
     │                    │  {context_id, message}         │
     │                    │───────────────────────────────►│
     │                    │                                │
     │                    │        (A0 processes...        │
     │                    │         may take minutes)      │
     │                    │                                │
     │                    │  {context_id, response}        │
     │                    │◄───────────────────────────────│
     │                    │                                │
     │                    │  [Format response for TG]      │
     │                    │                                │
     │  [Edit message:    │                                │
     │   formatted reply] │                                │
     │◄───────────────────│                                │
     │                    │                                │
```

### 4.2 Authentication Flow (New User)

```
Unknown User             Bot                     Admin (CLI)
     │                    │                          │
     │  "Hello"           │                          │
     │───────────────────►│                          │
     │                    │  [Auth middleware:        │
     │                    │   user NOT approved]      │
     │                    │                          │
     │                    │  [Generate code: A1B2C3]  │
     │                    │  [Store pending in state]  │
     │                    │                          │
     │  "Your code:       │                          │
     │   A1B2C3"          │                          │
     │◄───────────────────│                          │
     │                    │                          │
     │  (any message)     │                          │
     │───────────────────►│                          │
     │                    │  [Auth middleware:        │
     │                    │   pending → silent drop]  │
     │                    │                          │
     │                    │    docker exec ...        │
     │                    │    python -m bot.cli      │
     │                    │      approve A1B2C3       │
     │                    │◄─────────────────────────│
     │                    │                          │
     │                    │  [CLI: move user_id to    │
     │                    │   config.approved_users]   │
     │                    │  [CLI: remove pending]     │
     │                    │  [CLI: send TG notify]     │
     │                    │                          │
     │  "✅ Approved!"     │                          │
     │◄───────────────────│                          │
     │                    │                          │
     │  (next message     │                          │
     │   processed        │                          │
     │   normally)        │                          │
     │                    │                          │
```

### 4.3 New Chat Flow

```
User                     Bot                          Agent Zero
     │                    │                                │
     │  /new myproject    │                                │
     │───────────────────►│                                │
     │                    │  POST /api_message             │
     │                    │  {context_id: "",              │
     │                    │   message: ".",                │
     │                    │   project_name: "myproject"}   │
     │                    │───────────────────────────────►│
     │                    │                                │
     │                    │  {context_id: "new-uuid",      │
     │                    │   response: "..."}             │
     │                    │◄───────────────────────────────│
     │                    │                                │
     │                    │  [State: save new context_id   │
     │                    │   for this user]               │
     │                    │                                │
     │  "🆕 New chat       │                                │
     │   created with     │                                │
     │   project          │                                │
     │   myproject"       │                                │
     │◄───────────────────│                                │
```

---

## 5. Directory Structure

```
agent-zero-telegram/
├── bot/
│   ├── __init__.py               # Package init
│   ├── __main__.py               # Allows `python -m bot` to run main
│   ├── main.py                   # Entry point: init bot, wire deps, start polling
│   ├── config.py                 # Pydantic config models, load/save
│   ├── state.py                  # Pydantic state models, atomic persistence
│   ├── a0_client.py              # aiohttp wrapper for A0 API endpoints
│   ├── formatters.py             # A0 markdown → Telegram HTML conversion
│   ├── cli.py                    # CLI tool: approve, pending, users, revoke
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── commands.py           # /start, /new, /reset, /delete, /status, /help
│   │   └── messages.py           # Catch-all text message → A0 forwarding
│   └── middleware/
│       ├── __init__.py
│       └── auth.py               # Outer middleware: user verification gate
├── config.json                   # Configuration (bind-mounted in Docker)
├── Dockerfile                    # Container build
├── docker-compose.yml            # Deployment orchestration
├── requirements.txt              # Python dependencies
├── README.md                     # Setup & usage guide
├── research.md                   # Research document
└── specs/
    └── 1-initial-implementation/
        └── architecture.md       # This file
```

**File count**: ~15 Python files. This is intentionally small. No abstraction layers that don't earn their keep.

---

## 6. Configuration Schema

### `config.json`

```json
{
    "telegram": {
        "bot_token": "123456:ABC-DEF...",
        "approved_users": [],
        "parse_mode": "HTML"
    },
    "agent_zero": {
        "host": "http://agent-zero",
        "port": 80,
        "api_key": "your-mcp-server-token",
        "default_project": null,
        "timeout_seconds": 300,
        "lifetime_hours": 24
    },
    "state_file": "/data/state.json"
}
```

### Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `telegram.bot_token` | string | ✅ | — | Telegram Bot API token from @BotFather |
| `telegram.approved_users` | int[] | No | `[]` | List of approved Telegram user IDs |
| `telegram.parse_mode` | string | No | `"HTML"` | Telegram message parse mode |
| `agent_zero.host` | string | No | `"http://agent-zero"` | A0 container hostname/URL |
| `agent_zero.port` | int | No | `80` | A0 HTTP port |
| `agent_zero.api_key` | string | ✅ | — | A0 MCP server token for `X-API-KEY` header |
| `agent_zero.default_project` | string? | No | `null` | Default project for new chats |
| `agent_zero.timeout_seconds` | int | No | `300` | HTTP timeout for A0 API calls |
| `agent_zero.lifetime_hours` | int | No | `24` | A0 chat context lifetime |
| `state_file` | string | No | `"/data/state.json"` | Path to persistent state file |

### Config Access Pattern

- **Bot process**: Reads on startup. Re-reads `approved_users` on every auth check (to pick up CLI changes without restart).
- **CLI process**: Reads and writes directly. Modifies `approved_users` on approve/revoke.
- **Concurrency safety**: Only the CLI writes to config. The bot only reads. No locking needed. The CLI uses atomic write (write tmp → rename).

---

## 7. State Management

### State File (`/data/state.json`)

```json
{
    "pending_verifications": {
        "A1B2C3": {
            "user_id": 123456789,
            "username": "john_doe",
            "code": "A1B2C3",
            "created_at": "2025-02-07T12:00:00Z"
        }
    },
    "users": {
        "123456789": {
            "context_id": "550e8400-e29b-41d4-a716-446655440000",
            "project": "agent_zero"
        }
    }
}
```

### State Lifecycle

| Event | State Change |
|-------|--------------|
| Unknown user sends message | Add entry to `pending_verifications` |
| Admin approves code | Remove from `pending_verifications`, add user_id to `config.approved_users` |
| Code expires (10 min) | Remove from `pending_verifications` (lazy cleanup) |
| `/new` command | Update `users[id].context_id` and `.project` |
| `/delete` command | Clear `users[id].context_id` |
| Auto-create context (first message) | Set `users[id].context_id` |

### Persistence Strategy

- **Write trigger**: Every state mutation triggers an immediate write
- **Write method**: Atomic — `json.dump` to a `.tmp` file, then `os.replace()` to the target path
- **Read**: On startup only (state lives in memory during runtime)
- **Volume**: `/data/` is a named Docker volume, survives container restarts

---

## 8. Docker Deployment

### Container Architecture

```
┌─────────────────────────────────────────────────┐
│              Docker Host (VPS)                    │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │         Docker Network: a0-network        │    │
│  │                                           │    │
│  │  ┌─────────────────┐  ┌───────────────┐  │    │
│  │  │ a0-telegram-bot  │  │  agent-zero   │  │    │
│  │  │                  │  │               │  │    │
│  │  │ python:3.12-slim │  │  Port 80      │  │    │
│  │  │ No exposed ports │  │  (+ 50080     │  │    │
│  │  │                  │──│   external)   │  │    │
│  │  │ Volumes:         │  │               │  │    │
│  │  │  ./config.json   │  └───────────────┘  │    │
│  │  │  bot-data:/data  │                     │    │
│  │  └─────────────────┘                      │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/

CMD ["python", "-m", "bot"]
```

**Notes**:
- `config.json` is NOT copied into the image — it's bind-mounted at runtime
- No exposed ports — long polling is outbound-only
- Minimal image: ~150MB (python:3.12-slim + deps)

### docker-compose.yml

```yaml
services:
  telegram-bot:
    build: .
    container_name: a0-telegram-bot
    restart: unless-stopped
    volumes:
      - ./config.json:/app/config.json
      - bot-data:/data
    networks:
      - a0-network

volumes:
  bot-data:

networks:
  a0-network:
    external: true
```

### Network Connectivity

- The bot reaches A0 at `http://agent-zero:80` (Docker DNS resolves the container name)
- A0's port does NOT need to be exposed to the host for the bot to reach it
- The bot has no inbound ports — zero attack surface from the network

### Admin CLI Access

```bash
# Approve a user
docker exec a0-telegram-bot python -m bot.cli approve A1B2C3

# List pending verifications
docker exec a0-telegram-bot python -m bot.cli pending

# List approved users
docker exec a0-telegram-bot python -m bot.cli users

# Revoke a user
docker exec a0-telegram-bot python -m bot.cli revoke 123456789
```

---

## 9. Error Handling Strategy

### Error Categories

| Category | Examples | Bot Behavior |
|----------|----------|--------------|
| **A0 Unreachable** | Connection refused, DNS failure | Reply: "⚠️ Agent Zero is not reachable. Is it running?" |
| **A0 Timeout** | Response takes > `timeout_seconds` | Edit processing msg: "⏰ Request timed out. A0 may still be processing." |
| **A0 API Error** | 401 (bad key), 500 (internal) | Reply with error type. Log full details. |
| **A0 Bad Response** | Malformed JSON, missing fields | Reply: "⚠️ Unexpected response from A0." Log raw response. |
| **Telegram API Error** | Rate limit, message too long, chat not found | Retry with backoff for rate limits. Split for length. Log others. |
| **Config Error** | Missing bot_token, invalid JSON | Fail fast on startup with clear error message. |
| **State Corruption** | Invalid JSON in state file | Log warning, reset state to empty, continue. |

### Error Handling Principles

1. **Never crash silently**: All exceptions are caught, logged, and result in a user-facing message when possible.
2. **Never leak internals**: Error messages to users are generic. Full details go to logs only.
3. **Fail fast on startup**: Config validation errors prevent the bot from starting (better than runtime failures).
4. **Graceful degradation**: If state file is corrupted, reset and continue. If A0 is down, tell the user and keep accepting messages.
5. **Retry sparingly**: Only retry on transient network errors (connection reset, DNS timeout). Never retry on 4xx errors.

### Logging

- Use Python's `logging` module
- Log level: `INFO` by default, `DEBUG` available via env var
- Log format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Log destinations: stdout (Docker captures it)
- Key events to log: startup, shutdown, auth events, A0 API calls (request/response summary), errors

### Timeout Handling (Detail)

Since A0's `/api_message` is synchronous and can take minutes:

1. `aiohttp` timeout is set to `config.agent_zero.timeout_seconds` (default 300s)
2. The "⏳ Processing..." message is sent immediately before the API call
3. On timeout: edit the processing message with a timeout notice
4. The user can send another message — it won't interfere (aiogram handles concurrent updates)
5. A0 may still complete the task server-side even after our timeout — this is acceptable; the response is simply lost

---

## 10. Security Considerations

### Threat Model

This is a private bot for 1-3 trusted users. The primary threats are:

1. **Unauthorized access**: Random Telegram users discovering the bot and sending commands to A0
2. **Secret exposure**: Bot token or A0 API key leaking
3. **A0 abuse**: An approved user sending malicious prompts (out of scope — A0's own sandboxing handles this)

### Mitigations

| Threat | Mitigation |
|--------|------------|
| Unauthorized access | Auth middleware blocks all unapproved users before any handler runs |
| Brute-force code guessing | 6 hex chars = 16.7M combinations. 10-min expiry. Rate limit: 1 code/min/user. |
| Bot token exposure | Stored in bind-mounted config.json, not in image. `.gitignore` the file. |
| API key exposure | Same as bot token — config.json only. |
| Network sniffing (bot↔A0) | Internal Docker network only. No traffic leaves the host. |
| Network sniffing (bot↔Telegram) | HTTPS enforced by Telegram's API. |
| State file tampering | File is inside a Docker volume. Only the bot and CLI write to it. |
| CLI access | Requires `docker exec` = requires SSH/root access to the host. |

### Secrets Management

- `bot_token` and `api_key` live in `config.json`
- `config.json` is bind-mounted (not baked into the image)
- Add `config.json` to `.gitignore` and `.dockerignore`
- Provide a `config.example.json` with placeholder values for documentation

### What This Architecture Does NOT Handle

- **End-to-end encryption**: Telegram messages are encrypted in transit but Telegram servers can read them. This is inherent to the Telegram Bot API.
- **Prompt injection via Telegram**: If an approved user sends a malicious prompt, A0 processes it. This is by design — the user is trusted.
- **Multi-tenancy isolation**: All approved users share the same A0 instance. User A could theoretically access User B's chat if they know the context_id. For the MVP (1-3 trusted users), this is acceptable.

---

## Appendix: A0 API Endpoints Used

| Endpoint | Method | Auth | Request Body | Response | Used For |
|----------|--------|------|-------------|----------|----------|
| `/api_message` | POST | `X-API-KEY` | `{context_id?, message, project_name?, attachments?, lifetime_hours?}` | `{context_id, response}` | Send messages, create chats |
| `/api_reset_chat` | POST | `X-API-KEY` | `{context_id}` | `{ok: true}` | `/reset` command |
| `/api_terminate_chat` | POST | `X-API-KEY` | `{context_id}` | `{ok: true}` | `/delete` command |
