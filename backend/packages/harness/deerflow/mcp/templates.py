"""Operator-approved connection forms over the existing personal MCP store.

Templates own transport and bridge authentication. Users supply only declared
credential fields. No second credential store or provider-specific code lives here.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from deerflow.config.extensions_config import McpServerConfig


class ConnectionTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,127}$")
    url: str
    manifest: dict[str, Any]
    credential_headers: dict[str, str]
    required: list[str]
    service_headers_file: str
    server: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        from deerflow.capabilities.catalog import PluginManifest

        manifest = PluginManifest.model_validate(self.manifest)
        if manifest.id != self.id or manifest.adapter != "template":
            raise ValueError("Template manifest identity mismatch")
        url = urlsplit(self.url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("Invalid template endpoint")
        names = list(self.credential_headers.values())
        if len({x.lower() for x in names}) != len(names) or any(not x.lower().startswith("x-") or not x.replace("-", "").isalnum() for x in names):
            raise ValueError("Invalid credential header names")
        if "x-genesis-connection-owner" in {x.lower() for x in names}:
            raise ValueError("Reserved connection owner header")
        if not self.required or not set(self.required) <= self.credential_headers.keys():
            raise ValueError("Invalid required credential fields")
        if set(self.server) & {"type", "url", "headers", "capability", "personal_template", "personal_public_network", "user_auth", "oauth", "headers_from_context"}:
            raise ValueError("Template transport fields must use their dedicated settings")
        return self


def load_templates() -> dict[str, ConnectionTemplate]:
    path = os.environ.get("DEER_FLOW_PERSONAL_MCP_TEMPLATES")
    if not path:
        return {}
    entries = [ConnectionTemplate.model_validate(item) for item in json.loads(Path(path).read_text(encoding="utf-8"))]
    result = {item.id: item for item in entries}
    if len(result) != len(entries):
        raise ValueError("Duplicate personal connection template")
    return result


def template_id(server: dict | McpServerConfig) -> str | None:
    raw = server if isinstance(server, dict) else server.model_dump()
    value = raw.get("personal_template")
    return value if isinstance(value, str) else None


def _template(identity: str) -> ConnectionTemplate:
    template = load_templates().get(identity)
    if template is None:
        raise ValueError("This personal connection template is unavailable")
    return template


def connection_definition(identity: str, credentials: dict[str, Any]) -> dict:
    template = _template(identity)
    if not set(credentials) <= template.credential_headers.keys():
        raise ValueError("Only the displayed credential fields may be configured")
    headers = {}
    for field, header in template.credential_headers.items():
        value = credentials.get(field, "")
        if not isinstance(value, str) or len(value.encode("utf-8")) > 2048 or value == "***":
            raise ValueError("Invalid personal credential value")
        if field in template.required and not value:
            raise ValueError("Complete the required account fields")
        if value:
            headers[header] = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return {**template.server, "enabled": True, "type": "http", "url": template.url, "headers": headers, "personal_template": identity, "personal_public_network": False}


def validate_definition(raw: dict, *, materialized: bool = False) -> ConnectionTemplate:
    identity = template_id(raw)
    template = _template(identity or "")
    headers = raw.get("headers") or {}
    allowed = set(template.credential_headers.values())
    owner = None
    bridge = {}
    if materialized:
        bridge = _bridge_headers(template)
        allowed |= set(bridge) | {"X-Genesis-Connection-Owner"}
        owner = headers.get("X-Genesis-Connection-Owner")
        if not isinstance(owner, str) or not owner:
            raise ValueError("Personal connection owner is missing")
        if any(headers.get(key) != value for key, value in bridge.items()):
            raise ValueError("Bridge credentials have changed")
    if not isinstance(headers, dict) or not set(headers) <= allowed:
        raise ValueError("Only template credential headers are allowed")
    values = {}
    for field, header in template.credential_headers.items():
        value = headers.get(header, "")
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8") if value else ""
        except (ValueError, UnicodeError):
            raise ValueError("Invalid encoded personal credential") from None
        values[field] = decoded
    expected = connection_definition(template.id, values)
    # Normalize all schema defaults; callers cannot add commands, OAuth flows,
    # alternate URLs, context-header mappings or user_auth bypasses to a template.
    actual = McpServerConfig.model_validate(raw).model_dump()
    canonical = McpServerConfig.model_validate(expected).model_dump()
    for key in ("enabled", "description", "capability", "presentation", "tool_name_prefix"):
        actual.pop(key, None)
        canonical.pop(key, None)
    if materialized:
        canonical["headers"].update(bridge)
        canonical["headers"]["X-Genesis-Connection-Owner"] = owner
    if actual != canonical:
        raise ValueError("The approved connection transport has changed; reconnect using its form")
    return template


def _bridge_headers(template: ConnectionTemplate) -> dict[str, str]:
    headers = json.loads(Path(template.service_headers_file).read_text(encoding="utf-8"))
    reserved = {x.lower() for x in template.credential_headers.values()} | {"x-genesis-connection-owner"}
    if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v or k.lower() in reserved for k, v in headers.items()):
        raise ValueError("Invalid bridge authentication configuration")
    return headers


def materialize(raw: dict, owner: str) -> dict:
    template = validate_definition(raw)
    return {**raw, "headers": {**raw["headers"], **_bridge_headers(template), "X-Genesis-Connection-Owner": owner}}


def template_httpx_client_factory(headers=None, timeout=None, auth=None):
    """Keep credentials on the approved endpoint; redirects never inherit them."""
    import httpx

    options = {"headers": headers, "auth": auth, "follow_redirects": False, "trust_env": False}
    if timeout is not None:
        options["timeout"] = timeout
    return httpx.AsyncClient(**options)
