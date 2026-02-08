"""Async HTTP client for the Agent Zero API.

Wraps all A0 API calls with proper error handling, lazy session
creation, and custom exception types.
"""

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Custom Exceptions
# ------------------------------------------------------------------

class A0Error(Exception):
    """Base exception for all A0 client errors."""


class A0ConnectionError(A0Error):
    """Raised when the A0 server is unreachable."""


class A0TimeoutError(A0Error):
    """Raised when a request to A0 times out."""


class A0APIError(A0Error):
    """Raised when A0 returns a non-2xx response.

    Attributes:
        status: HTTP status code.
        body: Response body text.
    """

    def __init__(self, status: int, body: str = "") -> None:
        self.status = status
        self.body = body
        super().__init__(f"A0 API error {status}: {body[:200]}")


# ------------------------------------------------------------------
# Client
# ------------------------------------------------------------------

class A0Client:
    """Async HTTP client for Agent Zero API endpoints.

    Uses lazy session creation — the aiohttp.ClientSession is created
    on the first API call, not at instantiation time.

    Args:
        base_url: The A0 server base URL (e.g. "http://agent-zero:80").
        api_key: The API key for X-API-KEY authentication.
        timeout: Request timeout in seconds (default 300).
    """

    def __init__(self, base_url: str, api_key: str, timeout: int = 300) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the existing session or lazily create one."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-API-KEY": self._api_key},
                timeout=self._timeout,
            )
            logger.debug("Created new aiohttp session for A0 client")
        return self._session

    async def _request(
        self, method: str, path: str, json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Send an HTTP request to A0 with error mapping.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path (e.g. "/api_message").
            json_body: Optional JSON body.

        Returns:
            Parsed JSON response dict, or None for empty responses.

        Raises:
            A0ConnectionError: If the server is unreachable.
            A0TimeoutError: If the request times out.
            A0APIError: If the server returns a non-2xx status.
        """
        url = f"{self._base_url}{path}"
        session = await self._get_session()

        try:
            logger.debug("A0 %s %s body=%s", method, url, json_body)
            async with session.request(method, url, json=json_body) as resp:
                body_text = await resp.text()

                if resp.status >= 400:
                    logger.error(
                        "A0 API error: %s %s → %d %s",
                        method, url, resp.status, body_text[:200],
                    )
                    raise A0APIError(resp.status, body_text)

                if not body_text.strip():
                    return None

                return await resp.json(content_type=None)

        except A0APIError:
            raise
        except aiohttp.ClientConnectorError as e:
            logger.error("A0 connection error: %s", e)
            raise A0ConnectionError(str(e)) from e
        except asyncio.TimeoutError as e:
            logger.error("A0 request timed out: %s %s", method, url)
            raise A0TimeoutError(f"Request timed out: {method} {url}") from e
        except aiohttp.ClientError as e:
            logger.error("A0 client error: %s", e)
            raise A0ConnectionError(str(e)) from e

    # ------------------------------------------------------------------
    # Public API Methods
    # ------------------------------------------------------------------

    async def send_message(
        self,
        message: str,
        context_id: str | None = None,
        project_name: str | None = None,
        attachments: list[str] | None = None,
    ) -> dict[str, str]:
        """Send a message to Agent Zero.

        Args:
            message: The user message text.
            context_id: Existing context/chat ID (omit to auto-create).
            project_name: Optional project name for the context.
            attachments: Optional list of attachment references.

        Returns:
            Dict with "context_id" and "response" keys.
        """
        payload: dict[str, Any] = {
            "message": message,
            "text": message,
            "attachments": attachments or [],
        }
        if context_id:
            payload["context"] = context_id
        if project_name:
            payload["project"] = project_name

        logger.info(
            "Sending message to A0 (context=%s, project=%s, len=%d)",
            context_id or "<new>", project_name or "<default>", len(message),
        )

        result = await self._request("POST", "/api_message", json_body=payload)

        if result is None:
            raise A0APIError(0, "Empty response from /api_message")

        return {
            "context_id": result.get("context", context_id or ""),
            "response": result.get("response", ""),
        }

    async def reset_chat(self, context_id: str) -> None:
        """Reset a chat's history in Agent Zero.

        Args:
            context_id: The context/chat ID to reset.
        """
        logger.info("Resetting A0 chat: %s", context_id)
        await self._request("POST", "/api_reset_chat", json_body={"context": context_id})

    async def terminate_chat(self, context_id: str) -> None:
        """Terminate a chat in Agent Zero.

        Args:
            context_id: The context/chat ID to terminate.
        """
        logger.info("Terminating A0 chat: %s", context_id)
        await self._request("POST", "/api_terminate_chat", json_body={"context": context_id})

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("A0 client session closed")
            self._session = None
