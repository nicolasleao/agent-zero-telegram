# Implementation Tasks — Agent Zero Telegram Bot

> **Version**: 2.0 — Simplified Static Config Architecture  
> **Date**: 2026-02-07  
> **Status**: Phase 1-3 Complete, Phase 4-5 Pending Update

---

## Task Legend

| Status | Meaning |
|--------|---------|
| ✅ | Complete |
| 🔄 | In Progress |
| ⏳ | Pending |
| ❌ | Blocked/Issue |

---

## Phase 1: Foundation — ✅ COMPLETE

| ID | Task | Status | Files | Notes |
|----|------|--------|-------|-------|
| T-01 | Create project scaffold | ✅ | `bot/`, `routers/`, `middleware/`, `data/` | Standard aiogram structure |
| T-02 | Implement Pydantic configuration | ✅ | `bot/config.py`, `config.example.json` | Atomic save with exclude for computed fields |
| T-03 | Implement state manager | ✅ | `bot/state.py` | Pending verifications, atomic writes |
| T-04 | Implement bot skeleton | ✅ | `bot/main.py`, `bot/__main__.py` | Lifecycle, dependency injection, graceful shutdown |

**Phase 1 QA**: ✅ PASSED (after fixing config serialization issue)

---

## Phase 2: Authentication — ✅ COMPLETE

| ID | Task | Status | Files | Notes |
|----|------|--------|-------|-------|
| T-05 | Design verification flow | ✅ | — | 6-char hex, 10-min expiry, rate limit 1/60s |
| T-06 | Implement auth middleware | ✅ | `bot/middleware/auth.py` | Outer middleware, hot reload from config.json |
| T-07 | Implement CLI approval tool | ✅ | `bot/cli.py` | approve, pending, users, revoke commands |
| T-08 | Wire auth into bot lifecycle | ✅ | `bot/main.py` | Router includes middleware |

**Phase 2 QA**: ✅ PASSED

---

## Phase 3: Core Messaging — ✅ COMPLETE

| ID | Task | Status | Files | Notes |
|----|------|--------|-------|-------|
| T-09 | Implement A0 HTTP client | ✅ | `bot/a0_client.py` | Lazy session, custom exceptions, timeout handling |
| T-10 | Wire A0 client into bot | ✅ | `bot/main.py` | Add to workflow_data, proper cleanup |
| T-11 | Implement message relay | ✅ | `bot/routers/messages.py` | Processing indicator, error handling, response relay |
| T-12 | Implement response formatter | ✅ | `bot/formatters.py` | Markdown→HTML, 4096 split, tag balancing |
| T-13 | Integration test messaging | ✅ | — | 15 regression tests, inline code fix applied |

**Phase 3 QA**: ✅ PASSED (after fixing inline code protection critical bug)

---

## Phase 4: Static Configuration (Previously Chat/Project Management) — ⏳ PENDING

> **SIMPLIFICATION**: Instead of dynamic /new, /chats, /projects commands, we use static config.  
> One bot instance = one A0 project = one A0 context. Need another project? Spin up another bot.

| ID | Task | Status | Files | Spec Ref | Notes |
|----|------|--------|-------|----------|-------|
| **T-14** | **Add fixed_project_name to config** | ⏳ | `bot/config.py`, `config.example.json` | FR-30, FR-60 | Add `fixed_project_name: str | None = None` to AgentZeroConfig |
| **T-15** | **Add fixed_context_id to config** | ⏳ | `bot/config.py`, `config.example.json` | FR-31, FR-60 | Add `fixed_context_id: str | None = None` to AgentZeroConfig |
| **T-16** | **Update state.json for auto-created context** | ⏳ | `bot/state.py` | FR-32, FR-54 | Add `auto_context_id: str | None` field to persist auto-created contexts |
| **T-17** | **Update message router for static config** | ⏳ | `bot/routers/messages.py` | FR-10, FR-11, FR-30, FR-31 | Modify `_relay_to_a0()` to: 1) Use `fixed_project_name` from config, 2) Use `fixed_context_id` if set, otherwise use `auto_context_id` from state, 3) Auto-create and persist context if neither exists |
| **T-18** | **Simplify /start command** | ⏳ | `bot/routers/commands.py` | FR-40, US-40 | Update welcome message to show configured project name (or "Default") |
| **T-19** | **Update /help command** | ⏳ | `bot/routers/commands.py` | FR-41 | Simplify to show only: /start, /help, /status |
| **T-20** | **Implement /status command** | ⏳ | `bot/routers/commands.py` | FR-42, FR-33, FR-34 | Show: fixed_project_name, current context ID (truncated), connection status, user ID |

