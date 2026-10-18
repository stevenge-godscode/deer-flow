# Native Agent directory — Issue 21

Root Controller/executor 01a14c72-9b4f-7be3-9cba-d8fc78fa09ae, single writer.
Exact accepted base b09d38c5dd9c4d9f59629cab1fc1fe711ee96833; unique branch codex/issue-21-agent-access-management.
Implementation began in ontology-dev's issue worktree. Its 1 GiB container hit OOM during full checks. The canonical native worktree has moved to the existing real data-platform-dev workspace at /workspace/native-validation-21/source (4 GiB); the former tree is retained read-only. Full Git history, exact dependencies and Python/Node runtime were transferred inside DEV. This is still real DEV, not a local/CI surrogate. No quota or business runtime was changed.

Scope: immutable shared Agent versions, identity business-role assignments, version enable/disable, account-scoped administrator UI and durable audit, with private chats/files/projects/memory intact. Deployment #542 owns environment-local physical bindings and immutable release. User authorizes DEV→STG→PROD same image digests and CMDB read-only access for the reported ordinary account; no merge or semantic CMDB change. Preserve PR20's private-owner guard.

Role state comes from the identity service and is checked at listing, admission, worker resolution and each protected tool call, including discovery infrastructure. Directory failures deny shared access. Publish only verified single-file skill bodies, immutable source definitions and new version IDs. No personal resource or credential copies.

Rollback by disabling the version/revoking the managed role and restoring retained images/config. Keep catalog audit, business history and target-private backups. Source/tests, immutable CI image identity, runtime UI and assigned/unassigned/revoked execution evidence are required before rollout.

Exact source CI reuses the repository's accepted `issue-*-source-check-dev` verification-ref convention. `issue-21-agent-source-check-dev` points to the exact implementation head and owns no independent changes/PR. Native candidate gates accept successful push checks of that head, not pull-request merge-ref metadata. The implementation branch remains codex/issue-21-agent-access-management.

Independent read-only review found and fixed delegated live revocation, enabled same-name skill body conflicts and unstable source selection. Retain the server-bound immutable reference through ordinary and durable delegation, reject skill conflicts atomically under the catalog lock, and bind UI source choices to owner/name. Real DEV regression: 264 backend tests, 3 management DOM tests and frontend check passed. Casdoor idempotent Unaffected role updates are accepted only after read-back verification.

User confirmed Steven needs a separate Agent directory manager role while remaining a native ordinary user. Add live own-realm agent-directory-manager self capability and session-only authorization; manager membership is operator-owned and cannot be granted through the assignable business profiles. Ordinary consumption has no account/admin data access.
