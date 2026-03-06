#!/usr/bin/env python3
"""
Telegram Notification Script
Sends messages to Telegram via Bot API

Usage:
    python send_message.py "Hello World"
    python send_message.py "Hello" --token "123456:ABC-DEF" --chat-id 123456789
    TELEGRAM_BOT_TOKEN="123456:ABC" python send_message.py "Hello"
    python send_message.py "<b>Bold</b>" --parse-mode HTML
"""

import argparse
import os
import sys
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode


def get_config(cli_token=None, cli_chat_id=None):
    """Get configuration from environment variables or CLI arguments."""
    # Priority: CLI args > environment variables
    bot_token = cli_token or os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = cli_chat_id or os.environ.get('TELEGRAM_CHAT_ID') or os.environ.get('TELEGRAM_SENDER_ID')

    if not bot_token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN not set.\n\n"
            "To fix this, either:\n"
            "  1. Pass --token: python send_message.py 'Hello' --token 'YOUR_TOKEN'\n"
            "  2. Set env var: TELEGRAM_BOT_TOKEN='your-token' python send_message.py 'Hello'\n"
            "  3. Configure TELEGRAM_BOT_TOKEN as a secret in Agent Zero settings\n"
        )

    if not chat_id:
        raise ValueError(
            "TELEGRAM_CHAT_ID not set.\n\n"
            "To fix this, either:\n"
            "  1. Pass --chat-id: python send_message.py 'Hello' --chat-id 123456789\n"
            "  2. Set env var: TELEGRAM_CHAT_ID='123456789' python send_message.py 'Hello'\n"
            "  3. Configure TELEGRAM_CHAT_ID as a variable in Agent Zero settings\n"
        )

    return bot_token, chat_id


def send_message(text, bot_token=None, chat_id=None, parse_mode=None, disable_notification=False, disable_web_page_preview=False):
    """
    Send a message to Telegram using Bot API.

    Args:
        text: Message text to send
        bot_token: Bot token (optional, uses TELEGRAM_BOT_TOKEN from env if not provided)
        chat_id: Target chat ID (optional, uses TELEGRAM_CHAT_ID from env if not provided)
        parse_mode: 'HTML' or 'Markdown' for formatting
        disable_notification: Send message silently
        disable_web_page_preview: Disable link previews

    Returns:
        dict: API response from Telegram
    """
    bot_token, default_chat_id = get_config(bot_token, chat_id)
    chat_id = chat_id or default_chat_id

    # Build API URL
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # Build payload
    payload = {
        'chat_id': chat_id,
        'text': text,
    }

    if parse_mode:
        payload['parse_mode'] = parse_mode
    if disable_notification:
        payload['disable_notification'] = 'true'
    if disable_web_page_preview:
        payload['disable_web_page_preview'] = 'true'

    # Send request
    data = urlencode(payload).encode('utf-8')
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    try:
        request = Request(api_url, data=data, headers=headers, method='POST')
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result
    except HTTPError as e:
        error_body = e.read().decode('utf-8')
        try:
            error_data = json.loads(error_body)
            error_msg = error_data.get('description', error_body)
        except json.JSONDecodeError:
            error_msg = error_body
        raise RuntimeError(f"Telegram API error: {error_msg}")
    except URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")


def main():
    parser = argparse.ArgumentParser(
        description='Send notifications to Telegram via Bot API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python send_message.py "Hello World"
  python send_message.py "Hello" --token "123456:ABC-DEF" --chat-id 123456789
  TELEGRAM_BOT_TOKEN="123456:ABC" python send_message.py "Hello"
  python send_message.py "<b>Bold</b>" --parse-mode HTML
        """
    )
    parser.add_argument('message', help='Message text to send')
    parser.add_argument('--token', help='Bot token (or set TELEGRAM_BOT_TOKEN env var)')
    parser.add_argument('--chat-id', help='Target chat ID (or set TELEGRAM_CHAT_ID env var)')
    parser.add_argument('--parse-mode', choices=['HTML', 'Markdown', 'MarkdownV2'],
                        help='Message parse mode for formatting')
    parser.add_argument('--silent', action='store_true',
                        help='Send message without notification')
    parser.add_argument('--no-preview', action='store_true',
                        help='Disable web page preview for links')

    args = parser.parse_args()

    try:
        result = send_message(
            text=args.message,
            bot_token=args.token,
            chat_id=args.chat_id,
            parse_mode=args.parse_mode,
            disable_notification=args.silent,
            disable_web_page_preview=args.no_preview
        )

        if result.get('ok'):
            message_id = result['result']['message_id']
            chat = result['result']['chat']
            print(f"✅ Message sent successfully!")
            print(f"   Message ID: {message_id}")
            print(f"   Chat: {chat.get('title', chat.get('username', chat['id']))}")
            return 0
        else:
            print(f"❌ Failed to send message: {result}", file=sys.stderr)
            return 1

    except ValueError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
