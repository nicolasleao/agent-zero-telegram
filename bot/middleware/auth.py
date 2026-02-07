"""Authentication middleware for the Agent Zero Telegram Bot.

Outer middleware that gates all incoming updates based on user approval status.
Unapproved users receive a verification code; pending users are silently dropped.
"""

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from bot.config import load as load_config, BotConfig
from bot.state import StateManager

logger = logging.getLogger(__name__)

# Constants
CODE_EXPIRY_MINUTES = 10


class AuthMiddleware(BaseMiddleware):
    """Outer middleware that enforces user approval before handlers run.

    Behavior:
    - Approved users (in config.approved_users) pass through immediately.
    - Unknown users receive a verification code and are dropped.
    - Pending users (with a non-expired code) are silently dropped.
    - Config is re-read from disk on every call for hot-reload support.
    - Expired codes are lazily cleaned up on each invocation.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Extract sender ID from the event
        sender_id = self._extract_sender_id(event)
        if sender_id is None:
            # Cannot determine sender — pass through (e.g. channel posts)
            return await handler(event, data)

        # Get dependencies from workflow_data
        config_path: Path = data["config_path"]
        state_manager: StateManager = data["state_manager"]

        # Hot-reload config from disk to pick up CLI changes immediately
        try:
            config = load_config(config_path)
        except Exception as e:
            logger.error("Failed to reload config from %s: %s", config_path, e)
            # Fall back to the config already in workflow_data
            config = data["config"]

        # Update the config in workflow_data so handlers see the fresh version
        data["config"] = config

        # Lazy cleanup of expired pending verifications
        state_manager.cleanup_expired(max_age_minutes=CODE_EXPIRY_MINUTES)

        # 1. Check if user is approved
        if sender_id in config.telegram.approved_users:
            return await handler(event, data)

        # 2. Check if user already has a pending (non-expired) verification
        pending = self._find_pending_for_user(state_manager, sender_id)
        if pending is not None:
            # Silently drop — user already has a pending code
            logger.debug(
                "Dropping message from pending user %d (code: %s)",
                sender_id, pending.code,
            )
            return None

        # 3. Unknown user — generate a new verification code
        code = secrets.token_hex(3).upper()  # 6 hex characters
        username = self._extract_username(event)

        state_manager.add_pending(
            code=code,
            user_id=sender_id,
            username=username,
        )

        logger.info(
            "New verification code %s generated for user %d (@%s)",
            code, sender_id, username or "unknown",
        )

        # Send the verification code to the user
        await self._send_verification_message(event, code)

        # Drop the update — do not pass to handler
        return None

    @staticmethod
    def _extract_sender_id(event: TelegramObject) -> int | None:
        """Extract the sender's Telegram user ID from the event."""
        if isinstance(event, Message):
            return event.from_user.id if event.from_user else None
        if isinstance(event, CallbackQuery):
            return event.from_user.id if event.from_user else None
        # For other event types, try the generic from_user attribute
        user = getattr(event, "from_user", None)
        if user is not None:
            return user.id
        return None

    @staticmethod
    def _extract_username(event: TelegramObject) -> str | None:
        """Extract the sender's username from the event."""
        user = None
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user
        else:
            user = getattr(event, "from_user", None)
        if user is not None:
            return user.username
        return None

    @staticmethod
    def _find_pending_for_user(
        state_manager: StateManager, user_id: int
    ) -> Any | None:
        """Find a pending verification for a given user ID.

        Also enforces the rate limit: if a code was generated less than
        """
        now = datetime.now(timezone.utc)
        for pv in state_manager.state.pending_verifications.values():
            if pv.user_id == user_id:
                age_seconds = (now - pv.created_at).total_seconds()
                # Code is still valid (not expired) — treat as pending
                if age_seconds < CODE_EXPIRY_MINUTES * 60:
                    return pv
        return None

    @staticmethod
    async def _send_verification_message(
        event: TelegramObject, code: str
    ) -> None:
        """Send the verification code message to the user."""
        text = (
            "\U0001f510 <b>Verification Required</b>\n"
            "\n"
            "Your verification code is: <code>" + code + "</code>\n"
            "\n"
            "Ask the admin to run:\n"
            "<code>python -m bot.cli approve " + code + "</code>"
        )

        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery) and event.message:
            await event.message.answer(text)