**Phase 4 Acceptance Criteria**:
- ✅ Config loads `fixed_project_name` and `fixed_context_id` (both optional)
- ✅ If `fixed_context_id` set, all messages use this context
- ✅ If not set, bot auto-creates context on first message and persists it
- ✅ All approved users share the same context
- ✅ `/status` shows the effective project and context
- ✅ `/help` shows simplified command list
- ✅ `/start` mentions the configured project name

---

## Phase 5: Deployment — ⏳ PENDING

| ID | Task | Status | Files | Spec Ref | Notes |
|----|------|--------|-------|----------|-------|
| T-21 | Create Dockerfile | ⏳ | `Dockerfile` | US-50, NFR-10 | Multi-stage, minimal image, no root |
| T-22 | Create docker-compose.yml | ⏳ | `docker-compose.yml` | US-50 | Service definition, volume mounts for config.json and state |
| T-23 | Create README.md | ⏳ | `README.md` | — | Setup instructions, config reference, CLI usage |

---

## Task Dependency Graph

```
Phase 1 (Foundation)
    ├── T-01 ──┐
    ├── T-02 ──┼──→ T-05 (Phase 2 starts)
    ├── T-03 ──┤
    └── T-04 ──┘

Phase 2 (Auth)
    ├── T-05 ──┐
    ├── T-06 ──┼──→ T-09 (Phase 3 starts)
    ├── T-07 ──┤
    └── T-08 ──┘

Phase 3 (Core Messaging)
    ├── T-09 ──┐
    ├── T-10 ──┤
    ├── T-11 ──┼──→ T-14 (Phase 4 starts)
    ├── T-12 ──┤
    └── T-13 ──┘

Phase 4 (Static Config)
    ├── T-14 ──┐
    ├── T-15 ──┤
    ├── T-16 ──┼──→ All affect T-17
    ├── T-17 ──┤
    ├── T-18 ──┤
    ├── T-19 ──┤
    └── T-20 ──┘──→ T-21 (Phase 5 starts)

Phase 5 (Deployment)
    ├── T-21 ──┐
    ├── T-22 ──┤
    └── T-23 ──┘
```

---

## Definition of Done (Per Phase)

**Phase 4 Complete When:**
1. All 7 tasks (T-14 through T-20) implemented
2. QA specialist review passed
3. All acceptance criteria from spec.md met
4. No regression in Phases 1-3
5. Documentation updated (README mentions static config approach)

**Phase 5 Complete When:**
1. All 3 tasks (T-21 through T-23) implemented
2. Docker image builds successfully
3. docker-compose up -d starts the bot
4. Bot survives restart with state intact
5. README is clear enough for a non-Python developer to deploy

---

## Post-Implementation Review Notes

### What Was Removed from Original Phase 4

| Original Task | Status | Rationale |
|---------------|--------|-----------|
| T-14: /new command | ❌ REMOVED | Not needed — project fixed in config |
| T-15: /chats command | ❌ REMOVED | Single shared context, no switching |
| T-16: /projects command | ❌ REMOVED | Not applicable with static project |
| T-17: /reset command | ❌ REMOVED | Use A0's own /reset command via messaging |
| T-18: /delete command | ❌ REMOVED | Not applicable with single context |
| T-19: /exit command | ❌ REMOVED | Not applicable — always in one context |
| T-20: Context persistence | ⏳ MODIFIED | Now T-16 — only for auto-created context_id |

### What Replaces the Removed Features

| Old Feature | New Approach | Config Field |
|-------------|--------------|--------------|
| /new chat | Bot auto-creates context on first message | `fixed_context_id` (optional) |
| /chats | Not applicable — single context | N/A |
| /projects | Not applicable — single project | `fixed_project_name` (optional) |
| /reset | User types "reset" in chat, A0 handles | N/A |
| /delete | Not applicable | N/A |
| /exit | Not applicable | N/A |

---

## QA Checklist for Phase 4

- [ ] Config validation: `fixed_project_name` accepts string or null
- [ ] Config validation: `fixed_context_id` accepts string or null
- [ ] Message routing: Uses `fixed_project_name` from config
- [ ] Message routing: Uses `fixed_context_id` from config if set
- [ ] Auto-context: Creates new context when `fixed_context_id` not set and no `auto_context_id` in state
- [ ] Persistence: Auto-created `context_id` saved to `state.json`
- [ ] Recovery: On restart, loads `auto_context_id` from state and continues using it
- [ ] /status: Shows correct project name (from config)
- [ ] /status: Shows correct context ID (from config or state)
- [ ] /help: Lists only /start, /help, /status
- [ ] /start: Mentions the configured project name
- [ ] No regression: Phases 1-3 functionality intact
