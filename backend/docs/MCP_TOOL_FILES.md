# Native MCP file receipts

The generic harness receives files only through explicit `deerflow.tool-file/v1`
MCP results. The Agent selects the export and explicitly calls `present_files`
after a receipt; the platform does not choose business workflows or answers.

## Protocol and boundary

`CallToolResult.structuredContent.files` is a list of one to four exact records:
`profile`, `resource_uri` (an opaque `urn:`), `name`, `mime_type`, `size_bytes`
and lowercase `sha256`. Each record must match exactly one EmbeddedResource
BlobResourceContents in the same result. MIME, canonical base64, decoded byte
length and hash must agree. No URL or filesystem URI is fetched or opened.
Display names have no path separators, controls, leading dot or overlong UTF-8.
Limits: 8 MiB/file, 16 MiB aggregate and 32 MiB complete serialized MCP result.
All records and blobs are validated before any writes. Additional content must
be text; duplicate names/URIs, errors and unmatched resources are rejected.

The receiver is the innermost shared MCP interceptor for HTTP, SSE and pooled
stdio. Ordinary results without the explicit protocol and short-circuit
ToolMessage/Command values pass through. It requires actual ToolRuntime with
explicit server-bound owner, thread, run and tool-call IDs; the standard user
resolver must agree with that owner. Missing runtime/background tasks cannot
write into a fallback bucket. An already initialized provider with shared thread-data mounts is
required; unsupported providers fail before persistence and no sandbox is
acquired by the receiver.

## Storage and recovery

Destinations are derived from native Paths, never tool arguments:
`/mnt/user-data/outputs/mcp-files/<SHA256([run,call])>/<name>` in that owner/thread.
Every ancestor and leaf is opened relative to descriptors with O_NOFOLLOW.
Every opened directory entry is fsynced in its parent, including entries left
by an interrupted prior mkdir, before proceeding.
Stages and a stable nonblocking per-call flock live under the private thread
root `.mcp-file-staging/`, outside sandbox-mounted user-data. The lock is never
replaced or unlinked. Holding it allows a proven private nlink1 partial stage
to be rebuilt after interruption. Unknown hardlinks and symlinks are rejected.

An exclusive hardlink commits complete fsynced bytes without overwriting an
existing name. The outputs directory is fsynced before unlinking the private
stage, then both directories are fsynced. A crash between link/unlink recovers
only the known stage whose inode matches final with nlink2; final is reopened
and verified as regular/nlink1 with exact size/hash. Existing identical files
are idempotent; different bytes fail. A busy concurrent call fails promptly and
may be retried. No replacement fallback is used.

The current output directory is reopened from the trusted base to detect an
ancestor rename before issuing a receipt. Multi-file I/O is not a transaction:
a later filesystem failure can leave earlier complete files, but returns no
all-files success. A later identical call completes them idempotently. The
receipt proves bytes at readback time; normal outputs remain user writable.

## Receipt, evidence and delivery

Accepted results become a native ToolMessage. Original non-blob text is
preserved, followed by `deerflow.tool-file-receipt/v1` with each verified native
path, MIME, size, SHA256 and `readback_verified: true`. No base64 enters model
content. ToolMessage.artifact contains the complete original bounded MCP result,
its canonical SHA256 and receipt; normal native journaling/checkpointing owns
persistence. Protocol, identity and size rejections return bounded technical errors with
`original_retained: false`. Once native identity and complete bounded bytes are
validated, provider/storage failures return an error ToolMessage retaining the
original and SHA in its artifact (`original_retained: true`, no delivered files).
Neither error path claims file delivery.

`present_files` registers a requested file and does not itself prove existence.
Release acceptance requires an authenticated artifact GET with matching bytes,
a different-owner denial, real journal readback and actual mounted sandbox
visibility. Unit graphs use real adapter/ToolNode conversion with synthetic
sessions; they do not establish network, ContextForge or live delivery success.

## Existing stdio workspace behavior

Persistent stdio sessions are scoped by user_id:thread_id. For stdio transports
only, DeerFlow pins subprocess default cwd to the thread workspace and
TMPDIR/TMP/TEMP to workspace/.mcp/tmp/, unless the operator explicitly configured
cwd or temp env. `.mcp` is internal: its temporary/debug files remain addressable
when returned but are excluded from workspace-change summaries by directory
name at any depth. SSE/HTTP skip this filesystem preparation.

Existing stdio local file references are translated only when they resolve
inside the current mounted user-data tree; they are not copied by that legacy
path translation. Explicit blob receipts above are a separate generic protocol.
