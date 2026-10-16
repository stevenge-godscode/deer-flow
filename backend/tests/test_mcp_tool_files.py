"""Transport-independent file ingress must prove bytes and owner confinement."""

import base64
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import mcp.types as mt
import pytest
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langgraph.prebuilt.tool_node import ToolRuntime

from deerflow.config.paths import Paths
from deerflow.mcp.tool_file_storage import ToolFileError, store_files
from deerflow.mcp.tool_files import build_tool_file_interceptor


def result(data=b"name,value\nexample,42\n", name="report.csv"):
    digest = hashlib.sha256(data).hexdigest()
    manifest = {"profile": "deerflow.tool-file/v1", "resource_uri": "urn:export:" + digest, "name": name, "mime_type": "text/csv", "size_bytes": len(data), "sha256": digest}
    return mt.CallToolResult(
        content=[mt.TextContent(type="text", text='{"status":"ok"}'), mt.EmbeddedResource(type="resource", resource=mt.BlobResourceContents(uri=manifest["resource_uri"], mimeType="text/csv", blob=base64.b64encode(data).decode()))],
        structuredContent={"status": "ok", "files": [manifest]},
    )


def runtime(**context):
    return ToolRuntime(state={}, context={"user_id": "alice", "thread_id": "thread-1", "run_id": "run-1", **context}, config={}, stream_writer=lambda _: None, tool_call_id="call-1", store=None)


@pytest.fixture
def environment(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("deerflow.mcp.tool_files.get_paths", return_value=paths), patch("deerflow.mcp.tool_files.get_initialized_sandbox_provider", return_value=SimpleNamespace(uses_thread_data_mounts=True)):
        yield paths


async def receive(raw, rt=None):
    request = MCPToolCallRequest(name="export", args={}, server_name="arbitrary", runtime=rt)

    async def handler(_):
        return raw

    return await build_tool_file_interceptor()(request, handler)


@pytest.mark.asyncio
async def test_sealed_text_raw_artifact_and_verified_output(environment):
    raw = result()
    reply = await receive(raw, runtime())
    assert isinstance(reply, ToolMessage)
    assert reply.content[0]["text"] == raw.content[0].text
    receipt = json.loads(reply.content[-1]["text"])
    proof = receipt["files"][0]
    assert receipt["profile"] == "deerflow.tool-file-receipt/v1"
    assert proof["readback_verified"] is True
    actual = environment.resolve_virtual_path("thread-1", proof["path"], user_id="alice")
    assert actual.read_bytes() == b"name,value\nexample,42\n"
    assert proof["sha256"] == hashlib.sha256(actual.read_bytes()).hexdigest()
    assert reply.artifact["original"] == raw.model_dump(mode="json")
    assert base64.b64encode(actual.read_bytes()).decode() not in str(reply.content)
    assert ToolMessage.model_validate_json(reply.model_dump_json()).artifact == reply.artifact
    from langchain_mcp_adapters.tools import _convert_call_tool_result as adapter_convert

    from deerflow.mcp.tools import _convert_call_tool_result as native_convert

    assert native_convert(reply)[0] is reply
    assert adapter_convert(reply)[0] is reply
    again = await receive(raw, runtime())
    assert again.content == reply.content
    other = await receive(raw, runtime(run_id="run-2"))
    assert json.loads(other.content[-1]["text"])["files"][0]["path"] != proof["path"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rt", [None, SimpleNamespace(context={"user_id": "alice", "thread_id": "thread-1", "run_id": "run-1"}, tool_call_id="call-1"), runtime(user_id=""), runtime(thread_id=""), runtime(run_id=""), runtime(thread_id="../foreign")]
)
async def test_explicit_native_identity_is_required(environment, rt):
    reply = await receive(result(), rt)
    assert reply.isError is True
    assert not list(environment.base_dir.rglob("report.csv"))
    assert "blob" not in reply.model_dump_json()


@pytest.mark.asyncio
async def test_foreign_authoritative_owner_cannot_use_context_owner(environment):
    rt = runtime()
    rt.server_info = SimpleNamespace(user=SimpleNamespace(identity="bob"))
    reply = await receive(result(), rt)
    assert getattr(reply, "isError", False) or getattr(reply, "status", None) == "error"
    assert not list(environment.base_dir.rglob("report.csv"))


@pytest.mark.asyncio
async def test_unsupported_provider_never_writes_or_acquires(environment):
    provider = SimpleNamespace(uses_thread_data_mounts=False)
    with patch("deerflow.mcp.tool_files.get_initialized_sandbox_provider", return_value=provider):
        reply = await receive(result(), runtime())
    assert getattr(reply, "isError", False) or getattr(reply, "status", None) == "error"
    assert not list(environment.base_dir.rglob("report.csv"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "../stolen.csv"),
        ("name", ".stage-hidden"),
        ("name", "a\\b.csv"),
        ("name", "a\n.csv"),
        ("name", "a\x00.csv"),
        ("mime_type", "text/html"),
        ("size_bytes", True),
        ("size_bytes", 1),
        ("sha256", "0" * 64),
        ("resource_uri", "https://example.test/file"),
        ("profile", "deerflow.tool-file/v2"),
    ],
)
async def test_manifest_mismatch_never_persists(environment, field, value):
    raw = result()
    raw.structuredContent["files"][0][field] = value
    reply = await receive(raw, runtime())
    assert getattr(reply, "isError", False) or getattr(reply, "status", None) == "error"
    assert not list(environment.base_dir.rglob("report.csv"))
    assert "blob" not in reply.model_dump_json()


