"""Message handler: relay user text to Agent Zero and return formatted responses."""

import logging
import re

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
    """
    user = message.from_user
    user_id = user.id if user else 0
    user_name = user.first_name if user else "unknown"

    logger.info(
        "Message from %s (id: %d): %s",
        user_name, user_id,
        message.text[:80] if message.text else "<empty>",
    )

    # Look up user's current context
    user_state = state_manager.get_user(user_id)
    context_id = user_state.context_id if user_state else None
    project = user_state.project if user_state else None

    # Use default project from config if user has no project set
    if not project:
        project = config.agent_zero.default_project

    # Send processing indicator
    processing_msg = await message.answer("\u23f3 Processing...")

    # Call Agent Zero
    try:
        result = await a0_client.send_message(
            message=message.text,
            context_id=context_id,
            project_name=project,
        )
    except A0ConnectionError:
        logger.error("A0 connection error for user %d", user_id)
        await processing_msg.edit_text(
            "\u26a0\ufe0f Agent Zero is not reachable. Is it running?"
        )
        return
    except A0TimeoutError:
        logger.error("A0 timeout for user %d", user_id)
        await processing_msg.edit_text(
            "\u23f0 Request timed out. Agent Zero may still be processing."
        )
        return
    except A0APIError as e:
        logger.error("A0 API error for user %d: %s", user_id, e)
        await processing_msg.edit_text(
            "\u26a0\ufe0f Agent Zero returned an error. Please try again."
        )
        return

    # Store context if new or changed
    returned_context = result["context_id"]
    if returned_context and returned_context != context_id:
        state_manager.set_user_context(user_id, returned_context, project)
        # Add to chat registry if this is a new chat
        state_manager.add_chat(user_id, returned_context, project)
        logger.info(
            "New context for user %d: %s (project: %s)",
            user_id, returned_context, project,
        )

    # Format the response
    response_text = result["response"]

    if not response_text or not response_text.strip():
        await processing_msg.edit_text(
            "\u2705 Task completed (no text response)."
        )
        return

    chunks = format_response(response_text)

    if not chunks:
        await processing_msg.edit_text(
            "\u2705 Task completed (no text response)."
        )
        return

    # Send first chunk by editing the processing message
    await _send_chunk(processing_msg, chunks[0], edit=True)

    # Send remaining chunks as new messages
    for chunk in chunks[1:]:
        await _send_chunk(message, chunk, edit=False)
