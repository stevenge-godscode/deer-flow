# Native personal connections — Issue 23

DeerFlow runs as an immutable image. Agent drafts, published versions, role
assignment and personal connections are configuration over that runtime. The
DEV release is tracked separately in genesis-deployment#546; this source does
not assert an environment was deployed or accepted.

## Reused upstream functions

The foundation backports pinned upstream changes 42334f26, 52a3e256, 9dc7bb30
and 4343ced6: Capability Center selection, owner-scoped personal MCP storage/API,
secret masking, current-role checks, public-network restrictions, owner/revision
checks on ordinary and durable calls, and cancelled-write draining. Native
plugin forms and Agent editing remain the user interfaces. Personal files have
restricted modes; this is not Vault/KMS encryption. Never mount these files in
Agent sandboxes or include credentials in Agent definitions or run metadata.

## Operator-approved internal connections

`DEER_FLOW_PERSONAL_MCP_TEMPLATES` points to an operator-owned JSON list. Each
entry contains `id`, fixed HTTP `url`, a native plugin `manifest` using adapter
`template`, credential field/header mapping, required fields, and
`service_headers_file`. The latter holds only gateway authentication, separate
from the user's source account, and must stay outside user-readable files.
Optional `server` settings carry transport timeouts/tools. The form accepts only
the declared fields. It cannot override endpoints, bridge headers or execution
settings. Runtime revalidates the template and injects the trusted owner;
changes to credentials, template or bridge identity invalidate old wrappers.
HTTP redirects do not carry these credentials to another endpoint.

An Agent selects `template:<id>` to resolve exactly one enabled connection for
the invoking user. No connection, duplicate connections, source login rejection
or missing optional provider identity may select a shared source credential.
Validated templates preserve upstream tool names, while connection/session
identities remain owner/config scoped. Ordinary arbitrary personal MCPs retain
public-network restrictions and name prefixing.

Directory managers edit their own native drafts and publish immutable snapshots
with explicit skills and MCP selections. Skill contents are pinned at publish;
editing the draft does not modify a released version. Roles grant access to the
Agent, while source systems decide data access using the user's own account.

## DEV composition and migration

ContextForge remains the MCP gateway and uses its native header passthrough.
The CMDB adapter implements request-scoped source login; optional Guance keys
stay in the same request identity. Required-personal mode disables shared source
fallback. This business behavior belongs to genesis-solution-cmdb-operations#2,
not DeerFlow or ContextForge.

Before starting this runtime, remove legacy `agent_directory.profiles.*.
mcp_service_auth` and retire the DEV shared CMDB MCP entry. Back up the previous
immutable image references, configuration and catalog for rollback. Configure
only the approved header names in ContextForge; do not enable broad sensitive
header forwarding. No STAGING/PRODUCTION rollout is authorized by this change.

Source tests cover per-user ownership, masked responses, tampered transport,
revocation and isolated requests. Two actual source identities with different
resource permissions are still required to accept real CMDB/Guance ACL behavior.
The supplied Genesis password is exclusively for platform login.
