---
name: telegram-notify
description: Send notifications to Telegram via Bot API
version: 1.0.0
tags:
  - notification
  - telegram
  - messaging
  - api
author: Agent Zero
trigger_patterns:
  - "send telegram"
  - "telegram notification"
  - "notify telegram"
  - "telegram message"
---

# Telegram Notify Skill

Send notifications and messages to Telegram chats using the Telegram Bot API.

## Prerequisites

1. Create a Telegram bot via [@BotFather](https://t.me/botfather) and get your bot token
2. Get your chat ID by messaging your bot and visiting:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Configure the following in Agent Zero:
   - **Secret**: `TELEGRAM_BOT_TOKEN` - Your bot token from BotFather
   - **Variable**: `TELEGRAM_CHAT_ID` - The chat ID to send messages to

## Usage

### Method 1: Environment Variables (Recommended)

Set environment variables and run:

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token-here"
export TELEGRAM_CHAT_ID="your-chat-id-here"
python /a0/usr/skills/telegram-notify/scripts/send_message.py "Hello World"
```

Or inline:

```bash
TELEGRAM_BOT_TOKEN="your-bot-token-here" TELEGRAM_CHAT_ID="your-chat-id-here" \
    python /a0/usr/skills/telegram-notify/scripts/send_message.py "Hello World"
```

### Method 2: Command Line Arguments

```bash
python /a0/usr/skills/telegram-notify/scripts/send_message.py "Hello World" \
    --token "your-bot-token-here" \
    --chat-id "your-chat-id-here"
```

### Method 3: Agent Zero Secrets (Recommended for Agent Zero users)

Configure `TELEGRAM_BOT_TOKEN` as a secret and `TELEGRAM_CHAT_ID` as a variable in Agent Zero settings, then use:

```bash
python /a0/usr/skills/telegram-notify/scripts/send_message.py "Hello World" \
    --token "$TELEGRAM_BOT_TOKEN" \
    --chat-id "$TELEGRAM_CHAT_ID"
```

### Send with HTML formatting

```bash
python /a0/usr/skills/telegram-notify/scripts/send_message.py \
    "<b>Bold</b> and <i>italic</i> message" \
    --token "$TELEGRAM_BOT_TOKEN" \
    --chat-id "$TELEGRAM_CHAT_ID" \
    --parse-mode HTML
```

### Send silently (no notification sound)

```bash
python /a0/usr/skills/telegram-notify/scripts/send_message.py \
    "Silent message" \
    --token "$TELEGRAM_BOT_TOKEN" \
    --chat-id "$TELEGRAM_CHAT_ID" \
    --silent
```

### Send from Python

```python
import sys
sys.path.insert(0, '/a0/usr/skills/telegram-notify/scripts')
from send_message import send_message

result = send_message(
    text="Hello from Agent Zero!",
    bot_token="your-bot-token-here",
    chat_id="your-chat-id-here"
)
print(result)
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `message` | **Required.** The message text to send |
| `--token` | Bot token (or set TELEGRAM_BOT_TOKEN env var) |
| `--chat-id` | Target chat ID (or set TELEGRAM_CHAT_ID env var) |
| `--parse-mode` | Formatting: `HTML`, `Markdown`, or `MarkdownV2` |
| `--silent` | Send without notification sound |
| `--no-preview` | Disable web page preview for links |

## API Reference

The skill uses Telegram Bot API's `sendMessage` endpoint:
- **URL**: `https://api.telegram.org/bot<token>/sendMessage`
- **Method**: POST
- **Required Parameters**:
  - `chat_id`: Target chat ID
  - `text`: Message text to send
- **Optional Parameters**:
  - `parse_mode`: `HTML` or `Markdown` for formatting
  - `disable_web_page_preview`: `true` to disable link previews
  - `disable_notification`: `true` to send silently

## Troubleshooting

### Error: "TELEGRAM_BOT_TOKEN not set"

You must provide the bot token using one of these methods:
1. `--token` argument
2. `TELEGRAM_BOT_TOKEN` environment variable
3. Agent Zero secret (configure `TELEGRAM_BOT_TOKEN` in your Agent Zero settings)

### Error: "bots can't send messages to bots"

The chat ID you're using belongs to another bot. Use your personal chat ID or a group chat ID where your bot is a member.

### Error: "chat not found"

The bot hasn't been started by the user with that chat ID. Message your bot first to initiate the conversation.

## Files

- `scripts/send_message.py` - Main script for sending messages
- `scripts/__init__.py` - Python module marker
