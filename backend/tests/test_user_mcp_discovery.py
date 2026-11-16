"""Exercise user-bound discovery with the installed MCP transports."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.tools import ToolException

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.tools import get_mcp_tools
from deerflow.mcp.user_discovery import UserMcpRun, get_user_mcp_tools
from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.utils.assembly_io import run_assembly


def config(*, users=None, **updates):
    return ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "personal": {
                    "type": "http",
                    "url": "http://mcp.invalid/mcp",
                    "headers": {"Authorization": "Bearer synthetic-gateway"},
                    "user_auth": {"header": "X-Caller", "discover_with_user": True, "users": users if users is not None else {"a": "user-a", "b": "user-b"}},
                    **updates,
                }
            },
        }
    )


class McpEndpoint:
    def __init__(self, monkeypatch):
        self.current = config()
        self.sessions = {}
        self.events = []
        self.clients = []
        self.mode = "normal"
        self.started = None
        original_client = httpx.AsyncClient

        def client(**kwargs):
            instance = original_client(transport=httpx.MockTransport(self.respond), **kwargs)
            self.clients.append(instance)
            return instance

        monkeypatch.setattr(httpx, "AsyncClient", client)
        monkeypatch.setattr(ExtensionsConfig, "from_file", classmethod(lambda cls: self.current))

    async def respond(self, request):
        assert request.url.host == "mcp.invalid"
        assert request.headers.get_list("Authorization") == ["Bearer synthetic-gateway"]
        [caller] = request.headers.get_list("X-Caller")
        assert caller in {"user-a", "user-b"}
        if self.mode == "redirect":
            return httpx.Response(307, headers={"Location": "http://forbidden.invalid/mcp"})
        if self.mode == "wait":
            self.started.set()
            await asyncio.Event().wait()
        session = request.headers.get("Mcp-Session-Id")
        if request.method in {"GET", "DELETE"}:
            assert self.sessions[session] == caller
            return httpx.Response(405 if request.method == "GET" else 200)
        rpc = json.loads(request.content)
        method = rpc["method"]
        self.events.append((caller, method, session))
        headers = {}
        if method == "initialize":
            assert session is None
            session = f"session-{len(self.sessions) + 1}"
            self.sessions[session] = caller
            headers["Mcp-Session-Id"] = session
            result = {"protocolVersion": rpc["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "test", "version": "1"}}
        else:
            assert self.sessions[session] == caller
            if method == "notifications/initialized":
                return httpx.Response(202)
            if method == "tools/list":
                page_two = (rpc.get("params") or {}).get("cursor") == "next"
                name = f"{'detail' if page_two else 'lookup'}_{caller[-1]}"
                result = {"tools": [{"name": name, "description": "Synthetic", "inputSchema": {"type": "object", "properties": {}}}]}
                if not page_two:
                    result["nextCursor"] = "next"
            else:
                assert method == "tools/call"
                assert rpc["params"]["name"].endswith(caller[-1])
                result = {"content": [{"type": "text", "text": caller}], "isError": False}
        return httpx.Response(200, headers=headers, json={"jsonrpc": "2.0", "id": rpc["id"], "result": result})


def test_private_tools_never_load_into_global_catalog_and_keep_concurrent_users_separate(monkeypatch):
    endpoint = McpEndpoint(monkeypatch)

    async def run(user):
        token = set_current_user(SimpleNamespace(id=user))
        scope = UserMcpRun.start(user)
        try:
            scope.tools = tuple(await get_mcp_tools(user_run=scope))
            tools = await run_assembly(get_user_mcp_tools)
            assert [t.name for t in tools] == [f"personal_lookup_{user}", f"personal_detail_{user}"]
            result = await tools[0].ainvoke({})
            assert [block["text"] for block in result] == [f"user-{user}"]
        finally:
            scope.close()
            reset_current_user(token)
        assert get_user_mcp_tools() == ()

    async def scenario():
        assert await get_mcp_tools() == []
        assert endpoint.events == []
        await asyncio.gather(run("a"), run("b"))
        await run("a")

    asyncio.run(scenario())
    assert len(endpoint.sessions) >= 6
    assert sum(method == "tools/call" for _, method, _ in endpoint.events) == 3
    assert all(client.is_closed for client in endpoint.clients)


def test_stale_run_and_revocation_refuse_before_new_requests(monkeypatch):
    endpoint = McpEndpoint(monkeypatch)

    async def scenario():
        token = set_current_user(SimpleNamespace(id="a"))
        first = UserMcpRun.start("a")
        try:
            [tool, _] = await get_mcp_tools(user_run=first)
            endpoint.current = config(users={})
            count = len(endpoint.events)
            with pytest.raises((ExceptionGroup, ToolException)):
                await tool.ainvoke({})
            assert len(endpoint.events) == count
        finally:
            first.close()
            reset_current_user(token)

        for user in ("a", "b"):
            token = set_current_user(SimpleNamespace(id=user))
            second = UserMcpRun.start(user)
            try:
                endpoint.current = config()
                with pytest.raises((ExceptionGroup, ToolException)):
                    await tool.ainvoke({})
                assert len(endpoint.events) == count
            finally:
                second.close()
                reset_current_user(token)

    asyncio.run(scenario())
    assert all(client.is_closed for client in endpoint.clients)


def test_redirect_timeout_and_cancellation_clean_up_the_sdk_transport(monkeypatch):
    endpoint = McpEndpoint(monkeypatch)

    async def scenario():
        token = set_current_user(SimpleNamespace(id="a"))
        scope = UserMcpRun.start("a")
        try:
            endpoint.mode = "redirect"
            assert await get_mcp_tools(user_run=scope) == []
            endpoint.mode = "wait"
            endpoint.started = asyncio.Event()
            endpoint.current = config(session_init_timeout=0.03)
            assert await get_mcp_tools(user_run=scope) == []
            assert endpoint.started.is_set()
            endpoint.started.clear()
            endpoint.current = config()
            task = asyncio.create_task(get_mcp_tools(user_run=scope))
            await endpoint.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            endpoint.mode = "normal"
            assert len(await get_mcp_tools(user_run=scope)) == 2
        finally:
            scope.close()
            reset_current_user(token)

    asyncio.run(scenario())
    assert all(client.is_closed for client in endpoint.clients)


def test_session_needs_verified_matching_user():
    assert UserMcpRun.start("a") is None
    token = set_current_user(SimpleNamespace(id="a"))
    try:
        assert UserMcpRun.start("b") is None
        assert UserMcpRun.start("default") is None
    finally:
        reset_current_user(token)


@pytest.mark.parametrize(
    "override",
    [
        {"type": "sse"},
        {"url": "https://name:password@example.invalid/mcp"},
        {"headers": {"X-Caller": "another-user"}},
        {"session_init_timeout": None},
        {"user_auth": {"discover_with_user": True, "on_missing": "passthrough"}},
    ],
)
def test_unreviewed_transport_combinations_are_rejected(override):
    with pytest.raises(ValueError):
        config(**override)
