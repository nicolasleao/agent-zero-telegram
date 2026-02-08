"""Command handlers for the Telegram bot."""

import logging

import aiohttp
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from bot.config import BotConfig
from bot.state import StateManager
from bot.a0_client import A0Client, A0ConnectionError

logger = logging.getLogger(__name__)

router = Router(name="commands")


@router.message(CommandStart())
async def cmd_start(message: Message, config: BotConfig) -> None:
    """Handle the /start command.

    Shows welcome message and project info.
    """
    user = message.from_user
    user_name = user.first_name if user else "there"

    logger.info("/start from user %s (id: %s)", user_name, user.id if user else "unknown")

    # Determine project name to display
    project_display = config.agent_zero.fixed_project_name
    if project_display is None:
        project_display = config.agent_zero.default_project
    project_display = project_display or "Default"

    welcome_text = (
        f"🤖 <b>Welcome to Agent Zero Bot!</b>\n\n"
        f"Connected to project: <b>{project_display}</b>\n\n"
        f"Send me any message and I'll forward it to Agent Zero.\n"
        f"All approved users share the same conversation.\n\n"
        f"<b>Commands:</b>\n"
        f"/help - Show available commands\n"
        f"/status - Show connection info"
    )

    await message.answer(welcome_text)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle the /help command.

    Shows available commands.
    """
    logger.info("/help from user %s", message.from_user.id if message.from_user else "unknown")
    help_text = (
        "<b>Available Commands:</b>\n\n"
        "<b>/start</b> - Welcome message and project info\n"
        "<b>/help</b> - Show this help message\n"
        "<b>/status</b> - Show connection status and configuration"
    )

    await message.answer(help_text)


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    config: BotConfig,
    state_manager: StateManager,
    a0_client: A0Client,
) -> None:
    """Handle the /status command.

    Shows bot status, project info, context ID, and connection status.
    """
    user = message.from_user
    user_id = user.id if user else 0
    user_name = user.first_name if user else "unknown"

    logger.info("/status from user %s (id: %s)", user_name, user_id)

    # Determine project name
    project_name = config.agent_zero.fixed_project_name
    if project_name is None:
        project_name = config.agent_zero.default_project
    project_display = project_name or "Default"

    # Determine context ID source
    context_id = config.agent_zero.fixed_context_id
    context_source = "fixed"
    if context_id is None:
        context_id = state_manager.get_auto_context_id()
        context_source = "auto"

    # Truncate context ID for display
    if context_id:
        context_display = context_id[:16] + "..." if len(context_id) > 16 else context_id
    else:
        context_display = "Will auto-create on first message"

    # Test A0 connectivity with a lightweight request
    connection_status = "❌ Disconnected"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                config.agent_zero.base_url,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status < 500:
                    connection_status = "✅ Connected"
                else:
                    connection_status = "⚠️ Degraded"
    except Exception as e:
        logger.debug("A0 connectivity check failed: %s", e)
        connection_status = "❌ Disconnected"

    status_text = (
        "📊 <b>Bot Status</b>\n\n"
        f"<b>Project:</b> {project_display}\n"
        f"<b>Context:</b> {context_display} [{context_source}]\n"
        f"<b>Connection:</b> {connection_status}\n"
        f"<b>Your ID:</b> <code>{user_id}</code>"
    )

    await message.answer(status_text)
