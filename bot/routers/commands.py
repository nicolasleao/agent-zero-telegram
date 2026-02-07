"""Command handlers for the Telegram bot."""

import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.config import BotConfig
from bot.state import StateManager

logger = logging.getLogger(__name__)

router = Router(name="commands")


@router.message(CommandStart())
async def cmd_start(message: Message, config: BotConfig, state_manager: StateManager) -> None:
    """Handle the /start command.

    Sends a welcome message to the user.
    """
    user = message.from_user
    user_name = user.first_name if user else "there"

    logger.info("/start from user %s (id: %s)", user_name, user.id if user else "unknown")

    welcome_text = (
        f"\U0001f44b <b>Welcome to Agent Zero, {user_name}!</b>\n"
        f"\n"
        f"I'm your bridge to Agent Zero. Send me any message and "
        f"I'll forward it to A0 for processing.\n"
        f"\n"
        f"<b>Available commands:</b>\n"
        f"/start \u2014 Show this welcome message\n"
        f"/help \u2014 List all commands\n"
        f"/new \u2014 Start a new chat\n"
        f"/status \u2014 Show current session info\n"
        f"/reset \u2014 Reset current chat history\n"
        f"/delete \u2014 Delete current chat\n"
    )

    await message.answer(welcome_text)
