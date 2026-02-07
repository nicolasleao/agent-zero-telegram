"""Bot entry point: initialize, wire dependencies, and start polling."""

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.a0_client import A0Client
from bot.config import load as load_config
from bot.middleware.auth import AuthMiddleware
from bot.state import StateManager
from bot.routers import commands, messages

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure logging to stdout at INFO level."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # Reduce noise from third-party libraries
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


async def main() -> None:
    """Main async entry point."""
    setup_logging()
    logger.info("Starting Agent Zero Telegram Bot...")

    # Load configuration
    config_path = Path("config.json")
    try:
        config = load_config(config_path)
    except Exception as e:
        logger.error("Failed to load configuration: %s", e)
        sys.exit(1)

    logger.info("Configuration loaded. A0 endpoint: %s", config.agent_zero.base_url)

    # Initialize state manager
    state_manager = StateManager(config.state_file)
    state_manager.load()
    logger.info("State manager initialized (state file: %s)", config.state_file)

    # Initialize A0 client
    a0_client = A0Client(
        base_url=config.agent_zero.base_url,
        api_key=config.agent_zero.api_key,
        timeout=config.agent_zero.timeout_seconds,
    )
    logger.info(
        "A0 client initialized (base_url: %s, timeout: %ds)",
        config.agent_zero.base_url,
        config.agent_zero.timeout_seconds,
    )

    # Initialize bot and dispatcher
    bot = Bot(
        token=config.telegram.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )
    dp = Dispatcher()

    # Inject dependencies via workflow_data
    dp.workflow_data["config"] = config
    dp.workflow_data["config_path"] = config_path
    dp.workflow_data["state_manager"] = state_manager
    dp.workflow_data["a0_client"] = a0_client

    # Register middleware
    dp.message.outer_middleware(AuthMiddleware())
    dp.callback_query.outer_middleware(AuthMiddleware())
    logger.info("Auth middleware registered")

    # Register routers
    dp.include_router(commands.router)
    dp.include_router(messages.router)

    logger.info("Routers registered. Starting long polling...")

    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down...")
        state_manager.save()
        await a0_client.close()
        await bot.session.close()
        logger.info("Shutdown complete.")


def run() -> None:
    """Synchronous wrapper to run the async main."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
