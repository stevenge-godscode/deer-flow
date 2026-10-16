# Authorization implementation

## Scoped capability provider

`authz/scoped.py` composes operator-owned exact run grants with the existing
central provider. Preserve the shared Principal builder, concrete MCP origin,
trusted project admission and execution-time checks. Never infer authority from
SOUL, skill instructions, user-supplied authz_attributes, tool arguments or a
maintenance identity. Scope does not implement business plans.

Scoped bootstrap and unadmitted child/durable execution fail closed. A scoped
skill list always materializes a physical projection; restricted AIO uses the
v3 filesystem policy identity and excludes implicit integration runtime mounts
and brokers. Preserve both sync/async paths and ownership-fenced replacement.
Live authority shrinkage fences all protected tools until original permissions
are restored; it is not a persisted revocation latch. Contract and deployment
limits: `docs/SCOPED_AUTHORIZATION.md`.

Default/projectless subjects are internal exact identities only. A true default
Agent stays public None. Projectless proof comes from strict owner membership
resolution, never caller flags or lookup failure. Temporary admission must prove
absence of legacy checkpoint/journal history; retain the same provider instance
through proof binding. Thread startup pins/rechecks owner plus incarnation,
including owned-only atomic initialization of legacy NULL incarnations; it never
uses the legacy unscoped ownership-claim path. Verification cancellation fails
closed. Keep SCOPED_AUTHORIZATION.md and two-stage admission regressions current.
