# Technical Architecture — Agent Zero Telegram Bot

> **Version**: 2.0 — Simplified Static Config Architecture  
> **Date**: 2026-02-07  
> **Status**: Updated for Static Configuration Model

This document describes the internal architecture of the Agent Zero Telegram Bot. It covers components, data flow, API interactions, and design patterns.

---

## 1. High-Level Architecture

### 1.1 Design Philosophy

This bot follows a **minimal state, maximum simplicity** philosophy:

- **One bot = one project = one context**: No dynamic switching, no per-user state complexity
- **Static configuration**: Project and context are set in `config.json` at deployment time
- **Shared context**: All approved users collaborate in the same A0 conversation
- **Stateless where possible**: Only runtime state (pending verifications) and auto-created context_id are persisted

### 1.2 System Context

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Docker Network: a0-network                       │
│                                                                          │
│  ┌─────────────────────┐         HTTP REST         ┌──────────────────┐  │
│  │   Telegram Bot      │  ═══════════════════════► │   Agent Zero     │  │
│  │   (this service)    │    POST /api_message      │   (existing)     │  │
│  │                     │    POST /api_reset_chat   │                  │  │
│  │                     │    POST /api_terminate_chat │                  │  │
│  └─────────────────────┘                           └──────────────────┘  │
│           │                                                              │
│           │ Long Polling (outbound only)                                 │
│           ▼                                                              │
│  ┌─────────────────────┐                                                 │
│  │   Telegram API      │                                                 │
│  │   (external)        │                                                 │
│  └─────────────────────┘                                                 │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Component Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Telegram Bot Container                        │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  │
│  │    Config    │  │     State    │  │   Telegram   │  │   A0     │  │
│  │   Manager    │  │   Manager    │  │    Client    │  │  Client  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └────┬─────┘  │
│         │                 │                 │               │        │
│         └────────────────┴─────────────────┴───────────────┘        │
│                            │                                        │
│                            ▼                                        │
│                  ┌──────────────────┐                              │
│                  │  Bot Application   │                              │
│                  │    (aiogram)     │                              │
│                  └────────┬─────────┘                              │
│                           │                                         │
│           ┌───────────────┼───────────────┐                        │
│           ▼               ▼               ▼                        │
│  ┌────────────────┐ ┌────────────┐ ┌──────────────┐              │
│  │ Auth Middleware│ │  Commands  │ │   Messages   │              │
│  │   (outer)      │ │  Router    │ │   Router     │              │
│  └────────────────┘ └────────────┘ └──────────────┘              │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │  CLI Tool (admin approval, separate entry point)           │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Components

### 2.1 Configuration (`bot/config.py`)

**Purpose**: Type-safe configuration management using Pydantic.

**Key Classes**:

```python
class TelegramConfig(BaseModel):
    bot_token: str
    approved_users: list[int] = Field(default_factory=list)
    parse_mode: str = "HTML"

class AgentZeroConfig(BaseModel):
    host: str = "http://agent-zero"
    port: int = 80
    api_key: str
    timeout_seconds: int = 300
    # SIMPLIFIED: Static configuration fields
    fixed_project_name: str | None = None  # All messages go to this project
    fixed_context_id: str | None = None    # If set, use this context; else auto-create

class BotConfig(BaseModel):
    telegram: TelegramConfig
    agent_zero: AgentZeroConfig
    state_file: str = "/data/state.json"
```

**Behavior**:
- Config is loaded once at startup and validated
- `approved_users` is re-read from disk on every auth check (hot reload)
- Atomic writes when CLI tool modifies config
- Excludes computed fields (like `base_url`) from serialization

### 2.2 State Management (`bot/state.py`)

**Purpose**: Persist runtime state that doesn't belong in config.

**Key Class**:

```python
class BotState(BaseModel):
    # Pending verifications (expiring codes waiting for admin approval)
    pending_verifications: dict[str, PendingVerification] = Field(default_factory=dict)
    # Auto-created context (persisted across restarts)
    auto_context_id: str | None = None  # Set when fixed_context_id not configured
    # Version for migrations
    version: int = 1
```

**Design Notes**:
- **No per-user contexts**: All users share one `auto_context_id`
- **No per-user chat registry**: Not needed with static configuration
- Atomic writes using temp file + `os.replace()`
- Lazy cleanup of expired verifications on access

### 2.3 Authentication Middleware (`bot/middleware/auth.py`)

**Purpose**: Gate all message handlers behind approval check.

**Flow**:

```
Incoming Update
      │
      ▼
┌─────────────┐
│  Outer      │  <-- Middleware runs BEFORE router dispatch
│ Middleware  │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ Known user?     │
│ (in approved)   │
└──────┬──────────┘
       │
   ┌───┴───┐
   │       │
  Yes     No
   │       │
   ▼       ▼
┌──────┐ ┌──────────────────┐
│ Pass │ │ Send code + drop │
│ thru │ │ (no handler)     │
└──────┘ └──────────────────┘
```

