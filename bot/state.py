"""State management for the Agent Zero Telegram Bot.

Tracks pending verifications and per-user session state with
JSON file persistence using atomic writes.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PendingVerification(BaseModel):
    """A pending user verification request."""
    user_id: int
    username: str | None = None
    code: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatInfo(BaseModel):
    """Information about a tracked chat/context."""
    context_id: str
    project: str | None = None


class UserState(BaseModel):
    """Per-user session state."""
    context_id: str | None = None
    project: str | None = None
    chats: list[ChatInfo] = Field(default_factory=list)


class BotState(BaseModel):
    """Top-level bot state persisted to disk."""
    pending_verifications: dict[str, PendingVerification] = Field(default_factory=dict)
    users: dict[int, UserState] = Field(default_factory=dict)


class StateManager:
    """Manages bot state with automatic JSON file persistence.

    Every mutation method auto-saves to disk using atomic writes.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._state = BotState()

    @property
    def state(self) -> BotState:
        """Access the current state (read-only reference)."""
        return self._state

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: str | Path | None = None) -> None:
        """Load state from file, or create empty state if missing/corrupt.

        Args:
            path: Override path (uses instance path if None).
        """
        target = Path(path) if path else self._path

        if not target.exists():
            logger.info("State file not found at %s — starting with empty state", target)
            self._state = BotState()
            return

        try:
            raw = target.read_text(encoding="utf-8")
            data = json.loads(raw)
            self._state = BotState.model_validate(data)
            logger.info("State loaded from %s", target)
        except Exception as e:
            logger.warning(
                "Corrupt or invalid state file at %s: %s — resetting to empty state",
                target, e,
            )
            self._state = BotState()

    def save(self) -> None:
        """Atomically write current state to disk."""
        dir_ = self._path.parent
        dir_.mkdir(parents=True, exist_ok=True)

        data = self._state.model_dump(mode="json")

        fd, tmp_path = tempfile.mkstemp(dir=str(dir_), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
                f.write("\n")
            os.replace(tmp_path, str(self._path))
            logger.debug("State saved to %s", self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Pending Verifications
    # ------------------------------------------------------------------

    def add_pending(self, code: str, user_id: int, username: str | None = None) -> PendingVerification:
        """Add a pending verification entry.

        Args:
            code: The verification code.
            user_id: Telegram user ID.
            username: Telegram username (optional).

        Returns:
            The created PendingVerification.
        """
        pv = PendingVerification(user_id=user_id, username=username, code=code)
        self._state.pending_verifications[code] = pv
        self.save()
        logger.info("Added pending verification for user %d (code: %s)", user_id, code)
        return pv

    def get_pending(self, code: str) -> PendingVerification | None:
        """Retrieve a pending verification by code."""
        return self._state.pending_verifications.get(code)

    def remove_pending(self, code: str) -> bool:
        """Remove a pending verification by code.

        Returns:
            True if the code existed and was removed.
        """
        if code in self._state.pending_verifications:
            del self._state.pending_verifications[code]
            self.save()
            logger.info("Removed pending verification code: %s", code)
            return True
        return False

    def cleanup_expired(self, max_age_minutes: int = 10) -> int:
        """Remove expired pending verifications.

        Args:
            max_age_minutes: Maximum age in minutes before expiry.

        Returns:
            Number of expired entries removed.
        """
        now = datetime.now(timezone.utc)
        expired = [
            code for code, pv in self._state.pending_verifications.items()
            if (now - pv.created_at).total_seconds() > max_age_minutes * 60
        ]
        for code in expired:
            del self._state.pending_verifications[code]

        if expired:
            self.save()
            logger.info("Cleaned up %d expired verification(s)", len(expired))
        return len(expired)

    # ------------------------------------------------------------------
    # User State
    # ------------------------------------------------------------------

    def _ensure_user(self, user_id: int) -> UserState:
        """Get or create a UserState entry."""
        if user_id not in self._state.users:
            self._state.users[user_id] = UserState()
        return self._state.users[user_id]

    def get_user(self, user_id: int) -> UserState | None:
        """Get user state, or None if user has no state."""
        return self._state.users.get(user_id)

    def set_user_context(self, user_id: int, context_id: str, project: str | None = None) -> None:
        """Update a user's active chat context.

        Args:
            user_id: Telegram user ID.
            context_id: The A0 context/chat ID.
            project: Optional project name.
        """
        user = self._ensure_user(user_id)
        user.context_id = context_id
        user.project = project
        self.save()
        logger.info("Set context for user %d: context=%s project=%s", user_id, context_id, project)

    def clear_user_context(self, user_id: int) -> None:
        """Clear a user's active chat context."""
        user = self._ensure_user(user_id)
        user.context_id = None
        user.project = None
        self.save()
        logger.info("Cleared context for user %d", user_id)

    # ------------------------------------------------------------------
    # Chat Registry
    # ------------------------------------------------------------------

    def get_user_chats(self, user_id: int) -> list[ChatInfo]:
        """List all chats tracked for a user."""
        user = self._state.users.get(user_id)
        if user is None:
            return []
        return list(user.chats)

    def add_chat(self, user_id: int, context_id: str, project: str | None = None) -> None:
        """Add a chat to a user's registry.

        Args:
            user_id: Telegram user ID.
            context_id: The A0 context/chat ID.
            project: Optional project name.
        """
        user = self._ensure_user(user_id)
        # Avoid duplicates
        if not any(c.context_id == context_id for c in user.chats):
            user.chats.append(ChatInfo(context_id=context_id, project=project))
            self.save()
            logger.info("Added chat %s for user %d", context_id, user_id)

    def remove_chat(self, user_id: int, context_id: str) -> bool:
        """Remove a chat from a user's registry.

        Returns:
            True if the chat was found and removed.
        """
        user = self._state.users.get(user_id)
        if user is None:
            return False

        original_len = len(user.chats)
        user.chats = [c for c in user.chats if c.context_id != context_id]

        if len(user.chats) < original_len:
            # If the removed chat was the active one, clear it
            if user.context_id == context_id:
                user.context_id = None
                user.project = None
            self.save()
            logger.info("Removed chat %s for user %d", context_id, user_id)
            return True
        return False
