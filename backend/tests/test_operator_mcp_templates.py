"""Approved templates reuse personal MCP storage without inheriting source authority."""

import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from app.gateway.routers import capabilities, personal_mcp
from deerflow.config.paths import Paths
from deerflow.mcp.user_config import load_user_mcp_config, read_user_mcp_config


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr("deerflow.mcp.user_config.get_paths", lambda: Paths(base_dir=tmp_path))
    bridge = tmp_path / "bridge.json"
    bridge.write_text(json.dumps({"Authorization": "Bearer bridge-only"}))
    template = {
        "id": "test-source",
        "url": "http://approved.svc/mcp",
        "service_headers_file": str(bridge),
        "credential_headers": {"username": "X-Source-Username", "password": "X-Source-Password"},
        "required": ["username", "password"],
        "manifest": {
            "id": "test-source",
            "version": "1",
            "name": {"en-US": "Test source"},
            "description": {"en-US": "Personal source"},
            "setup": {"en-US": "Connect your account"},
            "category": "business",
            "kind": "mcp",
            "adapter": "template",
            "source": "https://example.com/docs",
            "config_schema": {"type": "object", "properties": {"username": {"type": "string"}, "password": {"type": "string", "format": "password"}}, "required": ["username", "password"]},
        },
    }
    path = tmp_path / "templates.json"
    path.write_text(json.dumps([template]))
    monkeypatch.setenv("DEER_FLOW_PERSONAL_MCP_TEMPLATES", str(path))
    platform = tmp_path / "platform.json"
    platform.write_text('{"mcpServers": {}}')
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(platform))
    app = FastAPI()
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()

    @app.middleware("http")
    async def identity(request, call_next):
        if user := request.headers.get("test-user"):
            request.state.user = SimpleNamespace(id=user, system_role="user")
            request.state.auth_source = "session"
        return await call_next(request)

    app.include_router(capabilities.router)
    app.include_router(personal_mcp.router)
    with TestClient(app) as client:
        yield client, path, template


def connect(client, user, **configuration):
    return client.post(
        "/api/capabilities/installations", headers={"test-user": user}, json={"plugin_id": "test-source", "name": "test-source", "scope": "user", "configuration": configuration or {"username": user, "password": user + "-password"}}
    )


def test_ordinary_user_configures_only_own_connection(setup):
    client, _, _ = setup
    for owner in ("alice", "bob"):
        response = connect(client, owner)
        assert response.status_code == 200, response.text
        assert owner + "-password" not in response.text
        stored = read_user_mcp_config(owner)["mcpServers"]["test-source"]
        assert "bridge-only" not in json.dumps(stored)
        assert base64.b64decode(stored["headers"]["X-Source-Username"]).decode() == owner
        runtime = next(iter(load_user_mcp_config(owner).mcp_servers.values()))
        assert runtime.headers["Authorization"] == "Bearer bridge-only"
        assert runtime.headers["X-Genesis-Connection-Owner"] == owner
    assert set(load_user_mcp_config("alice").mcp_servers).isdisjoint(load_user_mcp_config("bob").mcp_servers)
    assert not load_user_mcp_config("charlie").mcp_servers
    masked = client.get("/api/mcp/personal/config", headers={"test-user": "alice"}).json()
    assert set(masked["mcp_servers"]["test-source"]["headers"].values()) == {"***"}


@pytest.mark.parametrize("overrides", [{"url": "http://evil.svc"}, {"headers": {"Authorization": "forged"}}, {"user_id": "bob"}, {"username": "a"}, {"username": "a", "password": ""}])
def test_invalid_fields_do_not_write_or_contact_other_endpoints(setup, overrides):
    client, _, _ = setup
    response = connect(client, "alice", **overrides)
    assert response.status_code == 422, response.text
    assert not read_user_mcp_config("alice")["mcpServers"]


def test_personal_selection_never_chooses_shared_or_another_owner(setup):
    from langchain_core.tools import StructuredTool

    from deerflow.capabilities.runtime import filter_mcp_plugins
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    client, _, _ = setup
    connect(client, "alice")
    config = load_user_mcp_config("alice")
    name = next(iter(config.mcp_servers))
    tool = StructuredTool.from_function(lambda: "ok", name="test", description="test")
    tag_mcp_tool(tool, server_name=name)
    assert filter_mcp_plugins([tool], ["template:test-source"], config) == [tool]
    assert filter_mcp_plugins([tool], ["template:missing"], config) == []
    assert filter_mcp_plugins([tool], ["template:test-source"], load_user_mcp_config("bob")) == []


def test_template_removed_or_endpoint_modified_revokes_saved_connection(setup):
    client, path, template = setup
    assert connect(client, "alice").status_code == 200
    before = load_user_mcp_config("alice")
    template["url"] = "http://replacement.svc/mcp"
    path.write_text(json.dumps([template]))
    with pytest.raises(ValueError):
        load_user_mcp_config("alice")
    path.write_text("[]")
    with pytest.raises(ValueError):
        load_user_mcp_config("alice")
    assert before.mcp_servers


def test_update_preserves_connection_id_but_revokes_previous_runtime(setup):
    client, _, _ = setup
    assert connect(client, "alice").status_code == 200
    before = read_user_mcp_config("alice")["mcpServers"]["test-source"]
    old_runtime = set(load_user_mcp_config("alice").mcp_servers)
    response = connect(client, "alice", username="alice", password="replacement")
    assert response.status_code == 200, response.text
    after = read_user_mcp_config("alice")["mcpServers"]["test-source"]
    assert after["capability"]["id"] == before["capability"]["id"]
    assert old_runtime.isdisjoint(load_user_mcp_config("alice").mcp_servers)
    assert client.delete("/api/mcp/personal/config/servers/test-source", headers={"test-user": "alice"}).status_code == 200
    assert not load_user_mcp_config("alice").mcp_servers


@pytest.mark.parametrize(
    "change",
    [
        {"url": "http://other.svc/mcp"},
        {"command": "sh"},
        {"headers_from_context": {"enabled": True}},
        {"personal_public_network": True},
        {"headers": {"Authorization": "forged"}},
    ],
)
def test_raw_personal_api_cannot_change_template_transport(setup, change):
    client, _, _ = setup
    assert connect(client, "alice").status_code == 200
    before = read_user_mcp_config("alice")
    raw = {**before["mcpServers"]["test-source"], **change}
    response = client.put("/api/mcp/personal/config/server", headers={"test-user": "alice"}, json={"server_name": "test-source", "server": raw})
    assert response.status_code in (400, 422), response.text
    assert read_user_mcp_config("alice") == before


def test_bridge_rotation_changes_runtime_identity_without_copying_secret(setup):
    client, _, template = setup
    assert connect(client, "alice").status_code == 200
    old = set(load_user_mcp_config("alice").mcp_servers)
    from pathlib import Path

    Path(template["service_headers_file"]).write_text(json.dumps({"Authorization": "Bearer rotated-bridge"}))
    assert old.isdisjoint(load_user_mcp_config("alice").mcp_servers)
    assert "rotated-bridge" not in json.dumps(read_user_mcp_config("alice"))


def test_template_change_invalidates_cached_config_even_without_personal_file_change(setup):
    from deerflow.mcp.user_config import load_user_mcp_config_if_changed

    client, path, _ = setup
    assert connect(client, "alice").status_code == 200
    cached = load_user_mcp_config_if_changed("alice")
    path.write_text("[]")
    with pytest.raises(ValueError):
        load_user_mcp_config_if_changed("alice", cached)
