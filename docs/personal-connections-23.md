# DEV personal connection foundation — Issue 23

This branch is a source candidate, not an environment release. The approved
shared Agent directory remains the deployed runtime in DEV, STG and PROD.

## Implemented foundation

Backported pinned upstream changes 42334f26, 52a3e256, 9dc7bb30 and 4343ced6:
Capability Center selection, owner-scoped personal MCP files and API, secret
masking, current-role checks, public-network restrictions, owner/revision-bound
tool and durable-task calls, and draining cancelled persistence operations.
Preserved the fork's live directory admission, memory settings and background
capability checks. Personal discovery failure drops all MCP tools before
selection can fall back to a deployment credential. User files use restricted
directory/file modes; this foundation does not claim Vault/KMS encryption.

## Not implemented or accepted by this branch

Operator-controlled CMDB/Guance templates, per-user CMDB source login and token
lifecycle, independent Guance read-only bindings, source-level resource ACL
acceptance and cross-domain ontology/result permission enforcement remain work
for Issue 23. The existing CMDB shared Source is not converted by this backport.
No real source credentials have been provided: the user-supplied credential was
explicitly for Genesis platform login and was used only for that purpose.

Do not deploy this source as completed personal CMDB access or promote it to
STG/PROD. Source-level tests and simulated provider tests do not constitute real
CMDB/Guance permission isolation. Preserve prior immutable runtime/configuration
for an eventual explicit DEV candidate and rollback.