@pytest.mark.asyncio
async def test_all_files_are_validated_before_any_write(environment):
    raw = result()
    raw.structuredContent["files"].append(deepcopy(raw.structuredContent["files"][0]))
    reply = await receive(raw, runtime())
    assert getattr(reply, "isError", False) or getattr(reply, "status", None) == "error"
    assert not list(environment.base_dir.rglob("report.csv"))
    raw = result()
    raw.content[-1].resource.blob = "%%%"
    assert (await receive(raw, runtime())).isError
    raw = result()
    raw.content.append(deepcopy(raw.content[-1]))
    assert (await receive(raw, runtime())).isError
    raw = result()
    raw.structuredContent["files"][0]["size_bytes"] = 8 * 1024 * 1024 + 1
    assert (await receive(raw, runtime())).isError


@pytest.mark.asyncio
async def test_ordinary_results_and_short_circuit_messages_passthrough(environment):
    ordinary = mt.CallToolResult(content=[mt.TextContent(type="text", text="ordinary")])
    assert await receive(ordinary, None) is ordinary
    message = ToolMessage(content="intercepted", tool_call_id="call-1")
    assert await receive(message, runtime()) is message
    error = result()
    error.isError = True
    assert (await receive(error, runtime())).isError
    assert not list(environment.base_dir.rglob("report.csv"))


def file_tuple(data=b"a", name="report.csv"):
    return {"name": name, "mime_type": "text/csv", "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "data": data}


def test_storage_no_overwrite_symlink_or_cross_owner(tmp_path):
    paths = Paths(base_dir=tmp_path)
    first = store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])[0]
    actual = paths.resolve_virtual_path("thread-1", first["path"], user_id="alice")
    with pytest.raises(ToolFileError):
        store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple(b"changed")])
    assert actual.read_bytes() == b"a"
    actual.unlink()
    secret = tmp_path / "secret"
    secret.write_bytes(b"a")
    actual.symlink_to(secret)
    with pytest.raises(ToolFileError):
        store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])
    assert secret.read_bytes() == b"a"
    bob = store_files(paths, "bob", "thread-1", "run-1", "call-1", [file_tuple(b"b")])[0]
    assert paths.resolve_virtual_path("thread-1", bob["path"], user_id="bob").read_bytes() == b"b"


def test_symlink_ancestor_and_hardlink_are_rejected(tmp_path):
    import os

    paths = Paths(base_dir=tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (tmp_path / "users").symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ToolFileError):
        store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])
    assert list(foreign.iterdir()) == []
    (tmp_path / "users").unlink()
    proof = store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])[0]
    actual = paths.resolve_virtual_path("thread-1", proof["path"], user_id="alice")
    os.link(actual, foreign / "link")
    with pytest.raises(ToolFileError):
        store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])