**Key Features**:
- Outer middleware (runs on raw updates before routing)
- Hot reload: re-reads `approved_users` from config.json on every check
- Rate limiting: 1 code per user per 60 seconds
- Silent drop: unapproved users get one code message, then silence

### 2.4 A0 HTTP Client (`bot/a0_client.py`)

**Purpose**: Async HTTP client for Agent Zero API.

**Key Methods**:

```python
async def send_message(
    self,
    content: str,
    context_id: str | None,      # Uses auto_context_id or fixed_context_id
    project_name: str | None,    # Uses fixed_project_name from config
) -> str:
    """Send message to A0, return context_id (new or existing)."""

async def reset_chat(self, context_id: str) -> None:
    """Reset the specified A0 context."""

async def terminate_chat(self, context_id: str) -> None:
    """Terminate the specified A0 context."""
```

**Error Handling**:
- Custom exception hierarchy: `A0Error` → `A0ConnectionError`, `A0TimeoutError`, `A0APIError`
- Maps `asyncio.TimeoutError` → `A0TimeoutError`
- Maps `aiohttp.ClientError` → `A0ConnectionError`
- Non-2xx status codes → `A0APIError`

### 2.5 Message Router (`bot/routers/messages.py`)

**Purpose**: Handle incoming text messages from approved users.

**Simplified Flow** (static config):

```
User Message
    │
    ▼
┌─────────────────┐
│ Send "⏳"       │
│ indicator       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Determine       │
│ context_id:     │
│ 1. fixed_context_id from config? Use it
│ 2. auto_context_id from state? Use it
│ 3. Else: send None (A0 creates new)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ POST /api_message
│ with:           │
│ - content       │
│ - context_id    │
│ - project_name  │ (from fixed_project_name)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ If new context  │
│ returned: save  │
│ to state.json   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Format & send   │
│ response        │
└─────────────────┘
```

### 2.6 Commands Router (`bot/routers/commands.py`)

**Purpose**: Handle Telegram bot commands.

**Simplified Command Set**:

| Command | Purpose | Who Can Use |
|---------|---------|-------------|
| `/start` | Welcome message + project info | Approved only |
| `/help` | List available commands | Approved only |
| `/status` | Show config: project, context, connection | Approved only |

**Removed Commands** (from original design):
- `/new` — not needed, context auto-created or fixed in config
- `/chats` — not applicable with single shared context
- `/projects` — not applicable with fixed project
- `/reset` — user can type "reset" in chat, A0 handles it
- `/delete` — not applicable with single context
- `/exit` — not applicable

### 2.7 Response Formatter (`bot/formatters.py`)

**Purpose**: Convert A0's markdown to Telegram HTML.

**Pipeline**:

1. **Extract** fenced code blocks → placeholders
2. **Extract** tables → placeholders (degraded to plain text)
3. **Extract** inline code `` `code` `` → placeholders
4. **Escape** remaining HTML special characters
5. **Convert** Markdown → HTML:
   - `# Header` → `<b>Header</b>`
   - `**bold**` → `<b>bold</b>`
   - `*italic*` / `_italic_` → `<i>italic</i>`
   - `[text](url)` → `<a href="url">text</a>`
   - `> quote` → `<blockquote>quote</blockquote>`
6. **Restore** placeholders with `<pre><code>` or `<code>` wrapping
7. **Split** at 4096 characters, respecting block boundaries

### 2.8 CLI Tool (`bot/cli.py`)

**Purpose**: Admin commands for user management.

**Entry Point**: `python -m bot.cli <command>`

**Commands**:

| Command | Description |
|---------|-------------|
| `approve <CODE>` | Approve pending user by verification code |
| `pending` | List all pending verifications |
| `users` | List all approved user IDs |
| `revoke <USER_ID>` | Remove user from approved list |

**Implementation Notes**:
- Runs standalone (no aiogram event loop)
- Creates temporary `Bot` instance to send approval notification
- Modifies `config.json` directly (atomic write)
- Changes take effect immediately (no bot restart needed)

---

## 3. Data Flow

### 3.1 First-Time User Authentication

```
User sends any message
         │
         ▼
┌─────────────────┐
│ Auth Middleware │
│ - Not in        │
│   approved_users│
│ - Generate code │
│ - Store in state│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Send code via   │
│ Telegram        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│ User sees:      │────►│ Admin runs:     │
│ "Your code:     │     │ python -m bot.cli│
│  AB12CD"        │     │ approve AB12CD   │
└─────────────────┘     └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Add user_id to  │
                         │ config.json     │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Notify user:    │
                         │ "✅ Approved!"  │
                         └─────────────────┘
```

