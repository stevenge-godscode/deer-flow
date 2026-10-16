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
