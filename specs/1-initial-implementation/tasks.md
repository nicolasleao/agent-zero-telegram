# Implementation Tasks — Agent Zero Telegram Bot

> **Version**: 1.0 — Initial Implementation  
> **Date**: 2025-02-07  
> **Spec**: See [spec.md](./spec.md) for requirements and acceptance criteria  
> **Architecture**: See [architecture.md](./architecture.md) for technical design

---

## Overview

This document breaks the initial implementation into **5 phases** with **21 tasks**. Each task is scoped to a single focused implementation session.

### Complexity Key

| Size | Meaning | Estimated Time |
|------|---------|----------------|
| **S** | Small — straightforward, minimal decisions | 30–60 min |
| **M** | Medium — some complexity, clear approach | 1–2 hours |
| **L** | Large — significant logic, multiple components | 2–4 hours |

### Phase Summary

| Phase | Name | Tasks | Focus |
|-------|------|-------|-------|
| 1 | Foundation | T-01 → T-04 | Project scaffolding, config, bot skeleton |
| 2 | Authentication | T-05 → T-08 | Verification flow, CLI approval, middleware |
| 3 | Core Messaging | T-09 → T-13 | A0 client, message relay, response formatting |
| 4 | Chat & Project Management | T-14 → T-18 | Commands for managing chats and projects |
| 5 | Deployment & Documentation | T-19 → T-21 | Dockerfile, docker-compose, README |

---

## Phase 1: Foundation

> **Goal**: A running bot skeleton that starts, connects to Telegram, and responds to `/start`.

---

### T-01: Project Scaffolding

**Complexity**: S

**Description**:  
Create the project directory structure, initialize the Python package, and set up dependency management.

