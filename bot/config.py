"""Configuration management for the Agent Zero Telegram Bot.

Pydantic-based configuration system that loads, validates, and provides
access to config.json.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

logger = logging.getLogger(__name__)


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""
    bot_token: str
    approved_users: list[int] = Field(default_factory=list)
    parse_mode: str = "HTML"


class AgentZeroConfig(BaseModel):
    """Agent Zero API configuration."""
    host: str = "http://agent-zero"
    port: int = 80
    api_key: str
    default_project: str | None = None  # Deprecated: use fixed_project_name
    fixed_project_name: str | None = None  # All messages go to this project
    fixed_context_id: str | None = None  # If set, use this context; else auto-create
    timeout_seconds: int = 300
    lifetime_hours: int = 24

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_url(self) -> str:
        """Combine host and port into a base URL for API calls."""
        host = self.host.rstrip("/")
        if (host.startswith("http://") and self.port == 80) or \
           (host.startswith("https://") and self.port == 443):
            return host
        return f"{host}:{self.port}"


class BotConfig(BaseModel):
    """Top-level bot configuration."""
    telegram: TelegramConfig
    agent_zero: AgentZeroConfig
    state_file: str = "/data/state.json"


def load(path: str | Path = "config.json") -> BotConfig:
    """Load and validate configuration from a JSON file.

    Args:
        path: Path to the config.json file.

    Returns:
        Validated BotConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
        pydantic.ValidationError: If the config fails validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {path.resolve()}\n"
            f"Copy config.example.json to config.json and fill in your values."
        )

    logger.info("Loading configuration from %s", path)
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"Invalid JSON in configuration file {path}: {e.msg}",
            e.doc,
            e.pos,
        ) from e

    config = BotConfig.model_validate(data)
    logger.info("Configuration loaded successfully")
    return config


def save(path: str | Path, config: BotConfig) -> None:
    """Atomically write configuration to a JSON file.

    Writes to a temporary file first, then renames to the target path
    to prevent corruption on crash.

    Args:
        path: Target path for the config file.
        config: The configuration to persist.
    """
    path = Path(path)
    data = config.model_dump(mode="json", exclude={"agent_zero": {"base_url"}})

    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=str(dir_), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, default=str)
            f.write("\n")
        os.replace(tmp_path, str(path))
        logger.info("Configuration saved to %s", path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