### 3.2 Message Relay (Static Config Model)

```
Approved user sends message
            │
            ▼
┌─────────────────────┐
│ 1. Send "⏳"        │
│    to Telegram      │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 2. Determine params │
│    from config:     │
│    - project_name = │
│      fixed_project_name
│    - context_id =   │
│      fixed_context_id│
│      OR auto_context_id
│      from state     │
│      OR None (auto) │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 3. POST /api_message │
│    to A0 instance   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 4. If new context   │
│    created: save    │
│    context_id to    │
│    state.json       │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 5. Format response  │
│    (Markdown→HTML)  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 6. Edit "⏳" with   │
│    first chunk +    │
│    send rest        │
└─────────────────────┘
```

---

## 4. API Interactions

### 4.1 Agent Zero Endpoints Used

| Endpoint | Method | Purpose | Payload |
|----------|--------|---------|---------|
| `/api_message` | POST | Send user message to A0 | `{content, context_id?, project_name?}` |
| `/api_reset_chat` | POST | Reset A0 context | `{context_id}` |
| `/api_terminate_chat` | POST | Terminate A0 context | `{context_id}` |

**Note**: `/projects` endpoint exists but requires web authentication (CSRF/cookies), so this bot does NOT use it. Project is configured statically in `config.json` instead.

### 4.2 Context Management (Static Model)

**Configuration Options**:

| Scenario | `fixed_project_name` | `fixed_context_id` | Behavior |
|----------|----------------------|-------------------|----------|
| A | Not set | Not set | Use A0 default project, auto-create context, persist to state |
| B | Set | Not set | Use specified project, auto-create context, persist to state |
| C | Set | Set | Use specified project and context always (no auto-create) |
| D | Not set | Set | Use A0 default project, use specified context |

**Auto-Create Flow**:

```
First message with context_id=None
            │
            ▼
┌─────────────────────┐
│ A0 creates new      │
│ context internally    │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Response includes   │
│ context_id          │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Bot saves to        │
│ state.json          │
│ as auto_context_id  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Subsequent messages │
│ use this context_id │
└─────────────────────┘
```

---

## 5. Configuration Schema

### 5.1 config.json Structure

```json
{
    "telegram": {
        "bot_token": "123456:ABC-DEF...",
        "approved_users": [123456789, 987654321],
        "parse_mode": "HTML"
    },
    "agent_zero": {
        "host": "http://agent-zero",
        "port": 80,
        "api_key": "your-api-key-here",
        "timeout_seconds": 300,
        "fixed_project_name": "my-project",
        "fixed_context_id": null
    },
    "state_file": "/data/state.json"
}
```

### 5.2 state.json Structure

```json
{
    "pending_verifications": {
        "AB12CD": {
            "sender_id": 123456789,
            "code": "AB12CD",
            "created_at": "2026-01-15T10:30:00",
            "expires_at": "2026-01-15T10:40:00"
        }
    },
    "auto_context_id": "uuid-generated-by-a0",
    "version": 1
}
```

---

## 6. Deployment Architecture

### 6.1 Docker Compose Stack

```yaml
version: '3.8'

services:
  agent-zero:
    image: agent0ai/agent-zero:latest
    # ... A0 configuration ...
    networks:
      - a0-network

  telegram-bot:
    build: .
    container_name: a0-telegram-bot
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
    volumes:
      - ./config.json:/app/config.json:ro
      - ./data:/data
    networks:
      - a0-network
    depends_on:
      - agent-zero

networks:
  a0-network:
    driver: bridge
```

### 6.2 Volume Mounts

| Host Path | Container Path | Purpose | Mode |
|-----------|---------------|---------|------|
| `./config.json` | `/app/config.json` | Bot configuration | Read-only |
| `./data/` | `/data/` | Runtime state (auto_context_id, pending) | Read-write |

### 6.3 Security Model

- **No inbound ports**: Bot uses long polling (outbound HTTPS only)
- **Internal network**: Bot ↔ A0 communication stays on Docker bridge network
- **Read-only config**: `config.json` mounted read-only; CLI tool writes via atomic replace
- **Secrets in config**: `bot_token` and `api_key` never in environment variables or logs

### 6.4 Multi-Project Setup

To run multiple bots for different projects:

```
project-a-bot/
├── config.json      # fixed_project_name: "project-a"
├── docker-compose.yml
└── data/

project-b-bot/
├── config.json      # fixed_project_name: "project-b"
├── docker-compose.yml
└── data/
```

Each bot:
- Has its own Telegram bot token (create via @BotFather)
- Connects to the same or different A0 instance
- Maintains its own approved users list
- Has its own auto-created or fixed context

---

## 7. Error Handling Strategy

### 7.1 A0 API Errors

