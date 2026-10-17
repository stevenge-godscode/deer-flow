# Native capability admission

This optional provider adds generic capability constraints to the existing
central provider. It contains no domain routing, query plans or answer rules.
Business reasoning belongs to Agent SOUL/skills; deterministic domain functions
remain in the domain MCP service.

## Operator configuration

Configure `authorization.enabled=true`, `fail_closed=true` and provider use
`deerflow.authz.scoped:ScopedAuthorizationProvider`. Provider options are
`policy_path`, `delegate_use` and `delegate_config` (or an embedded delegate),
and optional canonical `skill_root` matching `skills.container_path`.
The policy file must be operator-owned, atomically replaced, and mounted
read-only outside all user API, thread and sandbox roots. Never place it in an
Agent SOUL, skill, user uploads or a user-editable integration file.

Policy schema version 1 has a nonempty revision and exact grants. Each grant
has id, owner_id, project_id, agent_name, enabled and capabilities. Supported
resource/action pairs are tool/call, skill/activate, mcp_server/connect and
sandbox/execute. No wildcard identifiers are accepted. MCP tool capabilities
require server_name and the SHA-256 of the complete server configuration;
server-connect capabilities require that digest and their exact target name.
Configuration digests are opaque; never log raw headers, environment or tokens.

Gateway admission discards supplied authorization attributes and project proof
from both input carriers, resolves real project membership, and pins grants.
Only Agent selection and mode use the native context-over-configurable fallback;
owner identity and project proof never do. Tool metadata is taken from the
actual concrete tool, not model arguments or name prefixes. Central permission
for both the tool and its server is required. Route, model and application
checks continue to use central authorization.

## Runtime boundaries

No grant added after admission expands the old run. If the pinned capability
set shrinks, all protected capabilities are denied, including file tools and
shell access to a previously mounted skill tree. Central skill denial or
unavailability has the same effect. This is a live fence, not a permanent
revocation latch: explicitly restoring all original legal authority allows
that run to continue. Already returned model context cannot be erased.

Scoped skill policy always creates a physical filtered projection, even when
all currently visible names are allowed or the set is empty. Native slash
activation, secret binding, discovery, activation-file reads and active skill
policy recheck authorization. The sandbox projection excludes unauthorized
packages and enforces symlink boundaries. Restricted AIO sandboxes do not
inherit user integration credential/runtime mounts or brokers. Their v3
filesystem-policy identity cannot reuse an old shared or v2 restricted
container. Explicit integration-runtime admission is not implemented here.

A lead grant cannot be reused by a child Agent. Subagents are marked at both
assembly and execution. Scoped bootstrap is rejected at admission with HTTP
403, before Agent/model/memory construction. Durable raw MCP submit, status and
cancel have no independent scoped admission contract and are denied before
connection; submit also denies before any driver runs. Historical task rows
are preserved. Scheduled and notification launches use common Gateway admission;
without an actual selected Agent and project they receive no protected grants.
Embedded callers without server-produced admission proof fail closed.

## Version and verification limits

Ordinary native MCP configuration has existing content-based cache invalidation;
no Gateway restart is needed for those supported changes. Program extensions
and durable task server/interceptor configuration retain their existing startup
boundary. This feature does not create an atomic Agent/config/SOUL/skill release
store. Definitions, prompt bodies and release publication must be separately
bound and verified before claiming one-version execution.

Synthetic tests cover forged carriers, ownership/project/Agent isolation,
concrete MCP origin, central denial, live revocation/regrant, bootstrap, child
execution, durable raw paths, physical skill projection and restricted mounts.
Offline gates do not establish actual AIO mount manifests, ordinary OIDC
permissions, persisted audit readback or live model answer quality. Those DEV
integration gates remain required before environment promotion.

Sandbox execution uses the exact singleton target `default` (resource `sandbox`, action `execute`) before container acquisition. It is not the wildcard `*` or a container ID; grant it explicitly in both central policy and the operator scope. Legacy RBAC wildcard/boolean policies still match through the existing RBAC rules. Custom exact-target providers must use this identity.


## Native default and projectless subjects

A public Agent name remains unchanged. A true native default Agent (`None`)
is matched only inside scoped authorization as `deerflow:default-agent`; empty,
boolean, numeric or reserved public names cannot select it. A server-confirmed
unassigned thread matches `deerflow:projectless`. These are exact policy subjects,
not wildcard grants. Central authorization, immutable Agent definitions, current
policy intersection and concrete MCP configuration/tool origins still apply.

The Gateway resolves one authorization provider for admission. Providers requiring
run scope require an owned thread row and strict membership resolution. Missing,
foreign, malformed or unavailable membership never degrades to projectless. Only
confirmed absent/NULL membership does. Memory mode needs no project repository
for a genuinely unassigned row. Client proof/projectless markers are cleared from
both runtime carriers before all binder early returns; the admission marker is
never persisted.

Temporary runs create owned metadata before strict resolution. Creation requires
a successful bounded absence check for the thread's journal messages and any
checkpoint namespace; legacy checkpoint-only history needs explicit ownership migration.
Concurrent inserts cannot replace an existing row. First-run benign metadata is
preserved and reserved project/definition/trace fields are excluded. An owned
legacy row with a NULL incarnation receives a single atomic initialization that
preserves owner, project, metadata and timestamps; unowned/foreign rows are never
claimed. The admitted owner/incarnation is rechecked at the worker startup
barrier. Missing/replaced rows, timeout, error or a cancelled verification task
fail startup before Agent construction. Durable notifications still require the
thread to exist. Bootstrap, unadmitted child runs and raw durable tool calls do
not inherit a lead grant.
