# Product Specification — Agent Zero Telegram Bot

> **Version**: 2.0 — Simplified Static Config Architecture  
> **Date**: 2026-02-07  
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
7. [Design Decisions](#7-design-decisions)

---

## 1. Product Overview

### What

A standalone Python Telegram bot that acts as a messaging bridge between Telegram and a running Agent Zero (A0) instance. One bot instance serves exactly one A0 project and chat context, configured statically via `config.json`.

### Why

Agent Zero's primary interface is a web UI. A Telegram bot provides:

- **Mobile-first access**: Interact with A0 from anywhere via Telegram (phone, tablet, desktop)
- **Conversational UX**: Natural chat interface without opening a browser
- **Notification-friendly**: Telegram push notifications when A0 finishes processing
- **Low friction**: No URL to remember, no login page — just open the Telegram chat
- **Simplicity**: One bot = one project = one chat. Need another project? Spin up another bot instance.

### Who

- **Primary user**: The A0 instance owner (self-hosted, technical user)
- **Secondary users**: 1–3 additional trusted users the owner approves
- **Admin**: The person with SSH/Docker access to the server running the bot

### How It Works (Summary)

1. Bot runs as a separate Docker container on the same network as Agent Zero
2. Admin configures `project_name` and optionally `context_id` in `config.json` before starting
3. All approved users share the same A0 project and chat context
4. Users send messages in Telegram → bot forwards to A0's `/api_message` endpoint
5. A0 processes the request (may take seconds to minutes) → bot returns the response
6. Authentication: first-time users receive a verification code; admin approves via CLI

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

### Information & Help

| ID | Story | Priority |
|----|-------|----------|
| US-40 | As a **user**, I want to see a welcome message with basic instructions when I first use `/start`, so that I know how to use the bot. | Must |
| US-41 | As a **user**, I want to see all available commands with `/help`, so that I can discover the bot's capabilities. | Must |
| US-42 | As a **user**, I want to see my current session info with `/status`, so that I know which project the bot is connected to. | Should |

### Deployment

| ID | Story | Priority |
|----|-------|----------|
| US-50 | As an **admin**, I want to deploy the bot with `docker-compose up -d`, so that setup is simple and reproducible. | Must |
| US-51 | As an **admin**, I want to configure the bot via a single `config.json` file, so that all settings are in one place. | Must |
| US-52 | As an **admin**, I want bot state to persist across container restarts, so that approved users survive reboots. | Must |
| US-53 | As an **admin**, I want to set the project and chat context in config.json, so that the bot always connects to the right A0 project. | Must |

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
| FR-10 | **Text message forwarding** | Any non-command text message from an approved user is sent to A0 via `POST /api_message` with the configured `context_id` and `project_name`. |
| FR-11 | **Auto-create context** | If `fixed_context_id` is not set in config, send the first message with an empty `context_id`. A0 will create a new context and return it. The bot stores the returned `context_id` in the state file for persistence. |
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

### 3.4 Static Configuration

| ID | Requirement | Details |
|----|-------------|---------|
| FR-30 | **Fixed project name** | Admin sets `agent_zero.fixed_project_name` in `config.json`. All messages are sent to this project. If not set, messages use no project (A0 default). |
| FR-31 | **Fixed context ID** | Admin may optionally set `agent_zero.fixed_context_id` in `config.json`. If set, all messages use this context. If not set, bot auto-creates and persists the context ID in state file. |
| FR-32 | **Context persistence** | When auto-creating a context, the bot stores the returned `context_id` in the state file and uses it for all subsequent messages. |
| FR-33 | **Project display** | `/status` command shows the configured `fixed_project_name` (or "Default" if not set). |
| FR-34 | **Context display** | `/status` command shows the current `context_id` (truncated for readability). |

### 3.5 Help Commands

| ID | Requirement | Details |
|----|-------------|---------|
| FR-40 | **`/start` command** | Send a welcome message with bot description, the configured project name, and basic usage instructions. |
| FR-41 | **`/help` command** | Display all available commands: `/start`, `/help`, `/status`. Brief description of each. |
| FR-42 | **`/status` command** | Display: configured project name, current context ID (truncated), bot connection status, and your Telegram user ID. |

### 3.6 State Persistence

| ID | Requirement | Details |
|----|-------------|---------|
| FR-50 | **State file** | Runtime state (pending verifications, auto-created context_id) is persisted to a JSON file at `config.state_file`. |
| FR-51 | **Atomic writes** | State is written using atomic file replacement (write to `.tmp`, then `os.replace()`). |
| FR-52 | **Write-on-change** | State is written to disk immediately on every mutation. |
| FR-53 | **Startup recovery** | On startup, load state from file. If the file is missing or corrupted, start with empty state and log a warning. |
| FR-54 | **No per-user contexts** | All approved users share the same A0 context (as configured in `config.json` or auto-created). |

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
| NFR-11 | **State durability** | Approved users and auto-created context_id survive container restarts |
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
| NFR-30 | **Code simplicity** | ~12 Python files, no unnecessary abstraction layers |
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
  with the configured project_name and context_id
 AND edits the processing message with A0's formatted response
```

```
GIVEN no fixed_context_id is configured
WHEN the first message is sent
THEN A0 creates a new context
 AND the bot stores the returned context_id in the state file
 AND subsequent messages use this persisted context_id
```

```
GIVEN a fixed_context_id is configured
WHEN any message is sent
THEN the bot always uses this context_id for A0 API calls
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

### AC-4: Static Configuration

```
GIVEN agent_zero.fixed_project_name is set to "myproject" in config.json
WHEN any message is sent to A0
THEN the API call includes project_name="myproject"
```

```
GIVEN agent_zero.fixed_context_id is set to "abc-123" in config.json
WHEN any message is sent to A0
THEN the API call uses context_id="abc-123"
```

```
GIVEN neither fixed_project_name nor fixed_context_id are configured
WHEN the first message is sent
THEN A0 creates a new context with default project
 AND the bot persists the returned context_id
```

### AC-5: Help Commands

```
GIVEN a user sends /start
WHEN the command handler processes it
THEN the response includes:
 - A welcome message
 - The configured project name (or "Default")
 - Basic usage instructions
```

```
GIVEN a user sends /status
WHEN the command handler processes it
THEN the response includes:
 - Configured project name
 - Current context ID (truncated)
 - Bot connection status to A0
 - User's Telegram ID
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
 AND the auto-created context_id is restored (from state.json)
```

```
GIVEN config.json is missing or invalid
WHEN the bot starts
THEN it exits immediately with a clear error message describing what's wrong
```

---

## 6. Out of Scope

The following are explicitly **NOT** included in this implementation:

| Feature | Reason | Future Consideration |
|---------|--------|---------------------|
| **File/image attachments** (Telegram → A0) | Adds complexity (base64 encoding, file type handling) | Phase 2 |
| **Image responses** (A0 → Telegram) | Requires detecting image paths in A0 responses | Phase 2 |
| **Voice message support** | Requires speech-to-text integration | Phase 2 |
| **Streaming/progressive responses** | A0's `/api_message` is synchronous; would need polling `/poll` (web auth) | Phase 2 |
| **Webhook mode** | Requires HTTPS, public URL, TLS certificates | Only if polling proves insufficient |
| **Multi-project support** | Intentionally excluded — one bot = one project | Spin up another bot instance |
| **Chat management commands** (/new, /chats, /reset, /delete) | Not needed with static config approach | Not planned |
| **Project switching** | Intentionally excluded — configure in config.json | Edit config.json and restart |
| **Per-user contexts** | All users share the same A0 context | Not planned for this simplicity level |
| **Dynamic project discovery** | A0's `/projects` endpoint requires web auth | Hardcode in config.json |
| **Chat naming/renaming** | Not applicable with single shared context | Not planned |
| **Cancel in-progress request** | A0 API doesn't support cancellation | Depends on A0 API changes |
| **Group chat support** | Bot is designed for private 1:1 chats only | Not planned |
| **Inline mode** | Not needed for a private bot | Not planned |
| **A0 notification forwarding** | Would require websocket/polling integration with A0 | Phase 2 |

---

## 7. Design Decisions

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| D-01 | How to handle multiple projects? | Static config — one bot per project | Simpler architecture; no state complexity; users spin up multiple bot instances if needed |
| D-02 | How to handle chat contexts? | Single shared context for all users | All approved users collaborate in the same A0 conversation |
| D-03 | How to set project and context? | `config.json` fields: `fixed_project_name`, `fixed_context_id` | Explicit configuration; no runtime switching needed |
| D-04 | What if context_id is not set? | Auto-create on first message and persist | Zero-config startup option; bot self-initializes |
| D-05 | Long polling vs webhooks? | Long polling | No inbound ports, simpler Docker setup |
| D-06 | Single config file vs env vars? | `config.json` (bind-mounted) | Easier to manage all settings in one place |
| D-07 | How does admin approve users? | CLI via `docker exec` | Server-level security; can't be spoofed via Telegram |
| D-08 | Do users have separate A0 contexts? | No — all share one context | Simpler state management; collaborative usage model |