| Error Type | User Message | Log Level | Recovery |
|------------|-------------|-----------|----------|
| Timeout (>300s) | "⏰ Request timed out..." | WARNING | User retries |
| Connection refused | "⚠️ Agent Zero is not reachable..." | ERROR | Check A0 status |
| HTTP 4xx/5xx | "⚠️ An error occurred..." | ERROR | Check logs |
| Invalid JSON | "⚠️ Unexpected response..." | ERROR | Check A0 logs |

### 7.2 Telegram API Errors

| Error Type | Handler | Action |
|------------|---------|--------|
| HTML parse error | Formatter | Retry as plain text |
| Message too long | Formatter | Split into chunks |
| Bot blocked by user | Auth middleware | Remove from approved (optional) |
| Rate limit | aiogram | Exponential backoff (built-in) |

---

## 8. Testing Strategy

### 8.1 Unit Tests

| Component | Test Coverage |
|-----------|--------------|
| Config | Load, validate, save, atomic write, computed fields |
| State | Add/remove pending, expiry, atomic write, version |
| Formatter | Markdown→HTML, splitting, tag balance, edge cases |
| A0 Client | Mock aiohttp, test exceptions, retry logic |
| Auth Middleware | Mock updates, code generation, expiry, rate limit |

### 8.2 Integration Tests

| Scenario | Setup |
|----------|-------|
| Full auth flow | Send message → get code → CLI approve → send message → get response |
| Auto-context | First message with no context_id → verify state saved → second message uses saved context |
| Fixed context | Set fixed_context_id → verify all messages use it |
| Error handling | Stop A0 container → verify error message |
| Restart recovery | Start bot, approve user, restart container → verify user still approved and context persisted |

### 8.3 Manual QA Checklist

- [ ] First message from new user generates code
- [ ] Second message from same user is silent
- [ ] CLI approve sends success notification
- [ ] Approved user can send messages
- [ ] /status shows correct project and context
- [ ] Long response (>4096 chars) splits correctly
- [ ] Bot restart preserves approved users and context
- [ ] Multiple users share same context (collaborative)

---

## 9. Design Decisions & Trade-offs

### 9.1 Static vs Dynamic Configuration

| Approach | Pros | Cons | Chosen |
|----------|------|------|--------|
| **Static** (this design) | Simple state, no complex UI, easy to reason about, one bot per project is clean | Need multiple bots for multiple projects | ✅ Yes |
| **Dynamic** (original) | Single bot can switch projects/contexts | Complex state management, more commands, harder to test | ❌ No |

**Rationale**: The "one service per responsibility" pattern is clearer for a self-hosted tool. Users who need multiple projects can run multiple lightweight bot containers.

### 9.2 Long Polling vs Webhooks

| Approach | Pros | Cons | Chosen |
|----------|------|------|--------|
| **Long Polling** | No inbound ports, no TLS setup, works behind NAT/firewall | Slightly higher latency (acceptable) | ✅ Yes |
| **Webhooks** | Lower latency, instant delivery | Requires public HTTPS URL, TLS cert, reverse proxy | ❌ No |

### 9.3 Per-User vs Shared Context

| Approach | Pros | Cons | Chosen |
|----------|------|------|--------|
| **Shared** (this design) | Simple state, collaborative conversations, easier to manage | Users see each other's messages to A0 | ✅ Yes |
| **Per-User** | Privacy between users | Complex state management, more memory, harder to debug | ❌ No |

**Rationale**: The bot is designed for small trusted teams (1-3 users). Shared context enables collaboration (e.g., "Alice, what did you ask A0 about the database yesterday?").

### 9.4 Config File vs Environment Variables

| Approach | Pros | Cons | Chosen |
|----------|------|------|--------|
| **Config File** | All settings in one place, easy to edit, supports complex structures | Need to bind-mount file | ✅ Yes |
| **Env Vars** | 12-factor app style, cloud-native | Scattered configuration, harder for users to set up | ❌ No |

---

## 10. Future Considerations

### 10.1 Potential Phase 2 Features

| Feature | Complexity | Notes |
|---------|-----------|-------|
| File attachments | Medium | Need base64 encoding, detect mime types |
| Image responses | Medium | Detect image paths in A0 response, send as photo |
| Voice messages | High | Requires STT integration (Whisper API?) |
| Streaming responses | High | Need to poll A0's `/poll` endpoint (requires web auth) |

### 10.2 Migration Path

If dynamic project switching is needed later:

1. Add `user_contexts: dict[int, UserContext]` to state
2. Add `/new`, `/chats`, `/projects` commands
3. Modify auth middleware to track current context per user
4. Migration: existing `auto_context_id` becomes each approved user's initial context

This is a data model change but the architecture (routers, formatters, client) remains compatible.