def test_link_commit_crash_recovers_only_matching_owned_stage(tmp_path):
    import os

    paths = Paths(base_dir=tmp_path)
    real_unlink = os.unlink
    crashed = False

    def crash_once(name, *args, **kwargs):
        nonlocal crashed
        if str(name).startswith(".stage-") and not crashed:
            crashed = True
            raise OSError("simulated commit cleanup interruption")
        return real_unlink(name, *args, **kwargs)

    with patch("deerflow.mcp.tool_file_storage.os.unlink", side_effect=crash_once), pytest.raises(ToolFileError):
        store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])
    proof = store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])[0]
    actual = paths.resolve_virtual_path("thread-1", proof["path"], user_id="alice")
    assert actual.read_bytes() == b"a" and actual.stat().st_nlink == 1
    assert not list(actual.parent.glob(".stage-*"))


def test_partial_private_stage_recovers_after_writer_crash(tmp_path):
    import os

    paths = Paths(base_dir=tmp_path)
    real_write = os.write
    attempted = False

    def partial_then_fail(fd, data):
        nonlocal attempted
        if not attempted:
            attempted = True
            real_write(fd, data[:1])
        raise OSError("writer interrupted")

    with patch("deerflow.mcp.tool_file_storage.os.write", side_effect=partial_then_fail), pytest.raises(ToolFileError):
        store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple(b"complete bytes")])
    stage = list(paths.thread_dir("thread-1", user_id="alice").glob(".mcp-file-staging/*/.stage-*"))
    assert len(stage) == 1
    assert "user-data" not in stage[0].relative_to(paths.thread_dir("thread-1", user_id="alice")).parts
    proof = store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple(b"complete bytes")])[0]
    assert paths.resolve_virtual_path("thread-1", proof["path"], user_id="alice").read_bytes() == b"complete bytes"


def test_private_call_lock_is_nonblocking_and_never_replaced(tmp_path):
    import fcntl
    import os

    paths = Paths(base_dir=tmp_path)
    store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])
    lock = next(paths.thread_dir("thread-1", user_id="alice").glob(".mcp-file-staging/*/.lock"))
    before = lock.stat().st_ino
    with lock.open("r+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ToolFileError, match="FILE_CALL_BUSY"):
            store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])
    assert os.stat(lock).st_ino == before
    assert store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])[0]["readback_verified"]


@pytest.mark.asyncio
async def test_shared_builder_receives_before_custom_projection(environment):
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.interceptors import build_mcp_tool_interceptors, compose_tool_interceptors

    seen = []

    async def projection(request, handler):
        reply = await handler(request)
        seen.append(isinstance(reply, ToolMessage))
        return reply

    config = ExtensionsConfig.model_validate({"mcpInterceptors": ["custom.projection:builder"]})
    interceptors = build_mcp_tool_interceptors(config, resolver=lambda _: lambda: projection)

    async def transport(_):
        return result()

    reply = await compose_tool_interceptors(interceptors, transport)(MCPToolCallRequest(name="export", args={}, server_name="arbitrary", runtime=runtime()))
    assert isinstance(reply, ToolMessage) and seen == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse", "stdio"])
async def test_real_adapter_toolnode_preserves_file_message_and_native_runtime(environment, transport):
    from contextlib import asynccontextmanager
    from typing import Annotated, TypedDict
    from unittest.mock import AsyncMock

    from langchain_core.messages import AIMessage
    from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode

    raw = result()
    session = SimpleNamespace(call_tool=AsyncMock(return_value=raw), initialize=AsyncMock())

    @asynccontextmanager
    async def create_session(*args, **kwargs):
        yield session

    spec = mt.Tool(name="export", description="synthetic file", inputSchema={"type": "object", "properties": {}})
    connection = {"transport": transport, "url": "https://unused.invalid/mcp"}
    tool = convert_mcp_tool_to_langchain_tool(session if transport == "stdio" else None, spec, connection=None if transport == "stdio" else connection, server_name="arbitrary", tool_interceptors=[build_tool_file_interceptor()])

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    graph = StateGraph(State, context_schema=dict)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    call = {"name": "export", "args": {}, "id": "call-real-" + transport, "type": "tool_call"}
    with patch("langchain_mcp_adapters.tools.create_session", create_session):
        output = await graph.compile().ainvoke({"messages": [AIMessage(content="", tool_calls=[call])]}, context={"user_id": "alice", "thread_id": "thread-1", "run_id": "run-real"})
    reply = output["messages"][-1]
    assert isinstance(reply, ToolMessage)
    assert reply.tool_call_id == call["id"]
    assert reply.artifact["original"] == raw.model_dump(mode="json")
    proof = json.loads(reply.content[-1]["text"])["files"][0]
    assert environment.resolve_virtual_path("thread-1", proof["path"], user_id="alice").read_bytes() == b"name,value\nexample,42\n"


