"""Admin CLI tool for the Agent Zero Telegram Bot.

Standalone script for managing user approvals and verifications.
Runs outside the bot's event loop — operates directly on config.json
and the state file.

Usage:
    python -m bot.cli approve <CODE>    — Approve a pending user by verification code
    python -m bot.cli pending            — List all pending verifications
    python -m bot.cli users              — List all approved user IDs
    python -m bot.cli revoke <USER_ID>   — Revoke an approved user
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from bot.config import load as load_config, save as save_config, BotConfig
from bot.state import StateManager

logger = logging.getLogger(__name__)

# Defaults — can be overridden via environment variables
DEFAULT_CONFIG_PATH = "config.json"


def get_paths() -> tuple[Path, Path]:
    """Resolve config and state file paths.

    Reads from environment variables if set, otherwise uses defaults.

    Returns:
        Tuple of (config_path, state_path).
    """
    config_path = Path(os.environ.get("BOT_CONFIG_PATH", DEFAULT_CONFIG_PATH))
    config = load_config(config_path)

    state_path_env = os.environ.get("BOT_STATE_PATH")
    if state_path_env:
        state_path = Path(state_path_env)
    else:
        state_path = Path(config.state_file)

    return config_path, state_path


def cmd_approve(args: argparse.Namespace) -> None:
    """Approve a pending user by verification code.

    Moves the user_id to config.approved_users, removes the pending
    verification, and optionally sends a Telegram notification.
    """
    config_path, state_path = get_paths()
    config = load_config(config_path)
    state_manager = StateManager(state_path)
    state_manager.load()

    code = args.code.upper()

    # Find the pending verification
    pending = state_manager.get_pending(code)
    if pending is None:
        print("\u274c Code not found: {}".format(code))
        print("Run 'python -m bot.cli pending' to see active codes.")
        sys.exit(1)

    # Check if code is expired (10 minutes)
    now = datetime.now(timezone.utc)
    age_seconds = (now - pending.created_at).total_seconds()
    if age_seconds > 10 * 60:
        print("\u274c Code expired: {} (age: {:.1f} minutes)".format(code, age_seconds / 60))
        print("The user needs to send a new message to get a fresh code.")
        # Clean up the expired code
        state_manager.remove_pending(code)
        sys.exit(1)

    user_id = pending.user_id
    username = pending.username

    # Check if already approved (shouldn't happen, but be safe)
    if user_id in config.telegram.approved_users:
        print("\u2139\ufe0f User {} (@{}) is already approved.".format(user_id, username or "unknown"))
        state_manager.remove_pending(code)
        sys.exit(0)

    # Add to approved users
    config.telegram.approved_users.append(user_id)
    save_config(config_path, config)

    # Remove pending verification
    state_manager.remove_pending(code)

    print("\u2705 Approved user {} (@{})".format(user_id, username or "unknown"))
    print("   Code: {}".format(code))
    print("   Added to config.json approved_users")

    # T-08: Send Telegram notification
    _send_approval_notification(config, user_id)


def _send_approval_notification(config: BotConfig, user_id: int) -> None:
    """Send a Telegram notification to the newly approved user.

    Uses a one-shot async helper that creates a Bot instance,
    sends the message, and closes. Handles failure gracefully.
    """
    async def _notify() -> None:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        bot = Bot(
            token=config.telegram.bot_token,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
            ),
        )
        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "\u2705 <b>You've been approved!</b>\n"
                    "\n"
                    "Send any message to start chatting with Agent Zero."
                ),
            )
            print("   \u2709\ufe0f Notification sent to user {}".format(user_id))
        except Exception as e:
            print("   \u26a0\ufe0f Could not send notification: {}".format(e))
            print("   (Approval was still completed successfully)")
        finally:
            await bot.session.close()

    try:
        asyncio.run(_notify())
    except Exception as e:
        print("   \u26a0\ufe0f Notification failed: {}".format(e))
        print("   (Approval was still completed successfully)")


def cmd_pending(args: argparse.Namespace) -> None:
    """List all pending verifications with details."""
    _, state_path = get_paths()
    state_manager = StateManager(state_path)
    state_manager.load()

    pending = state_manager.state.pending_verifications
    if not pending:
        print("No pending verifications.")
        return

    now = datetime.now(timezone.utc)
    print("")
    print("{:-^60}".format(" Pending Verifications "))
    print("{:<10} {:<15} {:<20} {}".format("Code", "User ID", "Username", "Age"))
    print("-" * 60)

    for code, pv in pending.items():
        age_seconds = (now - pv.created_at).total_seconds()
        age_minutes = age_seconds / 60

        if age_minutes < 1:
            age_str = "{:.0f}s".format(age_seconds)
        elif age_minutes < 60:
            age_str = "{:.1f}m".format(age_minutes)
        else:
            age_str = "{:.1f}h".format(age_minutes / 60)

        expired = " (EXPIRED)" if age_minutes > 10 else ""
        username = "@{}".format(pv.username) if pv.username else "-"

        print("{:<10} {:<15} {:<20} {}{}".format(code, pv.user_id, username, age_str, expired))

    print("")
    print("Total: {} pending verification(s)".format(len(pending)))


def cmd_users(args: argparse.Namespace) -> None:
    """List all approved user IDs from config.json."""
    config_path, _ = get_paths()
    config = load_config(config_path)

    users = config.telegram.approved_users
    if not users:
        print("No approved users.")
        return

    print("")
    print("{:-^40}".format(" Approved Users "))
    for uid in users:
        print("  {}".format(uid))
    print("")
    print("Total: {} approved user(s)".format(len(users)))


def cmd_revoke(args: argparse.Namespace) -> None:
    """Revoke an approved user by Telegram user ID."""
    config_path, _ = get_paths()
    config = load_config(config_path)

    try:
        user_id = int(args.user_id)
    except ValueError:
        print("\u274c Invalid user ID: {} (must be an integer)".format(args.user_id))
        sys.exit(1)

    if user_id not in config.telegram.approved_users:
        print("\u274c User {} is not in the approved users list.".format(user_id))
        sys.exit(1)

    config.telegram.approved_users.remove(user_id)
    save_config(config_path, config)

    print("\u2705 Revoked user {}".format(user_id))
    print("   Removed from config.json approved_users")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m bot.cli",
        description="Agent Zero Telegram Bot \u2014 Admin CLI",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        help="Available commands",
    )

    # approve <CODE>
    approve_parser = subparsers.add_parser(
        "approve",
        help="Approve a pending user by verification code",
    )
    approve_parser.add_argument(
        "code",
        type=str,
        help="The 6-character verification code",
    )
    approve_parser.set_defaults(func=cmd_approve)

    # pending
    pending_parser = subparsers.add_parser(
        "pending",
        help="List all pending verifications",
    )
    pending_parser.set_defaults(func=cmd_pending)

    # users
    users_parser = subparsers.add_parser(
        "users",
        help="List all approved user IDs",
    )
    users_parser.set_defaults(func=cmd_users)

    # revoke <USER_ID>
    revoke_parser = subparsers.add_parser(
        "revoke",
        help="Revoke an approved user by Telegram user ID",
    )
    revoke_parser.add_argument(
        "user_id",
        type=str,
        help="The Telegram user ID to revoke",
    )
    revoke_parser.set_defaults(func=cmd_revoke)

    return parser


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
