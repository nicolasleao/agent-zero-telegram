"""Message handler: relay user text to Agent Zero and return formatted responses."""

import logging

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from bot.a0_client import (
    A0Client,
    A0ConnectionError,
    A0TimeoutError,
    A0APIError,
)
from bot.config import BotConfig
from bot.formatters import format_response, strip_html
from bot.state import StateManager

logger = logging.getLogger(__name__)

router = Router(name="messages")


async def _send_chunk(
    message: Message,
    text: str,
    edit: bool = False,
) -> None:
    """Send or edit a message chunk with HTML fallback.

    Attempts to send/edit with HTML parse mode. If Telegram rejects
    the HTML, retries with plain text (all tags stripped).

    Args:
        message: The Telegram message to edit or reply to.
        text: HTML-formatted text to send.
        edit: If True, edit the message instead of sending a new one.
    """
    try:
        if edit:
            await message.edit_text(text, parse_mode=ParseMode.HTML)
        else:
            await message.answer(text, parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        # HTML parse error — fall back to plain text
        logger.warning(
            "Telegram rejected HTML (edit=%s): %s — falling back to plain text",
            edit, e.message,
        )
        plain = strip_html(text)
        try:
            if edit:
                await message.edit_text(plain)
            else:
                await message.answer(plain)
        except TelegramBadRequest:
            # Last resort: truncate if still failing
            logger.error("Failed to send even plain text, truncating")
            truncated = plain[:4000] + "\n\n[Message truncated]"
            if edit:
                await message.edit_text(truncated)
            else:
                await message.answer(truncated)


@router.message(F.text)
async def handle_message(
    message: Message,
    config: BotConfig,
    state_manager: StateManager,
    a0_client: A0Client,
) -> None:
    """Handle all non-command text messages.

    Forwards the user's message to Agent Zero, formats the response,
    and sends it back as Telegram HTML.

    Uses static configuration:
    - fixed_project_name from config (all messages go to this project)
    - fixed_context_id from config, or auto_context_id from state,
      or None (A0 creates new context)
    """
    user = message.from_user
    user_id = user.id if user else 0
    user_name = user.first_name if user else "unknown"

    logger.info(
        "Message from %s (id: %d): %s",
        user_name, user_id,
        message.text[:80] if message.text else "<empty>",
    )

    # Determine project_name from fixed config
    # Priority: fixed_project_name > default_project (deprecated) > None
    project_name = config.agent_zero.fixed_project_name
    if project_name is None:
        project_name = config.agent_zero.default_project

    # Determine context_id (priority order):
    # 1. Use fixed_context_id from config if set
    # 2. Use auto_context_id from state (persisted when fixed_context_id not configured)
    # 3. If both None, send None to A0 (it will create new)
    context_id = config.agent_zero.fixed_context_id
    if context_id is None:
        context_id = state_manager.get_auto_context_id()

    logger.info(
        "Relaying message to A0 (project=%s, context=%s)",
        project_name or "<default>",
        context_id or "<auto>",
    )

    # Send processing indicator
    processing_msg = await message.answer("⏳ Processing...")

    # Call Agent Zero
    try:
        result = await a0_client.send_message(
            message=message.text,
            context_id=context_id,
            project_name=project_name,
        )
    except A0ConnectionError:
        logger.error("A0 connection error for user %d", user_id)
        await processing_msg.edit_text(
            "⚠️ Agent Zero is not reachable. Is it running?"
        )
        return
    except A0TimeoutError:
        logger.error("A0 timeout for user %d", user_id)
        await processing_msg.edit_text(
            "⏰ Request timed out. Agent Zero may still be processing."
        )
        return
    except A0APIError as e:
        logger.error("A0 API error for user %d: %s", user_id, e)
        await processing_msg.edit_text(
            "⚠️ Agent Zero returned an error. Please try again."
        )
        return

    # If A0 returned a new context_id (when we sent None), save it
    returned_context = result.get("context_id")
    if (
        config.agent_zero.fixed_context_id is None
        and state_manager.get_auto_context_id() is None
        and returned_context
    ):
        state_manager.set_auto_context_id(returned_context)
        logger.info(
            "Auto-created and persisted context_id: %s",
            returned_context,
        )

    # Format the response
    response_text = result.get("response", "")

    if not response_text or not response_text.strip():
        await processing_msg.edit_text(
            "✅ Task completed (no text response)."
        )
        return

    chunks = format_response(response_text)

    if not chunks:
        await processing_msg.edit_text(
            "✅ Task completed (no text response)."
        )
        return

    # Send first chunk by editing the processing message
    await _send_chunk(processing_msg, chunks[0], edit=True)

    # Send remaining chunks as new messages
    for chunk in chunks[1:]:
        await _send_chunk(message, chunk, edit=False)
