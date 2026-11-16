"""Keep opt-in MCP discovery and its transport credentials within one verified run."""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

import httpx
from langchain_core.tools import BaseTool, ToolException

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.headers import illegal_header_value_reason
from deerflow.runtime.user_context import DEFAULT_USER_ID, get_current_user


@dataclass
class UserMcpRun:
    user_id: str
    tools: tuple[BaseTool, ...] = ()
    _token: Token[UserMcpRun | None] = field(init=False, repr=False)

    @classmethod
    def start(cls, record_user_id: str | None) -> UserMcpRun | None:
        user = get_current_user()
        if user is None or not record_user_id or record_user_id == DEFAULT_USER_ID or str(user.id) != record_user_id:
            return None
        run = cls(record_user_id)
        run._token = _current_run.set(run)
        return run

    def require_current(self) -> None:
        user = get_current_user()
        if not hasattr(self, "_token") or _current_run.get() is not self or user is None or str(user.id) != self.user_id:
            raise ToolException("Personal MCP tools require the same authenticated run.")

    def close(self) -> None:
        token = self._token
        del self._token
        self.tools = ()
        _current_run.reset(token)


_current_run: ContextVar[UserMcpRun | None] = ContextVar("deerflow_user_mcp_run", default=None)


def get_user_mcp_tools() -> tuple[BaseTool, ...]:
    run = _current_run.get()
    if run is None:
        return ()
    try:
        run.require_current()
    except ToolException:
        return ()
    return run.tools


def _credentials(server: McpServerConfig, user_id: str) -> dict[str, str]:
    auth = server.user_auth
    if not server.enabled or auth is None or not auth.discover_with_user:
        raise ToolException("Personal MCP access is no longer configured.")
    credential = auth.users.get(user_id, "")
    if not credential or illegal_header_value_reason(credential):
        raise ToolException("Personal MCP access requires a valid credential for your account.")
    headers = {**server.headers, auth.header: credential}
    if any(not value or illegal_header_value_reason(value) for value in headers.values()):
        raise ToolException("The MCP transport credential is unavailable.")
    return headers


def _binding_digest(url: str, headers: dict[str, str]) -> bytes:
    identity = json.dumps([url, sorted(headers.items())], separators=(",", ":"))
    return hashlib.sha256(identity.encode()).digest()


def user_mcp_http_client_factory(run: UserMcpRun, name: str, server: McpServerConfig) -> Any:
    """Supply credentials per request without storing them in SDK tool closures."""
    run.require_current()
    endpoint = httpx.URL(server.url)
    binding = _binding_digest(str(endpoint), _credentials(server, run.user_id))

    async def authorize(request: httpx.Request) -> None:
        run.require_current()
        if request.url != endpoint:
            raise ToolException("Personal MCP request destination changed.")
        try:
            config = ExtensionsConfig.from_file()
            if (config.model_extra or {}).get("mcpInterceptors"):
                raise ValueError("personal MCP interceptors are unavailable")
            current = config.mcp_servers[name]
        except (OSError, KeyError, ValueError):
            raise ToolException("Personal MCP access is no longer configured.") from None
        headers = _credentials(current, run.user_id)
        if not current.url or _binding_digest(str(httpx.URL(current.url)), headers) != binding:
            raise ToolException("Personal MCP binding changed. Start a new run.")
        if any(header in request.headers for header in headers):
            raise ToolException("Unexpected MCP authentication header.")
        request.headers.update(headers)

    def factory(headers: dict[str, str] | None = None, timeout: httpx.Timeout | None = None, auth: httpx.Auth | None = None) -> httpx.AsyncClient:
        run.require_current()
        if auth is not None:
            raise ToolException("Personal MCP cannot use shared HTTP authentication.")
        return httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=False, event_hooks={"request": [authorize]})

    return factory
