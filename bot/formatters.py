"""Markdown-to-Telegram-HTML formatter with message splitting.

Converts Agent Zero's markdown output into Telegram-compatible HTML,
handling code blocks, inline formatting, links, headers, blockquotes,
tables, and images. Splits long messages at safe boundaries.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Telegram message length limit
MAX_MESSAGE_LENGTH = 4096


# ------------------------------------------------------------------
# HTML Entity Escaping
# ------------------------------------------------------------------

def _escape_html(text: str) -> str:
    """Escape HTML special characters in plain text.

    Only escapes &, <, > — the minimum required by Telegram HTML mode.
    """
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ------------------------------------------------------------------
# Block-Level Extraction (pre-processing)
# ------------------------------------------------------------------

# Placeholder pattern that won't appear in normal text
_BLOCK_PLACEHOLDER = "««BLK_{idx}»»"


def _extract_fenced_blocks(text: str) -> tuple[str, dict[int, str]]:
    """Extract fenced code blocks and replace with placeholders.

    This prevents inline formatting rules from mangling code content.
    Code content is HTML-escaped inside the blocks.

    Returns:
        Tuple of (text_with_placeholders, {index: html_block}).
    """
    blocks: dict[int, str] = {}
    counter = 0

    def _replace_block(match: re.Match) -> str:
        nonlocal counter
        lang = match.group(1) or ""
        code = match.group(2)
        # Escape HTML inside code blocks
        escaped_code = _escape_html(code)
        # Strip single leading/trailing newline if present
        if escaped_code.startswith("\n"):
            escaped_code = escaped_code[1:]
        if escaped_code.endswith("\n"):
            escaped_code = escaped_code[:-1]

        if lang:
            html = f'<pre><code class="language-{_escape_html(lang)}">{escaped_code}</code></pre>'
        else:
            html = f"<pre><code>{escaped_code}</code></pre>"

        idx = counter
        blocks[idx] = html
        counter += 1
        return _BLOCK_PLACEHOLDER.format(idx=idx)

    # Match fenced code blocks: ```lang\n...\n```
    pattern = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
    result = pattern.sub(_replace_block, text)
    return result, blocks


def _extract_tables(text: str, blocks: dict[int, str]) -> str:
    """Detect markdown tables and convert to monospace <pre> blocks.

    A table is detected as consecutive lines containing pipe characters
    in a tabular pattern (at least 3 pipe-separated segments).
    """
    counter = max(blocks.keys(), default=-1) + 1
    lines = text.split("\n")
    result_lines: list[str] = []
    table_buffer: list[str] = []

    def _flush_table() -> None:
        nonlocal counter
        if not table_buffer:
            return
        # Filter out separator lines (e.g. |---|---|)
        content_lines = []
        for line in table_buffer:
            stripped = line.strip()
            # Check if it's a separator line: only |, -, :, spaces
            if re.match(r"^[\|\-:\s]+$", stripped):
                continue
            content_lines.append(line)

        if content_lines:
            # Escape HTML entities in table content
            table_text = _escape_html("\n".join(content_lines))
            html = f"<pre>{table_text}</pre>"
            blocks[counter] = html
            result_lines.append(_BLOCK_PLACEHOLDER.format(idx=counter))
            counter += 1
        table_buffer.clear()

    for line in lines:
        stripped = line.strip()
        # A table line has pipes and at least 3 segments
        if "|" in stripped:
            cells = stripped.split("|")
            if len(cells) >= 3:
                table_buffer.append(line)
                continue

        # Not a table line
        _flush_table()
        result_lines.append(line)

    _flush_table()
    return "\n".join(result_lines)


# ------------------------------------------------------------------
# Inline Formatting
# ------------------------------------------------------------------

def _convert_inline(text: str) -> str:
    """Apply inline markdown-to-HTML conversions on already-escaped text.

    At this point, all plain-text < > & are already escaped as entities.
    The markdown syntax characters (*, _, `, [, ], etc.) are still raw.

    Inline code is extracted to placeholders FIRST to prevent formatting
    rules from mangling code content (e.g. *args, **kwargs, __init__).
    """
    # Step 1: Extract inline code to placeholders FIRST
    inline_blocks: dict[int, str] = {}
    inline_counter = 0

    def _protect_inline_code(match: re.Match) -> str:
        nonlocal inline_counter
        idx = inline_counter
        inline_blocks[idx] = f"<code>{match.group(1)}</code>"
        inline_counter += 1
        return f"\u00abICODE_{idx}\u00bb"

    text = re.sub(r"`([^`]+)`", _protect_inline_code, text)

    # Step 2: Images: ![alt](url) -> <a href="url">[Image: alt]</a>
    def _image(m: re.Match) -> str:
        alt = m.group(1)
        url = m.group(2)
        return f'<a href="{url}">[Image: {alt}]</a>'

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _image, text)

    # Links: [text](url) -> <a href="url">text</a>
    def _link(m: re.Match) -> str:
        link_text = m.group(1)
        url = m.group(2)
        return f'<a href="{url}">{link_text}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, text)

    # Bold: **text** or __text__ -> <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic: *text* or _text_ -> <i>text</i>
    text = re.sub(r"(?<!\w)\*(?!\*)(.+?)(?<!\*)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(?!_)(.+?)(?<!_)_(?!\w)", r"<i>\1</i>", text)

    # Strikethrough: ~~text~~ -> <s>text</s>
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Step 3: Restore inline code from placeholders
    for idx, html in inline_blocks.items():
        text = text.replace(f"\u00abICODE_{idx}\u00bb", html)

    return text


# ------------------------------------------------------------------
# Line-Level Formatting
# ------------------------------------------------------------------

def _convert_line_elements(text: str) -> str:
    """Convert line-level markdown elements (headers, blockquotes, HRs).

    Operates on already-escaped text. Markdown syntax chars are still raw.
    """
    lines = text.split("\n")
    result: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Skip placeholder lines
        if "««BLK_" in stripped:
            result.append(line)
            continue

        # Headers: # Header -> <b>Header</b>
        header_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if header_match:
            header_text = header_match.group(2)
            result.append(f"<b>{header_text}</b>")
            continue

        # Blockquotes: &gt; text -> <blockquote>text</blockquote>
        # Note: > is escaped to &gt; at this point
        bq_match = re.match(r"^&gt;\s?(.*)$", stripped)
        if bq_match:
            bq_text = bq_match.group(1)
            result.append(f"<blockquote>{bq_text}</blockquote>")
            continue

        # Horizontal rules: --- or *** or ___
        if re.match(r"^[-*_]{3,}$", stripped):
            result.append("\u2014" * 20)
            continue

        result.append(line)

    return "\n".join(result)


# ------------------------------------------------------------------
# Message Splitting
# ------------------------------------------------------------------

def _split_message(html: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split an HTML message into chunks that fit Telegram's limit.

    Strategy:
    1. Try to split at double newlines (paragraph breaks).
    2. Avoid splitting inside a <pre>...</pre> block.
    3. If a single pre block exceeds max_length, split at line boundaries
       within it, properly closing and reopening tags.
    4. Account for tag overhead when closing/reopening pre blocks.

    Args:
        html: The full HTML string.
        max_length: Maximum characters per chunk.

    Returns:
        List of HTML chunks, each within max_length.
    """
    if len(html) <= max_length:
        return [html]

    CLOSE_TAGS = "</code></pre>"
    OPEN_TAGS = "<pre><code>"
    TAG_OVERHEAD = len(CLOSE_TAGS)  # 13 chars reserved for closing

    chunks: list[str] = []
    remaining = html
    in_pre = False  # Track if we're continuing a split pre block

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining.strip())
            break

        # Reduce effective limit if we might need to append closing tags
        effective_limit = max_length - TAG_OVERHEAD if in_pre else max_length
        # Safety floor: never go below half the limit
        effective_limit = max(effective_limit, max_length // 2)

        candidate = remaining[:effective_limit]

        # Count pre tag balance in the candidate
        pre_opens = candidate.count("<pre")
        pre_closes = candidate.count("</pre>")
        currently_in_pre = in_pre or (pre_opens > pre_closes)

        split_pos = -1

        if currently_in_pre:
            # Try to find the closing </pre> within the full max_length
            close_pos = remaining.find("</pre>")
            if close_pos != -1:
                end_pos = close_pos + len("</pre>")
                if end_pos <= max_length:
                    # We can include the entire pre block
                    split_pos = end_pos
                    currently_in_pre = False
                else:
                    # Pre block too long — split at line boundary within it
                    split_pos = candidate.rfind("\n")
                    if split_pos <= 0:
                        split_pos = effective_limit
            else:
                # No closing tag found at all — split at line boundary
                split_pos = candidate.rfind("\n")
                if split_pos <= 0:
                    split_pos = effective_limit
        else:
            # Not in pre — prefer paragraph breaks, then line breaks
            split_pos = candidate.rfind("\n\n")
            if split_pos <= 0:
                split_pos = candidate.rfind("\n")
            if split_pos <= 0:
                split_pos = effective_limit

        chunk = remaining[:split_pos].strip()
        remaining = remaining[split_pos:].strip()

        if chunk:
            # Check if this chunk has unclosed <pre> tags
            chunk_pre_opens = chunk.count("<pre")
            chunk_pre_closes = chunk.count("</pre>")

            if chunk_pre_opens > chunk_pre_closes:
                # Need to append closing tags — check if it fits
                if len(chunk) + len(CLOSE_TAGS) > max_length:
                    # Closing tags would push over limit — trim the chunk
                    overshoot = len(chunk) + len(CLOSE_TAGS) - max_length
                    # Find a line break to trim at
                    trim_pos = chunk.rfind("\n", 0, len(chunk) - overshoot)
                    if trim_pos > 0:
                        remaining = chunk[trim_pos:].lstrip() + "\n" + remaining
                        chunk = chunk[:trim_pos]
                chunk += CLOSE_TAGS
                in_pre = True
            else:
                in_pre = False

            chunks.append(chunk)
        else:
            # Avoid infinite loop on empty chunks
            if remaining:
                # Force progress
                chunks.append(remaining[:max_length].strip())
                remaining = remaining[max_length:].strip()
            in_pre = False

        # Re-open pre block for continuation if needed
        if in_pre and remaining and not remaining.startswith("<pre"):
            remaining = OPEN_TAGS + remaining

    return [c for c in chunks if c]


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def format_response(markdown_text: str) -> list[str]:
    """Convert A0 markdown response to Telegram-safe HTML chunks.

    Pipeline:
    1. Extract fenced code blocks (content escaped, replaced with placeholders)
    2. Extract tables (content escaped, replaced with placeholders)
    3. Escape all remaining plain text (< > &)
    4. Convert line-level elements (headers, blockquotes)
    5. Convert inline formatting (bold, italic, code, links, images)
    6. Restore code blocks and tables from placeholders
    7. Clean up and split into Telegram-sized chunks

    Args:
        markdown_text: Raw markdown text from Agent Zero.

    Returns:
        List of HTML strings, each within Telegram's 4096-char limit.
    """
    if not markdown_text or not markdown_text.strip():
        return []

    text = markdown_text

    # Step 1: Extract fenced code blocks (protect from all processing)
    text, blocks = _extract_fenced_blocks(text)

    # Step 2: Extract tables (protect from inline processing)
    text = _extract_tables(text, blocks)

    # Step 3: Escape ALL remaining plain text
    # Split on placeholders to avoid escaping them
    parts = re.split(r"(««BLK_\d+»»)", text)
    escaped_parts = []
    for part in parts:
        if part.startswith("««BLK_"):
            escaped_parts.append(part)  # Placeholder — pass through
        else:
            escaped_parts.append(_escape_html(part))
    text = "".join(escaped_parts)

    # Step 4: Convert line-level elements (headers, blockquotes, HRs)
    text = _convert_line_elements(text)

    # Step 5: Apply inline formatting (bold, italic, code, links, images)
    text = _convert_inline(text)

    # Step 6: Restore code blocks and tables
    for idx, html in blocks.items():
        placeholder = _BLOCK_PLACEHOLDER.format(idx=idx)
        text = text.replace(placeholder, html)

    # Step 7: Clean up excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    # Step 8: Split into Telegram-sized chunks
    return _split_message(text)


def strip_html(text: str) -> str:
    """Remove all HTML tags from text (fallback for parse errors).

    Args:
        text: HTML-formatted text.

    Returns:
        Plain text with all HTML tags removed.
    """
    return re.sub(r"<[^>]+>", "", text)
