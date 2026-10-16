"""Receive explicit bounded MCP file blobs without business orchestration."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

import mcp.types as mt
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime

from deerflow.config.paths import get_paths
from deerflow.mcp.tool_file_storage import ToolFileError, store_files
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.sandbox.sandbox_provider import get_initialized_sandbox_provider
from deerflow.utils.file_io import run_file_io
from deerflow.utils.thread_id import validate_thread_id

PROFILE = "deerflow.tool-file/v1"
MAX_FILES = 4
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_RAW_BYTES = 32 * 1024 * 1024
_MANIFEST_KEYS = {"profile", "resource_uri", "name", "mime_type", "size_bytes", "sha256"}
_MIME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9!#$&^_.+-]*/[a-zA-Z0-9][a-zA-Z0-9!#$&^_.+-]*\Z")


def _fail(code: str) -> None:
    raise ToolFileError(code)


def _identity(runtime: object) -> tuple[str, str, str, str]:
    if not isinstance(runtime, ToolRuntime) or not isinstance(runtime.context, Mapping):
        _fail("FILE_NATIVE_RUNTIME_REQUIRED")
    context = runtime.context
    owner, thread, run, call = (context.get("user_id"), context.get("thread_id"), context.get("run_id"), runtime.tool_call_id)
    if any(not isinstance(value, str) or not value or len(value) > 255 or any(ord(char) < 32 for char in value) for value in (owner, thread, run, call)):
        _fail("FILE_NATIVE_IDENTITY_REQUIRED")
    if owner != resolve_runtime_user_id(runtime):
        _fail("FILE_OWNER_MISMATCH")
    validate_thread_id(thread)
    return owner, thread, run, call


def _files(result: mt.CallToolResult) -> list[dict[str, Any]]:
    manifest = result.structuredContent["files"]
    if result.isError or not isinstance(manifest, list) or not 1 <= len(manifest) <= MAX_FILES:
        _fail("FILE_MANIFEST_INVALID")
    if any(not isinstance(item, (mt.TextContent, mt.EmbeddedResource)) for item in result.content):
        _fail("FILE_CONTENT_SET_INVALID")
    resources = [item.resource for item in result.content if isinstance(item, mt.EmbeddedResource)]
    if len(resources) != len(manifest) or any(not isinstance(item, mt.BlobResourceContents) for item in resources):
        _fail("FILE_BLOB_SET_INVALID")
    by_uri = {str(item.uri): item for item in resources}
    if len(by_uri) != len(resources):
        _fail("FILE_DUPLICATE_RESOURCE")
    names: set[str] = set()
    used: set[str] = set()
    total = 0
    files = []
    for record in manifest:
        if not isinstance(record, dict) or set(record) != _MANIFEST_KEYS or record.get("profile") != PROFILE:
            _fail("FILE_MANIFEST_INVALID")
        name, uri, mime, size, sha = (record.get(key) for key in ("name", "resource_uri", "mime_type", "size_bytes", "sha256"))
        if not isinstance(name, str) or not name or name.startswith(".") or len(name.encode("utf-8")) > 200 or any(char in "/\\" or ord(char) < 32 or ord(char) == 127 for char in name):
            _fail("FILE_NAME_INVALID")
        if name in names or not isinstance(uri, str) or not uri.startswith("urn:") or uri in used or uri not in by_uri:
            _fail("FILE_RESOURCE_IDENTITY_INVALID")
        if not isinstance(mime, str) or not _MIME.fullmatch(mime):
            _fail("FILE_MIME_INVALID")
        if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES or not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
            _fail("FILE_SIZE_OR_DIGEST_INVALID")
        total += size
        if total > MAX_TOTAL_BYTES:
            _fail("FILE_TOTAL_LIMIT_EXCEEDED")
        blob = by_uri[uri]
        if blob.mimeType != mime or len(blob.blob) != 4 * ((size + 2) // 3):
            _fail("FILE_BLOB_METADATA_MISMATCH")
        try:
            data = base64.b64decode(blob.blob, validate=True)
        except (ValueError, binascii.Error):
            _fail("FILE_BASE64_INVALID")
        if len(data) != size or base64.b64encode(data).decode() != blob.blob or hashlib.sha256(data).hexdigest() != sha:
            _fail("FILE_BYTES_MISMATCH")
        names.add(name)
        used.add(uri)
        files.append({**record, "data": data})
    if used != set(by_uri):
        _fail("FILE_BLOB_SET_INVALID")
    return files


def _error(code: str) -> mt.CallToolResult:
    # Rejected/oversized data never reaches the model, checkpoint or trace as a
    # base64 blob. No full-original retention is claimed for rejected payloads.
    receipt = {"profile": "deerflow.tool-file-receipt/v1", "status": "error", "error_code": code, "original_retained": False, "files": []}
    return mt.CallToolResult(isError=True, content=[mt.TextContent(type="text", text=json.dumps(receipt))], structuredContent=receipt)


def _native_message(result: mt.CallToolResult, raw: dict[str, Any], receipt: dict[str, Any], request: Any, call: str) -> ToolMessage:
    content = [item.model_dump(mode="json", exclude_none=True) for item in result.content if not isinstance(item, mt.EmbeddedResource)]
    content.append({"type": "text", "text": json.dumps(receipt, ensure_ascii=False)})
    return ToolMessage(
        content=content,
        tool_call_id=call,
        name=request.name,
        status="error" if receipt["status"] == "error" else "success",
        artifact={"profile": "mcp.call-tool-result/original", "original": raw, "sha256": hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "file_receipt": receipt},
    )


def build_tool_file_interceptor() -> Any:
    async def tool_file_interceptor(request: Any, handler: Any) -> Any:
        result = await handler(request)
        if not isinstance(result, mt.CallToolResult) or not isinstance(result.structuredContent, dict) or "files" not in result.structuredContent:
            return result
        manifest = result.structuredContent["files"]
        # An unrelated business field named files is not an opt-in. A malformed
        # record attempting the explicit protocol is rejected, never half-read.
        candidates = manifest if isinstance(manifest, list) else [manifest]
        if not any(isinstance(item, dict) and str(item.get("profile", "")).startswith("deerflow.tool-file/") for item in candidates):
            return result
        accepted_raw = None
        call = None
        try:
            owner, thread, run, call = _identity(request.runtime)
            files = _files(result)
            raw = result.model_dump(mode="json")
            if len(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_RAW_BYTES:
                _fail("FILE_RAW_RESULT_LIMIT_EXCEEDED")
            accepted_raw = raw
            provider = get_initialized_sandbox_provider()
            if provider is None or not provider.uses_thread_data_mounts:
                _fail("FILE_SHARED_MOUNT_PROVIDER_REQUIRED")
            proof = await run_file_io(store_files, get_paths(), owner, thread, run, call, files)
            receipt = {"profile": "deerflow.tool-file-receipt/v1", "status": "ok", "files": proof}
            return _native_message(result, raw, receipt, request, call)
        except ToolFileError as exc:
            code = str(exc)
        except ValueError:
            code = "FILE_NATIVE_IDENTITY_INVALID"
        if accepted_raw is not None and call:
            receipt = {"profile": "deerflow.tool-file-receipt/v1", "status": "error", "error_code": code, "original_retained": True, "files": []}
            return _native_message(result, accepted_raw, receipt, request, call)
        return _error(code)

    return tool_file_interceptor