**Deliverables**:
- Directory structure matching [architecture.md § Directory Structure](./architecture.md#5-directory-structure)
- `requirements.txt` with pinned dependencies: `aiogram>=3.15`, `aiohttp>=3.9`, `pydantic>=2.0`
- All `__init__.py` files for the `bot`, `bot/routers`, and `bot/middleware` packages
- `bot/__main__.py` stub (allows `python -m bot`)
- `.gitignore` (Python defaults + `config.json`, `/data/`, `*.pyc`, `__pycache__/`)
- `config.example.json` with placeholder values

**Acceptance Criteria**:
- [ ] `pip install -r requirements.txt` succeeds
- [ ] `python -m bot` runs without import errors (can exit immediately if no config)
- [ ] Directory structure matches architecture spec

**Dependencies**: None

---

### T-02: Configuration Management

**Complexity**: M

**Description**:  
Implement the Pydantic-based configuration system that loads, validates, and provides access to `config.json`.

**Deliverables**:
- `bot/config.py` with Pydantic models: `TelegramConfig`, `AgentZeroConfig`, `BotConfig`
- Schema matching [architecture.md § Configuration Schema](./architecture.md#6-configuration-schema)
- `load(path) -> BotConfig` function that reads and validates config.json
- `save(path, config)` function that writes config back (atomic write for CLI use)
- `base_url` computed property on `AgentZeroConfig` that combines `host` and `port`
- Clear error messages on validation failure (missing required fields, wrong types)

**Acceptance Criteria**:
- [ ] Valid `config.json` loads successfully into typed Pydantic models
- [ ] Missing `bot_token` raises a clear validation error
- [ ] Missing `api_key` raises a clear validation error
- [ ] Missing optional fields use defaults (e.g., `timeout_seconds=300`)
- [ ] `save()` uses atomic write (tmp + rename)
- [ ] `base_url` returns correct URL (e.g., `http://agent-zero:80`)

**Dependencies**: T-01

---

### T-03: State Management

**Complexity**: M

**Description**:  
Implement the state manager that tracks pending verifications and per-user session state, with JSON file persistence.

**Deliverables**:
- `bot/state.py` with Pydantic models: `PendingVerification`, `UserState`, `BotState`
- Schema matching [architecture.md § State Management](./architecture.md#7-state-management)
- `StateManager` class with methods:
  - `load(path)` — load state from file (or create empty if missing/corrupt)
  - `save()` — atomic write to disk
  - `add_pending(code, user_id, username)` — add pending verification
  - `get_pending(code)` — retrieve pending verification by code
  - `remove_pending(code)` — remove a pending verification
  - `cleanup_expired(max_age_minutes=10)` — remove expired verifications
  - `get_user(user_id)` — get user state
  - `set_user_context(user_id, context_id, project=None)` — update user's active chat
  - `clear_user_context(user_id)` — clear user's active chat
  - `get_user_chats(user_id)` — list all chats tracked for a user
  - `add_chat(user_id, context_id, project=None)` — add a chat to user's registry
  - `remove_chat(user_id, context_id)` — remove a chat from registry
- Auto-save on every mutation
- Graceful handling of corrupt/missing state file on load

**Acceptance Criteria**:
- [ ] State loads from valid JSON file
- [ ] State initializes empty when file is missing
- [ ] State initializes empty when file is corrupt (with warning log)
- [ ] Every mutation triggers an atomic write to disk
- [ ] Pending verifications can be added, retrieved, and removed by code
- [ ] Expired verifications (>10 min) are cleaned up by `cleanup_expired()`
- [ ] User context can be set, retrieved, and cleared
- [ ] Chat registry tracks multiple chats per user with context_id, project, and created_at

**Dependencies**: T-01

---

### T-04: Bot Skeleton & /start Command

**Complexity**: M

**Description**:  
Wire up the aiogram bot with dispatcher, register the first router, and implement the `/start` command. This is the first end-to-end working version.

**Deliverables**:
- `bot/main.py` — entry point that:
  - Loads config
  - Initializes `Bot` and `Dispatcher`
  - Injects config and state manager into dispatcher's `workflow_data`
  - Includes routers
  - Starts long polling
  - Handles graceful shutdown (close sessions, flush state)
- `bot/routers/commands.py` — with `/start` handler:
  - Sends welcome message with bot description and basic usage
  - Lists available commands
- `bot/routers/messages.py` — stub catch-all handler that echoes "Message received" (placeholder for Phase 3)
- Logging setup: Python `logging` to stdout, `INFO` level default

**Acceptance Criteria**:
- [ ] `python -m bot` starts the bot and connects to Telegram (visible in logs)
- [ ] `/start` in Telegram returns a welcome message with command list
- [ ] Any text message returns a placeholder response
- [ ] Bot shuts down gracefully on SIGTERM/SIGINT
- [ ] Config and state manager are accessible in handlers via dependency injection
- [ ] Startup logs show: config loaded, bot started, polling active

**Dependencies**: T-02, T-03

---

## Phase 2: Authentication

> **Goal**: Only approved users can interact with the bot. New users go through verification. Admin manages users via CLI.

---

### T-05: Auth Middleware — Core Logic

**Complexity**: M

**Description**:  
Implement the aiogram outer middleware that gates all incoming messages based on user approval status.

**Deliverables**:
- `bot/middleware/auth.py` — `AuthMiddleware` class (extends `BaseMiddleware`):
  - Extract `sender_id` from incoming message
  - If `sender_id` in `config.approved_users` → pass through to handler
  - If `sender_id` has a pending (non-expired) verification → silently drop
  - If `sender_id` is unknown → generate code, store pending, send code message, drop
- Re-read `approved_users` from `config.json` on every call (hot reload)
- Code generation: `secrets.token_hex(3)` → 6 hex characters
- Rate limiting: max 1 code per user per 60 seconds
- Lazy cleanup of expired codes on each middleware invocation

**Acceptance Criteria**:
- [ ] Approved users' messages pass through to handlers
- [ ] Unknown users receive a verification code message
- [ ] The verification code is 6 hex characters
- [ ] Pending users' subsequent messages are silently dropped
- [ ] A second message within 60 seconds from an unknown user does NOT generate a new code
- [ ] Codes older than 10 minutes are cleaned up
- [ ] Adding a user_id to `config.json` `approved_users` (manually) immediately grants access on next message

**Dependencies**: T-03, T-04

---

### T-06: CLI Tool — Approve & Pending

**Complexity**: M

**Description**:  
Implement the admin CLI tool for approving users and viewing pending verifications.

**Deliverables**:
- `bot/cli.py` — standalone script using `argparse`:
  - `approve <CODE>` — find pending verification by code, move user_id to `config.approved_users`, remove from pending, print confirmation
  - `pending` — list all pending verifications with user_id, username, code, age
- Reads `config.json` and state file paths from environment or default locations
- Atomic write when modifying `config.json`
- Clear error messages: "Code not found", "Code expired", etc.

**Acceptance Criteria**:
- [ ] `python -m bot.cli approve <CODE>` with valid code adds user to `approved_users` in config.json
- [ ] `python -m bot.cli approve <CODE>` with expired code shows "Code expired" error
- [ ] `python -m bot.cli approve <CODE>` with invalid code shows "Code not found" error
- [ ] `python -m bot.cli pending` lists all pending verifications with details
- [ ] Config.json is updated atomically
- [ ] Running bot picks up the new approved user on next message (no restart needed)

**Dependencies**: T-02, T-03, T-05

---

### T-07: CLI Tool — Users & Revoke

**Complexity**: S

**Description**:  
Extend the CLI tool with user listing and revocation commands.

**Deliverables**:
- Add to `bot/cli.py`:
  - `users` — list all approved user IDs from config.json
  - `revoke <USER_ID>` — remove a user_id from `approved_users` in config.json
- Confirmation prompt for revoke ("Are you sure?")

**Acceptance Criteria**:
- [ ] `python -m bot.cli users` lists all approved user IDs
- [ ] `python -m bot.cli revoke <ID>` removes the user from approved_users
- [ ] Revoked user is blocked on their next message
- [ ] Revoking a non-existent user shows a clear message

**Dependencies**: T-06

---

### T-08: CLI Approval Notification

**Complexity**: S

**Description**:  
When a user is approved via CLI, send them a Telegram notification.

**Deliverables**:
- Extend `approve` command in `bot/cli.py`:
  - After adding user to approved_users, send a Telegram message: "✅ You've been approved! Send any message to start chatting with Agent Zero."
  - Use a one-shot async helper that creates a `Bot` instance, sends the message, and closes
  - Handle failure gracefully (log warning if notification fails, but still complete approval)

**Acceptance Criteria**:
- [ ] Approved user receives a Telegram notification
- [ ] If notification fails (e.g., user blocked the bot), approval still succeeds
- [ ] CLI prints confirmation regardless of notification outcome

**Dependencies**: T-06

---

## Phase 3: Core Messaging

> **Goal**: Users can send messages to A0 and receive formatted responses.

---

### T-09: A0 Client — HTTP Wrapper

**Complexity**: M

**Description**:  
Implement the async HTTP client that wraps all Agent Zero API calls.

**Deliverables**:
- `bot/a0_client.py` — `A0Client` class:
  - `__init__(base_url, api_key, timeout)` — store config, defer session creation
  - `send_message(message, context_id, project_name, attachments)` → `{context_id, response}`
  - `reset_chat(context_id)` → None
  - `terminate_chat(context_id)` → None
  - `close()` — close the aiohttp session
- Lazy session creation (created on first use)
- `X-API-KEY` header set on the session
- Custom exception types: `A0ConnectionError`, `A0TimeoutError`, `A0APIError`
- Proper error mapping: `aiohttp.ClientConnectorError` → `A0ConnectionError`, `asyncio.TimeoutError` → `A0TimeoutError`, non-2xx → `A0APIError`

**Acceptance Criteria**:
- [ ] `send_message()` makes a POST to `/api_message` with correct headers and body
- [ ] `reset_chat()` makes a POST to `/api_reset_chat`
- [ ] `terminate_chat()` makes a POST to `/api_terminate_chat`
- [ ] Connection errors raise `A0ConnectionError`
- [ ] Timeouts raise `A0TimeoutError`
- [ ] Non-2xx responses raise `A0APIError` with status code and body
- [ ] Session is reused across calls
- [ ] `close()` cleanly closes the session

**Dependencies**: T-02

---

### T-10: Wire A0 Client into Bot Lifecycle

**Complexity**: S

**Description**:  
Integrate the A0 client into the bot's startup/shutdown lifecycle and make it available to handlers.

**Deliverables**:
- Update `bot/main.py`:
  - Create `A0Client` instance from config on startup
  - Add to dispatcher's `workflow_data` for handler injection
  - Close the client on shutdown
- Verify handlers can access the client via function parameters

**Acceptance Criteria**:
- [ ] A0Client is created on bot startup
- [ ] A0Client is accessible in command and message handlers
- [ ] A0Client session is closed on bot shutdown
- [ ] No resource leaks on restart

**Dependencies**: T-04, T-09

---

### T-11: Message Relay — Core Flow

**Complexity**: L

**Description**:  
Implement the main message handler that forwards user text to A0 and returns the response.

**Deliverables**:
- Update `bot/routers/messages.py`:
  - Catch all non-command text messages
  - Look up user's current `context_id` from state
  - If no context, send with empty `context_id` (auto-create)
  - Send "⏳ Processing..." message immediately
  - Call `a0_client.send_message()`
  - Store returned `context_id` in state (if new)
  - Edit processing message with A0's response (plain text for now — formatting in T-12)
  - Handle errors:
    - `A0ConnectionError` → "⚠️ Agent Zero is not reachable. Is it running?"
    - `A0TimeoutError` → "⏰ Request timed out. Agent Zero may still be processing."
    - `A0APIError` → "⚠️ Agent Zero returned an error. Please try again."
- Add new chat to user's chat registry when auto-created

**Acceptance Criteria**:
- [ ] Text message is forwarded to A0 with correct context_id
- [ ] "Processing..." message appears immediately
- [ ] A0's response replaces the processing message
- [ ] New context_id is stored in state when auto-created
- [ ] Connection error shows appropriate message
- [ ] Timeout shows appropriate message
- [ ] API error shows appropriate message
- [ ] Multiple users can send messages concurrently without blocking each other

**Dependencies**: T-05, T-10

---

### T-12: Response Formatter — Markdown to Telegram HTML

**Complexity**: L

**Description**:  
Implement the converter that transforms A0's markdown output into Telegram-compatible HTML.

**Deliverables**:
- `bot/formatters.py`:
  - `format_response(markdown_text) -> list[str]` — returns a list of Telegram-safe HTML chunks
  - Conversion rules:
    - `**bold**` / `__bold__` → `<b>bold</b>`
    - `*italic*` / `_italic_` → `<i>italic</i>`
    - `` `inline code` `` → `<code>inline code</code>`
    - Fenced code blocks (``` ```) → `<pre>code</pre>` (with optional language tag: `<pre><code class="language-python">...`)
    - `# Header` → `<b>Header</b>` (all header levels)
    - `[text](url)` → `<a href="url">text</a>`
    - `> blockquote` → `<blockquote>text</blockquote>`
  - Unsupported elements:
    - Tables → preserve as monospace text inside `<pre>`
    - LaTeX → strip delimiters, show raw expression
    - Images `![alt](url)` → `<a href="url">[Image: alt]</a>`
  - HTML entity escaping for `<`, `>`, `&` in non-tag content
  - Message splitting at 4096-char boundaries:
    - Prefer splits at double newlines (paragraph breaks)
    - Never split inside a `<pre>` block if possible
    - If a single block exceeds 4096, split at line boundaries within it

**Acceptance Criteria**:
- [ ] Bold, italic, code, pre, links, blockquotes convert correctly
- [ ] Headers render as bold text
- [ ] Tables render as readable monospace text
- [ ] HTML special characters are escaped in content
- [ ] Messages over 4096 chars are split into multiple chunks
- [ ] Splits prefer paragraph boundaries
- [ ] No chunk exceeds 4096 characters
- [ ] Empty/whitespace-only responses return a fallback message

**Dependencies**: T-01

---

### T-13: Integrate Formatter + Fallback on Parse Error

**Complexity**: M

**Description**:  
Wire the formatter into the message handler and add fallback logic for Telegram parse errors.

**Deliverables**:
- Update `bot/routers/messages.py`:
  - Pass A0 response through `format_response()` before sending
  - Send first chunk by editing the "Processing..." message
  - Send remaining chunks as new messages
  - If Telegram rejects the HTML (parse error), retry with plain text (strip all HTML tags)
  - If response is empty, send "✅ Task completed (no text response)."
- Helper function: `strip_html(text) -> str` for fallback

**Acceptance Criteria**:
- [ ] A0 markdown responses render as formatted HTML in Telegram
- [ ] Long responses are split across multiple messages
- [ ] First chunk replaces the "Processing..." message
- [ ] If HTML is rejected by Telegram, plain text fallback is sent
- [ ] Empty responses show a completion message

**Dependencies**: T-11, T-12

---

## Phase 4: Chat & Project Management

> **Goal**: Users can manage multiple A0 chat sessions and switch projects.

---

### T-14: /new Command

**Complexity**: M

**Description**:  
Implement the `/new` command to create a new A0 chat session, optionally with a project.

**Deliverables**:
- Update `bot/routers/commands.py`:
  - `/new` — create new chat (send minimal message to A0 with empty context_id)
  - `/new <project_name>` — create new chat with `project_name` parameter
  - Store new context_id and project in user state
  - Add to user's chat registry
  - Reply with confirmation: context ID (truncated), project name (if any)
  - Handle errors (A0 unreachable, etc.)
- If user has a selected project (from `/projects`) and no argument given, use the selected project
- If `config.agent_zero.default_project` is set and no project specified, use it

**Acceptance Criteria**:
- [ ] `/new` creates a new A0 chat and updates user state
- [ ] `/new myproject` creates a chat with project_name="myproject"
- [ ] User's subsequent messages go to the new chat
- [ ] New chat appears in user's chat registry
- [ ] Error handling for A0 connection issues
- [ ] Default project is used when configured and no project specified

**Dependencies**: T-10, T-11

---

### T-15: /reset and /delete Commands

**Complexity**: S

**Description**:  
Implement commands to reset and delete the current chat session.

**Deliverables**:
- Update `bot/routers/commands.py`:
  - `/reset` — call `a0_client.reset_chat(context_id)`, confirm to user
  - `/delete` — call `a0_client.terminate_chat(context_id)`, remove from state and registry, confirm to user
  - Both: handle "no active chat" case with a helpful message
  - Both: handle A0 errors gracefully

**Acceptance Criteria**:
- [ ] `/reset` resets the current chat and confirms
- [ ] `/delete` terminates the current chat, clears state, and confirms
- [ ] `/reset` with no active chat shows "No active chat" message
- [ ] `/delete` with no active chat shows "No active chat" message
- [ ] A0 errors are handled gracefully

**Dependencies**: T-10

---

### T-16: /chats Command with Inline Keyboard

**Complexity**: L

**Description**:  
Implement the `/chats` command that lists the user's chat sessions and allows switching via inline keyboard buttons.

**Deliverables**:
- Update `bot/routers/commands.py`:
  - `/chats` — retrieve user's chat registry from state
  - Display as a list with: truncated context_id (first 8 chars), project name, relative time ("2h ago")
  - Mark the currently active chat
  - Inline keyboard buttons for each chat to switch to it
  - Handle empty list: "No chats yet. Send a message or use /new to create one."
- Add callback query handler for chat switching:
  - Update user's active context_id in state
  - Edit the message to reflect the switch
  - Confirm: "Switched to chat `abc12345` (project: myproject)"
- Limit display to last 10 chats (most recent first)

**Acceptance Criteria**:
- [ ] `/chats` shows a list of user's tracked chats
- [ ] Each chat shows truncated ID, project, and age
- [ ] Active chat is visually marked (e.g., ✅ prefix)
- [ ] Tapping a chat button switches the active context
- [ ] Switching is confirmed to the user
- [ ] Empty chat list shows a helpful message
- [ ] List is limited to 10 most recent chats

**Dependencies**: T-03, T-04

---

### T-17: /projects Command with Inline Keyboard

**Complexity**: M

**Description**:  
Implement the `/projects` command that lists available A0 projects and allows selection for the next new chat.

**Deliverables**:
- Add `projects` list to config schema (in `AgentZeroConfig`): `projects: list[str] = []`
- Update `bot/routers/commands.py`:
  - `/projects` — read project list from config
  - Display as inline keyboard buttons
  - Mark currently selected project (if any)
  - Handle empty list: "No projects configured. Add projects to config.json."
- Add callback query handler for project selection:
  - Store selected project in user state
  - Confirm: "Selected project: myproject. Use /new to create a chat with this project."
  - Allow deselection (tap again to deselect)

**Acceptance Criteria**:
- [ ] `/projects` shows available projects from config
- [ ] Each project is an inline keyboard button
- [ ] Tapping a project stores it as the selected project
- [ ] Selected project is used by `/new` when no argument given
- [ ] Currently selected project is visually marked
- [ ] Empty project list shows a helpful message

**Dependencies**: T-02, T-04

---

### T-18: /status and /help Commands

**Complexity**: S

**Description**:  
Implement informational commands.

**Deliverables**:
- Update `bot/routers/commands.py`:
  - `/status` — display:
    - Current context ID (or "No active chat")
    - Active project (or "None")
    - Selected project for next /new (or "None")
    - User's Telegram ID
    - Bot version (hardcoded constant)
  - `/help` — display all commands with descriptions:
    - `/start` — Start the bot
    - `/new [project]` — Create a new chat
    - `/chats` — List and switch chats
    - `/reset` — Reset current chat
    - `/delete` — Delete current chat
    - `/projects` — List and select projects
    - `/status` — Show current session info
    - `/help` — Show this help message
- Register commands with Telegram via `bot.set_my_commands()` on startup

**Acceptance Criteria**:
- [ ] `/status` shows all relevant session information
- [ ] `/help` lists all commands with descriptions
- [ ] Commands appear in Telegram's command menu (via `set_my_commands`)
- [ ] Both commands work for approved users

**Dependencies**: T-04

---

## Phase 5: Deployment & Documentation

> **Goal**: The bot can be deployed with a single `docker-compose up -d` and has clear setup documentation.

---

### T-19: Dockerfile

**Complexity**: S

**Description**:  
Create the production Dockerfile for the bot.

**Deliverables**:
- `Dockerfile` matching [architecture.md § Docker Deployment](./architecture.md#8-docker-deployment):
  - Base: `python:3.12-slim`
  - Copy `requirements.txt`, install deps
  - Copy `bot/` package
  - CMD: `python -m bot`
  - No config.json in image (bind-mounted at runtime)
- `.dockerignore` — exclude `.git`, `__pycache__`, `*.pyc`, `config.json`, `/data/`, `research.md`, `specs/`

**Acceptance Criteria**:
- [ ] `docker build -t a0-telegram-bot .` succeeds
- [ ] Image size is under 200MB
- [ ] `config.json` is NOT in the image
- [ ] Container runs with `docker run` when config is mounted

**Dependencies**: T-01

---

### T-20: Docker Compose & Network Setup

**Complexity**: M

**Description**:  
Create the docker-compose configuration and document the network setup with Agent Zero.

**Deliverables**:
- `docker-compose.yml` matching [architecture.md § Docker Deployment](./architecture.md#8-docker-deployment):
  - Service: `telegram-bot`
  - Build context: `.`
  - Container name: `a0-telegram-bot`
  - Restart policy: `unless-stopped`
  - Volumes: `./config.json:/app/config.json:ro`, `bot-data:/data`
  - Network: `a0-network` (external)
- Instructions for creating the external network if it doesn't exist
- Instructions for connecting the A0 container to the same network
- Verify end-to-end: bot starts, connects to Telegram, can reach A0

**Acceptance Criteria**:
- [ ] `docker-compose up -d` starts the bot successfully
- [ ] Bot can reach A0 at `http://agent-zero:80` (or configured host)
- [ ] State persists across `docker-compose down && docker-compose up -d`
- [ ] `docker exec a0-telegram-bot python -m bot.cli pending` works
- [ ] Container restarts automatically after crash

**Dependencies**: T-19

---

### T-21: README & Setup Documentation

**Complexity**: M

**Description**:  
Write comprehensive setup and usage documentation.

**Deliverables**:
- `README.md` with sections:
  1. **Overview** — What the bot does, architecture diagram (text)
  2. **Prerequisites** — Docker, running A0 instance, Telegram bot token from @BotFather
  3. **Quick Start** — Step-by-step:
     - Create bot with @BotFather
     - Copy `config.example.json` → `config.json`, fill in values
     - Create Docker network (if needed)
     - `docker-compose up -d`
     - Send first message, get verification code
     - `docker exec a0-telegram-bot python -m bot.cli approve <CODE>`
  4. **Configuration** — All config.json fields with descriptions
  5. **Commands** — All bot commands with examples
  6. **Admin CLI** — All CLI commands with examples
  7. **Troubleshooting** — Common issues and solutions:
     - Bot not responding (check token, check polling)
     - Can't reach A0 (check network, check host/port)
     - Verification code expired (send new message)
  8. **Development** — How to run locally without Docker
- Update `config.example.json` with helpful comments (as field descriptions)

**Acceptance Criteria**:
- [ ] A new user can set up the bot by following the README alone
- [ ] All configuration options are documented
- [ ] All commands are documented with examples
- [ ] All CLI commands are documented
- [ ] Troubleshooting covers the most common issues
- [ ] `config.example.json` has clear placeholder values

**Dependencies**: All previous tasks

---

## Dependency Graph

```
Phase 1: Foundation
  T-01 ─────────────────────────────────────────────────────────────────┐
    │                                                                   │
    ├──► T-02 (Config) ──────────────────────────────────┐              │
    │       │                                             │              │
    ├──► T-03 (State) ───────────────────┐               │              │
    │       │                             │               │              │
    └──► T-02 + T-03 ──► T-04 (Skeleton) │               │              │
                           │              │               │              │
Phase 2: Authentication    │              │               │              │
                           ▼              ▼               │              │
                    T-05 (Auth MW) ◄── T-03, T-04         │              │
                           │                              │              │
                           ▼                              │              │
                    T-06 (CLI approve) ◄── T-02, T-03     │              │
                           │                              │              │
                    T-07 (CLI users) ◄── T-06             │              │
                    T-08 (CLI notify) ◄── T-06            │              │
                                                          │              │
Phase 3: Core Messaging                                   │              │
                                                          ▼              │
                    T-09 (A0 Client) ◄── T-02                            │
                           │                                             │
                    T-10 (Wire Client) ◄── T-04, T-09                    │
                           │                                             │
                    T-11 (Msg Relay) ◄── T-05, T-10                      │
                           │                                             │
                    T-12 (Formatter) ◄── T-01 ◄──────────────────────────┘
                           │
                    T-13 (Integrate) ◄── T-11, T-12

Phase 4: Chat & Project Mgmt
                    T-14 (/new) ◄── T-10, T-11
                    T-15 (/reset, /delete) ◄── T-10
                    T-16 (/chats) ◄── T-03, T-04
                    T-17 (/projects) ◄── T-02, T-04
                    T-18 (/status, /help) ◄── T-04

Phase 5: Deployment
                    T-19 (Dockerfile) ◄── T-01
                    T-20 (Compose) ◄── T-19
                    T-21 (README) ◄── All
```

---

## Implementation Order (Recommended)

The following is the suggested linear order for a single developer:

| Order | Task | Phase | Complexity | Cumulative Milestone |
|-------|------|-------|------------|---------------------|
| 1 | T-01 | 1 | S | Project structure exists |
| 2 | T-02 | 1 | M | Config loads and validates |
| 3 | T-03 | 1 | M | State persists to disk |
| 4 | T-04 | 1 | M | **Bot runs and responds to /start** |
| 5 | T-05 | 2 | M | Auth middleware gates all messages |
| 6 | T-06 | 2 | M | Admin can approve users via CLI |
| 7 | T-07 | 2 | S | Admin can list/revoke users |
| 8 | T-08 | 2 | S | **Users get notified on approval** |
| 9 | T-09 | 3 | M | A0 HTTP client ready |
| 10 | T-10 | 3 | S | Client wired into bot |
| 11 | T-11 | 3 | L | **Messages relay to A0 and back** |
| 12 | T-12 | 3 | L | Formatter converts markdown to HTML |
| 13 | T-13 | 3 | M | **Formatted responses in Telegram** |
| 14 | T-14 | 4 | M | /new creates chats with projects |
| 15 | T-15 | 4 | S | /reset and /delete work |
| 16 | T-16 | 4 | L | /chats with inline keyboard switching |
| 17 | T-17 | 4 | M | /projects with inline keyboard |
| 18 | T-18 | 4 | S | **All commands implemented** |
| 19 | T-19 | 5 | S | Docker image builds |
| 20 | T-20 | 5 | M | docker-compose deployment works |
| 21 | T-21 | 5 | M | **Documentation complete — v1.0 ready** |

**Total estimated effort**: ~30–45 hours for a single developer familiar with aiogram and async Python.
