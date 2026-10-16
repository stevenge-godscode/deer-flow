"""Descriptor-confined, no-overwrite MCP file storage in native thread outputs."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from deerflow.config.paths import Paths


class ToolFileError(ValueError):
    """A technical file receipt could not be proven."""


def _open_directory(parent: int, name: str, mode: int) -> int:
    try:
        os.mkdir(name, mode, dir_fd=parent)
    except FileExistsError:
        pass
    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        # An existing entry may be left by an interrupted mkdir-before-fsync.
        # Sync every opened parent so a successful retry closes that window.
        os.fsync(parent)
    except BaseException:
        os.close(child)
        raise
    return child


def _walk(base: int, parts: tuple[str, ...], mode: int, handles: list[int]) -> int:
    current = base
    for part in parts:
        current = _open_directory(current, part, mode)
        handles.append(current)
    return current


def _read(directory: int, name: str, expected: dict[str, Any]) -> os.stat_result:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected["size_bytes"]:
            raise ToolFileError("FILE_READBACK_MISMATCH")
        digest = hashlib.sha256()
        remaining = expected["size_bytes"]
        while remaining:
            block = os.read(fd, min(remaining, 1024 * 1024))
            if not block:
                raise ToolFileError("FILE_READBACK_MISMATCH")
            digest.update(block)
            remaining -= len(block)
        after = os.fstat(fd)
        if os.read(fd, 1) or digest.hexdigest() != expected["sha256"] or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ToolFileError("FILE_READBACK_MISMATCH")
        return after
    finally:
        os.close(fd)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _commit(stage_dir: int, output_dir: int, file: dict[str, Any]) -> None:
    name = file["name"]
    stage = ".stage-" + hashlib.sha256((name + "\0" + file["sha256"]).encode()).hexdigest()
    try:
        fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=stage_dir)
    except FileExistsError:
        # A prior interrupted write is never overwritten. Only complete bytes
        # may be reused; a partial stage is a controlled failure, not a receipt.
        try:
            staged = _read(stage_dir, stage, file)
        except ToolFileError:
            # Only this call's private, unlinked partial stage may be rebuilt.
            # The caller holds its stable per-call lock across this recovery.
            check = os.open(stage, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=stage_dir)
            try:
                info = os.fstat(check)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ToolFileError("FILE_STAGE_LINK_CONFLICT")
            finally:
                os.close(check)
            os.unlink(stage, dir_fd=stage_dir)
            return _commit(stage_dir, output_dir, file)
        if staged.st_nlink not in (1, 2):
            raise ToolFileError("FILE_STAGE_LINK_CONFLICT")
    else:
        try:
            data = memoryview(file["data"])
            while data:
                written = os.write(fd, data)
                if written <= 0:
                    raise ToolFileError("FILE_STAGE_WRITE_FAILED")
                data = data[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        staged = _read(stage_dir, stage, file)
    try:
        existing = _read(output_dir, name, file)
    except FileNotFoundError:
        if staged.st_nlink != 1:
            raise ToolFileError("FILE_STAGE_LINK_CONFLICT")
        try:
            # Stage is in a platform-private directory outside the sandbox's
            # mounted user-data tree. Its source leaf cannot be swapped by bash.
            os.link(stage, name, src_dir_fd=stage_dir, dst_dir_fd=output_dir, follow_symlinks=False)
        except FileExistsError:
            pass
        existing = _read(output_dir, name, file)
    if _same_inode(staged, existing):
        if existing.st_nlink != 2:
            raise ToolFileError("FILE_STAGE_LINK_CONFLICT")
        try:
            os.fsync(output_dir)
            os.unlink(stage, dir_fd=stage_dir)
        except FileNotFoundError:
            # An identical concurrent retry may have completed this cleanup.
            pass
    else:
        if existing.st_nlink != 1 or staged.st_nlink != 1:
            raise ToolFileError("FILE_OUTPUT_COLLISION")
        os.unlink(stage, dir_fd=stage_dir)
    os.fsync(output_dir)
    os.fsync(stage_dir)
    if _read(output_dir, name, file).st_nlink != 1:
        raise ToolFileError("FILE_OUTPUT_LINK_CONFLICT")


def _verify_current_directory(base: Path, relative: tuple[str, ...], expected_fd: int) -> None:
    handles: list[int] = []
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    handles.append(fd)
    try:
        for part in relative:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            handles.append(fd)
        if not _same_inode(os.fstat(fd), os.fstat(expected_fd)):
            raise ToolFileError("FILE_OUTPUT_DIRECTORY_CHANGED")
    finally:
        for handle in reversed(handles):
            os.close(handle)


def store_files(paths: Paths, user_id: str, thread_id: str, run_id: str, tool_call_id: str, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist validated bytes; never accept a destination supplied by a tool.

    POSIX dir_fd/O_NOFOLLOW is required. Every successful receipt follows an
    exclusive link commit, directory fsync and size/hash readback. Interrupted
    link cleanup recovers only the exact private stage and matching final inode.
    Files already committed before a later I/O failure remain in this call's
    namespace, but no all-files receipt is issued for a failed call.
    """
    handles: list[int] = []
    try:
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise ToolFileError("FILE_STORAGE_UNSUPPORTED")
        base = paths.base_dir
        thread = paths.thread_dir(thread_id, user_id=user_id).relative_to(base)
        namespace = hashlib.sha256(json.dumps([run_id, tool_call_id], separators=(",", ":")).encode()).hexdigest()
        output_parts = (*thread.parts, "user-data", "outputs", "mcp-files", namespace)
        stage_parts = (*thread.parts, ".mcp-file-staging", namespace)
        fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        handles.append(fd)
        output_dir = _walk(fd, output_parts, 0o755, handles)
        stage_dir = _walk(fd, stage_parts, 0o700, handles)
        import fcntl

        lock = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=stage_dir)
        handles.append(lock)
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ToolFileError("FILE_LOCK_INVALID")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ToolFileError("FILE_CALL_BUSY") from None
        receipts = []
        for file in files:
            _commit(stage_dir, output_dir, file)
            receipts.append({key: file[key] for key in ("name", "mime_type", "size_bytes", "sha256")})
            receipts[-1].update(path=f"/mnt/user-data/outputs/mcp-files/{namespace}/{file['name']}", readback_verified=True)
        _verify_current_directory(base, output_parts, output_dir)
        return receipts
    except (OSError, ValueError) as exc:
        if isinstance(exc, ToolFileError):
            raise
        raise ToolFileError("FILE_STORAGE_FAILED") from None
    finally:
        for handle in reversed(handles):
            os.close(handle)
