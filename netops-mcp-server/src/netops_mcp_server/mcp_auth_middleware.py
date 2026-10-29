"""
MCP HTTP auth middleware for inbound client requests.
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastmcp.exceptions import AuthorizationError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext


class McpApiTokenMiddleware(Middleware):
    """Require Bearer token auth for inbound HTTP MCP requests when configured."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def on_request(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> object:
        request = None
        try:
            request = get_http_request()
        except Exception:
            # Non-HTTP transports are unsupported in this deployment mode.
            request = None

        if request is None:
            raise AuthorizationError("MCP API token auth requires HTTP transport requests")

        authz: Optional[str] = request.headers.get("authorization")
        if not authz or not authz.startswith("Bearer "):
            raise AuthorizationError("Missing bearer token")

        presented = authz[7:].strip()
        if not presented or not hmac.compare_digest(presented, self._token):
            raise AuthorizationError("Invalid bearer token")

        return await call_next(context)