@pytest.mark.asyncio
async def test_explicit_protocol_wrong_manifest_container_never_leaks_blob(environment):
    from langchain_mcp_adapters.tools import _convert_call_tool_result

    raw = result()
    raw.structuredContent["files"] = raw.structuredContent["files"][0]
    reply = await receive(raw, runtime())
    assert reply.isError
    from langchain_core.tools import ToolException

    with pytest.raises(ToolException) as caught:
        _convert_call_tool_result(reply)
    assert base64.b64encode(b"name,value\nexample,42\n").decode() not in str(caught.value)
    assert not list(environment.base_dir.rglob("report.csv"))


@pytest.mark.asyncio
async def test_missing_initialized_provider_has_no_storage_side_effect(environment):
    with patch("deerflow.mcp.tool_files.get_initialized_sandbox_provider", return_value=None):
        reply = await receive(result(), runtime())
    assert getattr(reply, "isError", False) or getattr(reply, "status", None) == "error"
    assert not list(environment.base_dir.rglob("report.csv"))


@pytest.mark.asyncio
async def test_valid_export_storage_failure_retains_bounded_original(environment):
    first = result(b"original")
    assert isinstance(await receive(first, runtime()), ToolMessage)
    changed = result(b"different valid bytes")
    reply = await receive(changed, runtime())
    assert isinstance(reply, ToolMessage) and reply.status == "error"
    receipt = reply.artifact["file_receipt"]
    assert receipt["status"] == "error" and receipt["original_retained"] is True and receipt["files"] == []
    assert reply.artifact["original"] == changed.model_dump(mode="json")
    assert base64.b64encode(b"different valid bytes").decode() not in str(reply.content)
    actual = next(environment.base_dir.rglob("report.csv"))
    assert actual.read_bytes() == b"original"
    assert ToolMessage.model_validate_json(reply.model_dump_json()).artifact == reply.artifact


def test_each_new_ancestor_directory_is_fsynced_in_its_parent(tmp_path):
    import os

    paths = Paths(base_dir=tmp_path)
    mkdir, fsync = os.mkdir, os.fsync
    events = []

    def create(name, *args, **kwargs):
        mkdir(name, *args, **kwargs)
        events.append(("mkdir", kwargs["dir_fd"]))

    def sync(fd):
        fsync(fd)
        events.append(("fsync", fd))

    with patch("deerflow.mcp.tool_file_storage.os.mkdir", side_effect=create), patch("deerflow.mcp.tool_file_storage.os.fsync", side_effect=sync):
        assert store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])[0]["readback_verified"]
    created = [index for index, event in enumerate(events) if event[0] == "mkdir"]
    assert len(created) >= 8
    for index in created:
        assert events[index + 1] == ("fsync", events[index][1])


def test_retry_fsyncs_ancestor_left_after_mkdir_interruption(tmp_path):
    import os

    paths = Paths(base_dir=tmp_path)
    sync = os.fsync

    def fail_first_parent(fd):
        raise OSError("interrupted before parent fsync")

    with patch("deerflow.mcp.tool_file_storage.os.fsync", side_effect=fail_first_parent), pytest.raises(ToolFileError):
        store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])
    assert (tmp_path / "users").is_dir()
    parents = []

    def record(fd):
        parents.append(os.fstat(fd).st_ino)
        return sync(fd)

    with patch("deerflow.mcp.tool_file_storage.os.fsync", side_effect=record):
        assert store_files(paths, "alice", "thread-1", "run-1", "call-1", [file_tuple()])[0]["readback_verified"]
    assert tmp_path.stat().st_ino in parents
