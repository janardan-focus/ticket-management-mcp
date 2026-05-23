"""
REST API client for the Ticket Management System Next.js backend.

Mirrors the error-handling patterns from the TypeScript mcp-server/api-client.ts
reference implementation: HTML-vs-JSON detection, structured error extraction,
and typed exceptions for clean tool-level error wrapping.

Usage:
    client = TMSApiClient(base_url="http://localhost:3000", bearer_token="tms_...")
    data = await client.get("/api/projects")
    result = await client.post("/api/ticket/create", json={"projectId": ..., "name": ...})
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TMSApiError(Exception):
    """Raised when the Next.js API returns a non-2xx response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    def __str__(self) -> str:
        if self.status_code:
            return f"[HTTP {self.status_code}] {super().__str__()}"
        return super().__str__()


class TMSApiClient:
    """
    Thin async HTTP client that calls the Next.js TMS REST API.

    - Forwards the caller's Bearer token on every request (pass-through auth).
    - Sets X-MCP-Internal: true for parity with the TypeScript reference client.
    - Raises TMSApiError on any non-2xx response, carrying the API's error message.
    - A single httpx.AsyncClient is reused for the lifetime of the instance to
      amortise TLS connection overhead across tool calls.
    """

    _HEADERS = {
        "Content-Type": "application/json",
        "X-MCP-Internal": "true",
    }

    def __init__(self, base_url: str, bearer_token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                **self._HEADERS,
                "Authorization": f"Bearer {bearer_token}",
            },
            timeout=30.0,
        )

    async def aclose(self) -> None:
        """Close the underlying httpx client. Call during app shutdown."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """
        GET <base_url><path>[?params].

        Returns the parsed JSON body on success.
        Raises TMSApiError on any non-2xx response.
        """
        logger.debug("GET %s params=%s", path, params)
        response = await self._client.get(path, params=params)
        return self._handle_response(response)

    async def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        """
        POST <base_url><path> with JSON body.

        Returns the parsed JSON body on success.
        Raises TMSApiError on any non-2xx response.
        """
        logger.debug("POST %s body=%s", path, json)
        response = await self._client.post(path, json=json)
        return self._handle_response(response)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _handle_response(response: httpx.Response) -> Any:
        """
        Parse and return a successful response, or raise TMSApiError.

        Handles two common error cases from Next.js:
          1. HTML error page (e.g. 500 from an unhandled exception) — detected
             by Content-Type: text/html.
          2. JSON body with an "error" or "message" field — the standard shape
             returned by the route handlers.
        """
        content_type = response.headers.get("content-type", "")

        if response.is_success:
            if "application/json" in content_type:
                return response.json()
            # Non-JSON 2xx (unlikely but safe to handle)
            return response.text

        # --- Error path ---
        status = response.status_code

        if "text/html" in content_type:
            # Next.js rendered an HTML error page — give a concise message
            raise TMSApiError(
                f"Received HTML error page (likely a server crash). Status: {status}",
                status_code=status,
            )

        # Try to extract a structured error message
        try:
            body = response.json()
            message = (
                body.get("error")
                or body.get("message")
                or json.dumps(body)
            )
        except Exception:
            message = response.text or f"HTTP {status}"

        raise TMSApiError(message, status_code=status)
