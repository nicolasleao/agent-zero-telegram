# Product Specification — Agent Zero Telegram Bot

> **Version**: 1.0 — Initial Implementation  
> **Date**: 2025-02-07  
> **Status**: Draft  
> **Architecture**: See [architecture.md](./architecture.md) for technical design details

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [User Stories](#2-user-stories)
3. [Functional Requirements](#3-functional-requirements)
4. [Non-Functional Requirements](#4-non-functional-requirements)
5. [Acceptance Criteria](#5-acceptance-criteria)
6. [Out of Scope](#6-out-of-scope)
7. [Open Questions & Decisions](#7-open-questions--decisions)

---

## 1. Product Overview

### What

A standalone Python Telegram bot that acts as a messaging bridge between Telegram and a running Agent Zero (A0) instance. Users send messages and commands via Telegram; the bot relays them to A0's REST API and returns the responses.

### Why

Agent Zero's primary interface is a web UI. A Telegram bot provides:

- **Mobile-first access**: Interact with A0 from anywhere via Telegram (phone, tablet, desktop)
- **Conversational UX**: Natural chat interface without opening a browser
- **Notification-friendly**: Telegram push notifications when A0 finishes processing
- **Low friction**: No URL to remember, no login page — just open the Telegram chat

### Who

- **Primary user**: The A0 instance owner (self-hosted, technical user)
- **Secondary users**: 1–3 additional trusted users the owner approves
- **Admin**: The person with SSH/Docker access to the server running the bot

### How It Works (Summary)

1. Bot runs as a separate Docker container on the same network as Agent Zero
2. Users send messages in Telegram → bot forwards to A0's `/api_message` endpoint
3. A0 processes the request (may take seconds to minutes) → bot returns the response
4. Authentication: first-time users receive a verification code; admin approves via CLI
5. Users can manage multiple A0 chat sessions and switch between projects

---

## 2. User Stories

### Authentication

| ID | Story | Priority |
|----|-------|----------|
| US-01 | As a **new user**, I want to receive a verification code when I first message the bot, so that I can ask the admin to approve me. | Must |
| US-02 | As an **admin**, I want to approve users via a CLI command inside the bot container, so that I maintain server-level control over who can access A0. | Must |
| US-03 | As an **approved user**, I want my approval to persist across bot restarts, so that I don't need to re-verify. | Must |
| US-04 | As an **admin**, I want to revoke a user's access via CLI, so that I can remove users who should no longer have access. | Should |
| US-05 | As an **unapproved user**, I want the bot to silently ignore my messages after the initial code, so that the bot doesn't leak information about its existence. | Must |

### Core Messaging

| ID | Story | Priority |
|----|-------|----------|
| US-10 | As a **user**, I want to send a text message and receive A0's response in the same Telegram chat, so that I can interact with A0 conversationally. | Must |
| US-11 | As a **user**, I want to see a "Processing..." indicator while A0 is working, so that I know my message was received. | Must |
| US-12 | As a **user**, I want long A0 responses to be split into multiple Telegram messages, so that nothing is truncated. | Must |
| US-13 | As a **user**, I want A0's markdown formatting (bold, code, links) to render properly in Telegram, so that responses are readable. | Must |
| US-14 | As a **user**, I want to receive a clear error message if A0 is unreachable or times out, so that I know what happened. | Must |

### Chat Management

| ID | Story | Priority |
|----|-------|----------|
| US-20 | As a **user**, I want to create a new A0 chat session with `/new`, so that I can start a fresh conversation. | Must |
| US-21 | As a **user**, I want to create a new chat with a specific project using `/new <project>`, so that the chat uses that project's context. | Must |
| US-22 | As a **user**, I want to list my chat sessions with `/chats`, so that I can see what conversations I have. | Should |
| US-23 | As a **user**, I want to switch between chat sessions by selecting from a list, so that I can resume previous conversations. | Should |
| US-24 | As a **user**, I want to reset the current chat with `/reset`, so that I can clear the conversation history without creating a new session. | Should |
| US-25 | As a **user**, I want to delete the current chat with `/delete`, so that I can clean up sessions I no longer need. | Should |

### Project Management

| ID | Story | Priority |
|----|-------|----------|
| US-30 | As a **user**, I want to list available A0 projects with `/projects`, so that I can see what projects exist. | Should |
| US-31 | As a **user**, I want to select a project from the list to use with my next `/new` chat, so that I can easily switch project contexts. | Should |

### Information & Help

| ID | Story | Priority |
|----|-------|----------|
| US-40 | As a **user**, I want to see a welcome message with basic instructions when I first use `/start`, so that I know how to use the bot. | Must |
| US-41 | As a **user**, I want to see all available commands with `/help`, so that I can discover the bot's capabilities. | Must |
| US-42 | As a **user**, I want to see my current session info with `/status`, so that I know which chat and project I'm using. | Should |

### Deployment

| ID | Story | Priority |
|----|-------|----------|
| US-50 | As an **admin**, I want to deploy the bot with `docker-compose up -d`, so that setup is simple and reproducible. | Must |
| US-51 | As an **admin**, I want to configure the bot via a single `config.json` file, so that all settings are in one place. | Must |
| US-52 | As an **admin**, I want bot state to persist across container restarts, so that approved users and active chats survive reboots. | Must |

---

## 3. Functional Requirements

### 3.1 Authentication & Authorization

| ID | Requirement | Details |
|----|-------------|---------|
| FR-01 | **Verification code generation** | When an unknown `sender_id` sends any message, generate a 6-character hex code using `secrets.token_hex(3)`. Send the code back to the user with instructions. |
| FR-02 | **Code expiry** | Verification codes expire after 10 minutes. Expired codes are cleaned up lazily on next access. |
| FR-03 | **Rate limiting** | Maximum 1 verification code per user per 60 seconds. If a pending code exists and hasn't expired, silently drop the message. |
| FR-04 | **Silent rejection** | After the initial code message, all subsequent messages from unapproved users are silently dropped (no response). |
| FR-05 | **CLI approval** | Admin approves a user by running `python -m bot.cli approve <CODE>` inside the container. This moves the `sender_id` to `config.json`'s `approved_users` list. |
| FR-06 | **Approval notification** | Upon CLI approval, the bot sends a Telegram message to the user: "✅ You've been approved!" |
| FR-07 | **CLI user management** | CLI supports: `approve <code>`, `pending` (list pending), `users` (list approved), `revoke <user_id>`. |
| FR-08 | **Hot reload of approved users** | The bot re-reads `approved_users` from `config.json` on every incoming message, so CLI changes take effect immediately without restart. |
| FR-09 | **Auth middleware** | Authentication is implemented as an aiogram outer middleware on the `Message` update type, gating all handlers. |

### 3.2 Message Relay

| ID | Requirement | Details |
|----|-------------|---------|
| FR-10 | **Text message forwarding** | Any non-command text message from an approved user is sent to A0 via `POST /api_message` with the user's current `context_id`. |
| FR-11 | **Auto-create context** | If the user has no active `context_id`, send the message with an empty `context_id`. A0 will create a new context and return it. Store the returned `context_id` in state. |
| FR-12 | **Processing indicator** | Immediately send a "⏳ Processing..." message before making the A0 API call. Edit this message with the actual response when A0 replies. |
| FR-13 | **Timeout handling** | If the A0 API call exceeds `timeout_seconds` (default 300s), edit the processing message to: "⏰ Request timed out. Agent Zero may still be processing." |
| FR-14 | **Connection error handling** | If A0 is unreachable, reply with: "⚠️ Agent Zero is not reachable. Is it running?" |
| FR-15 | **API error handling** | If A0 returns a non-2xx status, reply with a generic error message. Log the full error details. |

### 3.3 Response Formatting

| ID | Requirement | Details |
|----|-------------|---------|
| FR-20 | **Markdown to HTML conversion** | Convert A0's markdown response to Telegram HTML: `**bold**` → `<b>`, `` `code` `` → `<code>`, code blocks → `<pre>`, `# headers` → `<b>`, links → `<a href>`. |
| FR-21 | **Unsupported element handling** | Strip or degrade unsupported markdown elements: tables → plain text, LaTeX → raw text, images → link text. |
| FR-22 | **Message splitting** | If the formatted response exceeds 4096 characters, split into multiple messages at natural boundaries (paragraph breaks, between code blocks). |
| FR-23 | **Parse mode** | All bot messages use `parse_mode="HTML"` for consistent formatting. |
| FR-24 | **Fallback on parse error** | If Telegram rejects the HTML (malformed tags), retry sending as plain text with formatting stripped. |

### 3.4 Chat Management Commands

| ID | Requirement | Details |
|----|-------------|---------|
| FR-30 | **`/start` command** | Send a welcome message with bot description and basic usage instructions. If the user has no active context, create one. |
| FR-31 | **`/new [project]` command** | Create a new A0 chat. If `project` argument is provided, pass it as `project_name` to `/api_message`. Update the user's state with the new `context_id`. |
| FR-32 | **`/chats` command** | Display a list of the user's chat sessions (tracked in bot state). Show context ID (truncated), project name, and creation info. Use inline keyboard buttons for switching. |
| FR-33 | **`/reset` command** | Reset the current chat by calling `POST /api_reset_chat` with the user's `context_id`. Confirm to the user. |
| FR-34 | **`/delete` command** | Terminate the current chat by calling `POST /api_terminate_chat`. Clear the `context_id` from user state. Confirm to the user. |
| FR-35 | **`/status` command** | Display: current context ID, active project (if any), user's Telegram ID, and bot connection status. |
| FR-36 | **`/help` command** | Display all available commands with brief descriptions. |

### 3.5 Project Management

| ID | Requirement | Details |
|----|-------------|---------|
| FR-40 | **`/projects` command** | List available A0 projects. For MVP, read from a `projects` list in `config.json` (since A0's `/projects` endpoint requires web auth). |
| FR-41 | **Project selection** | Display projects as inline keyboard buttons. When selected, store the project name in user state for use with the next `/new` command. |
| FR-42 | **Default project** | If `config.agent_zero.default_project` is set, use it automatically for `/new` when no project is specified and no project is selected. |

### 3.6 State Persistence

| ID | Requirement | Details |
|----|-------------|---------|
| FR-50 | **State file** | All runtime state (pending verifications, user sessions) is persisted to a JSON file at `config.state_file`. |
| FR-51 | **Atomic writes** | State is written using atomic file replacement (write to `.tmp`, then `os.replace()`). |
| FR-52 | **Write-on-change** | State is written to disk immediately on every mutation. |
| FR-53 | **Startup recovery** | On startup, load state from file. If the file is missing or corrupted, start with empty state and log a warning. |
| FR-54 | **Chat history tracking** | The bot maintains its own registry of chats it has created per user (context_id, project, created_at). This is the source of truth for `/chats`. |

### 3.7 Configuration

| ID | Requirement | Details |
|----|-------------|---------|
| FR-60 | **Single config file** | All configuration in a single `config.json` file, validated by Pydantic models on startup. |
| FR-61 | **Fail-fast validation** | If `config.json` is missing, malformed, or fails validation (e.g., missing `bot_token`), the bot exits immediately with a clear error message. |
| FR-62 | **Config schema** | See [architecture.md § Configuration Schema](./architecture.md#6-configuration-schema) for the full schema. |
| FR-63 | **Example config** | Provide a `config.example.json` with placeholder values and comments for documentation. |

---

## 4. Non-Functional Requirements

### 4.1 Performance

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-01 | **Bot response latency** (excluding A0 processing) | < 500ms from receiving Telegram update to sending "Processing..." message |
| NFR-02 | **Concurrent message handling** | Bot must handle messages from multiple approved users simultaneously without blocking |
| NFR-03 | **Memory footprint** | < 100MB RSS under normal operation |
| NFR-04 | **Startup time** | < 5 seconds from container start to accepting Telegram updates |

### 4.2 Reliability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-10 | **Crash recovery** | Bot restarts automatically via Docker `restart: unless-stopped` |
| NFR-11 | **State durability** | All approved users and active sessions survive container restarts |
| NFR-12 | **Graceful degradation** | If A0 is down, bot remains responsive and informs users of the issue |
| NFR-13 | **No silent failures** | All errors result in either a user-facing message or a log entry (or both) |

### 4.3 Security

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-20 | **No unauthorized access** | Auth middleware blocks 100% of messages from unapproved users before any handler executes |
| NFR-21 | **Secret protection** | `bot_token` and `api_key` never appear in logs, error messages, or Docker image layers |
| NFR-22 | **No inbound ports** | Bot container exposes zero ports (long polling is outbound-only) |
| NFR-23 | **Internal network only** | Bot-to-A0 communication stays on the Docker internal network |
| NFR-24 | **Crypto-safe codes** | Verification codes use `secrets` module, not `random` |

### 4.4 Maintainability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-30 | **Code simplicity** | ~15 Python files, no unnecessary abstraction layers |
| NFR-31 | **Logging** | Structured logging via Python `logging` module to stdout. Key events: startup, auth, API calls, errors. |
| NFR-32 | **Dependency count** | 3 direct dependencies: `aiogram`, `aiohttp`, `pydantic` |

---

## 5. Acceptance Criteria

### AC-1: Authentication Flow

```
GIVEN an unknown Telegram user sends any message to the bot
WHEN the auth middleware processes the update
THEN the bot generates a 6-char hex code
 AND sends it to the user with approval instructions
 AND stores the pending verification in state
 AND does NOT pass the message to any handler
```

```
GIVEN a pending (unapproved) user sends another message
WHEN the auth middleware processes the update
THEN the message is silently dropped (no response)
```

```
GIVEN an admin runs `python -m bot.cli approve <CODE>` with a valid, non-expired code
WHEN the CLI processes the command
THEN the user's sender_id is added to config.json approved_users
 AND the pending verification is removed from state
 AND the user receives a "✅ You've been approved!" message on Telegram
```

```
GIVEN a verification code is older than 10 minutes
WHEN any auth check occurs
THEN the expired code is removed from pending verifications
```

```
GIVEN an approved user sends a message
WHEN the auth middleware processes the update
THEN the message is passed through to the appropriate handler
```

### AC-2: Message Relay

```
GIVEN an approved user sends a text message
WHEN the message handler processes it
THEN the bot immediately replies with "⏳ Processing..."
 AND sends the message to A0 via POST /api_message
 AND edits the processing message with A0's formatted response
```

```
GIVEN an approved user sends a message with no active context
WHEN the message handler processes it
THEN A0 creates a new context
 AND the bot stores the returned context_id in user state
 AND subsequent messages use this context_id
```

```
GIVEN A0 does not respond within timeout_seconds
WHEN the timeout fires
THEN the processing message is edited to show a timeout notice
```

```
GIVEN A0 is unreachable (connection refused, DNS failure)
WHEN the API call fails
THEN the processing message is edited to show a connection error notice
```

### AC-3: Response Formatting

```
GIVEN A0 returns a response with markdown formatting
WHEN the formatter processes it
THEN **bold** becomes <b>bold</b>
 AND `code` becomes <code>code</code>
 AND code blocks become <pre>code</pre>
 AND # headers become <b>headers</b>
 AND [links](url) become <a href="url">links</a>
```

```
GIVEN A0 returns a response longer than 4096 characters
WHEN the formatter processes it
THEN the response is split into multiple messages
 AND each message is ≤ 4096 characters
 AND splits occur at paragraph boundaries when possible
```

```
GIVEN the formatted HTML is rejected by Telegram's API
WHEN the send fails with a parse error
THEN the bot retries sending as plain text with HTML tags stripped
```

### AC-4: Chat Management

```
GIVEN a user sends /new
WHEN the command handler processes it
THEN a new A0 context is created (via /api_message with empty context_id)
 AND the user's state is updated with the new context_id
 AND the user receives confirmation with the new context info
```

```
GIVEN a user sends /new myproject
WHEN the command handler processes it
THEN a new A0 context is created with project_name="myproject"
 AND the user's state is updated with the new context_id and project
```

```
GIVEN a user sends /chats
WHEN the command handler processes it
THEN the bot displays a list of the user's tracked chat sessions
 AND each entry shows a truncated context ID and project name
 AND inline keyboard buttons allow switching between chats
```

```
GIVEN a user sends /reset with an active context
WHEN the command handler processes it
THEN the bot calls POST /api_reset_chat with the context_id
 AND confirms the reset to the user
```

```
GIVEN a user sends /delete with an active context
WHEN the command handler processes it
THEN the bot calls POST /api_terminate_chat with the context_id
 AND removes the context from user state
 AND confirms the deletion to the user
```

### AC-5: Project Management

```
GIVEN a user sends /projects
WHEN the command handler processes it
THEN the bot displays a list of available projects from config
 AND inline keyboard buttons allow selecting a project
```

```
GIVEN a user selects a project from the inline keyboard
WHEN the callback is processed
THEN the selected project is stored in user state
 AND the user is informed that the project will be used for the next /new chat
```

### AC-6: Deployment

```
GIVEN a valid config.json and Docker environment
WHEN the admin runs docker-compose up -d
THEN the bot container starts, connects to Telegram, and begins polling
 AND the bot can reach A0 on the Docker network
```

```
GIVEN the bot container is restarted
WHEN it starts up
THEN all approved users remain approved (from config.json)
 AND all active chat sessions are restored (from state.json)
```

```
GIVEN config.json is missing or invalid
WHEN the bot starts
THEN it exits immediately with a clear error message describing what's wrong
```

---

## 6. Out of Scope

The following are explicitly **NOT** included in this initial implementation:

| Feature | Reason | Future Consideration |
|---------|--------|---------------------|
| **File/image attachments** (Telegram → A0) | Adds complexity (base64 encoding, file type handling) | Phase 2 |
| **Image responses** (A0 → Telegram) | Requires detecting image paths in A0 responses | Phase 2 |
| **Voice message support** | Requires speech-to-text integration | Phase 2 |
| **Streaming/progressive responses** | A0's `/api_message` is synchronous; would need polling `/poll` (web auth) | Phase 2 |
| **Webhook mode** | Requires HTTPS, public URL, TLS certificates | Only if polling proves insufficient |
| **Multi-tenancy isolation** | All approved users share the same A0 instance | Only if user base grows |
| **Telegram admin commands** | CLI-only admin for security (no `/approve` command in Telegram) | Intentional design choice |
| **Inline mode** | Not needed for a private bot | Not planned |
| **Group chat support** | Bot is designed for private 1:1 chats only | Not planned |
| **A0 notification forwarding** | Would require websocket/polling integration with A0 | Phase 2 |
| **Dynamic project discovery** | A0's `/projects` endpoint requires web auth; using config list for MVP | PR to add API-key endpoint |
| **Chat naming/renaming** | Nice-to-have UX improvement | Phase 2 |
| **Cancel in-progress request** | A0 API doesn't support cancellation | Depends on A0 API changes |

---

## 7. Open Questions & Decisions

### Resolved Decisions

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| D-01 | How to list projects without web auth? | Read from `config.json` projects list | Simplest for MVP; no A0 changes needed |
| D-02 | How to list chats without `/poll` endpoint? | Bot maintains its own chat registry in state | Self-contained; no A0 dependency |
| D-03 | How to create new chats? | Send to `/api_message` with empty `context_id` | Avoids `/chat_create` which needs web auth |
| D-04 | Long polling vs webhooks? | Long polling | No inbound ports, simpler Docker setup |
| D-05 | Single config file vs env vars? | `config.json` (bind-mounted) | Easier to manage all settings in one place |
| D-06 | How does admin approve users? | CLI via `docker exec` | Server-level security; can't be spoofed via Telegram |

### Open Questions

| # | Question | Impact | Proposed Resolution |
|---|----------|--------|--------------------|
| Q-01 | What initial message should `/new` send to A0 to create a context? | UX — A0 will respond to this message | Send a minimal message like `"."` or `"New chat started."` — needs testing to see what A0 does with it |
| Q-02 | Should `/chats` show ALL chats ever created, or only recent/active ones? | UX — list could grow long | Show last 10 chats, sorted by most recent. Add pagination if needed later. |
| Q-03 | How should the bot handle A0 responses that contain only tool outputs / no text? | UX — some A0 responses may be empty or technical | Show the response as-is; if empty, show "✅ Task completed (no text response)." |
| Q-04 | Should the bot support environment variables as config overrides? | DX — useful for Docker secrets | Nice-to-have; implement if time allows. Env vars override config.json values. |
| Q-05 | What happens when a user's context_id becomes invalid (A0 cleaned it up)? | Reliability — A0 has `lifetime_hours` auto-cleanup | A0 will likely return an error. Bot should catch this, clear the stale context, and auto-create a new one. |
