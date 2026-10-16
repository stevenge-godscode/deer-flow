"""Real native file reception must offload storage and readback."""

import base64
import hashlib
from types import SimpleNamespace

import mcp.types as mt
import pytest
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langgraph.prebuilt.tool_node import ToolRuntime

from deerflow.config.paths import Paths
from deerflow.mcp import tool_files
from deerflow.utils.file_io import run_file_io


@pytest.mark.asyncio
async def test_native_mcp_file_receive_and_readback_do_not_block(tmp_path, monkeypatch):
    paths = await run_file_io(Paths, base_dir=tmp_path)
    monkeypatch.setattr(tool_files, "get_paths", lambda: paths)
    monkeypatch.setattr(tool_files, "get_initialized_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=True))
    data = b"synthetic exact output"
    sha = hashlib.sha256(data).hexdigest()
    uri = "urn:synthetic:" + sha
    manifest = {"profile": "deerflow.tool-file/v1", "resource_uri": uri, "name": "file.txt", "mime_type": "text/plain", "size_bytes": len(data), "sha256": sha}
    raw = mt.CallToolResult(
        content=[mt.TextContent(type="text", text="ready"), mt.EmbeddedResource(type="resource", resource=mt.BlobResourceContents(uri=uri, mimeType="text/plain", blob=base64.b64encode(data).decode()))],
        structuredContent={"files": [manifest]},
    )
    runtime = ToolRuntime(state={}, context={"user_id": "owner", "thread_id": "thread", "run_id": "run"}, config={}, stream_writer=lambda _: None, tool_call_id="call", store=None)

    async def handler(_):
        return raw

    reply = await tool_files.build_tool_file_interceptor()(MCPToolCallRequest(name="export", args={}, server_name="synthetic", runtime=runtime), handler)
    assert isinstance(reply, ToolMessage)
    proof = reply.artifact["file_receipt"]["files"][0]

    def readback():
        return paths.resolve_virtual_path("thread", proof["path"], user_id="owner").read_bytes()

    assert await run_file_io(readback) == data
