# Immutable native Agent definitions

This optional feature separates ordinary Agent method publication from platform
Python releases. It contains no business query routing or answer templates.

## Publication

Use the existing native Agent create endpoint with a new versioned name,
`immutable_definition: true`, an explicit `skills` array, and
`skill_body_sha256` covering exactly those names. Each hash is lowercase SHA-256
of the complete SKILL.md UTF-8 file bytes, including frontmatter and line endings.
`memory_enabled: false` is supported through the same API. Initial facts and
long-term memories are separate data and are not seeded by this feature.

The file store atomically publishes an authoritative `definition.json` containing
config, SOUL and a canonical digest. Compatibility config.yaml/SOUL.md mirrors
are not authority for published names. The SQL store reads config and SOUL in
one row read and hashes the stored document, without applying future defaults
to its historical identity. Missing or corrupt canonical data fails closed.
Published names cannot be updated or deleted through AgentStore or CRUD. Publish
a new name and select it for a later Run. No Gateway restart is required for
ordinary Agent or SKILL.md publication through these existing data APIs.
Platform Python and startup MCP transport configuration retain their own release
boundary. This is not an Agent package import endpoint or a promotion service.

## Runs and recovery

Gateway admission resolves the authenticated owner's actual Agent snapshot.
Only `{schema, name, digest}` is persisted in RunRecord metadata. Client-supplied
references/digests in both context carriers are discarded. The worker restores
that reference for replay and the factory loads SOUL/config from one matching
snapshot, before constructing a model. Full bodies and credentials are not
copied into Run metadata.

An explicit checkpoint replay or resume command obtains its expected Agent name
and digest from trusted checkpoint metadata. All checkpoint selectors actually
consumed by LangGraph (typed fields, nested configurable and flat config) are
normalized; conflicts and foreign thread IDs are rejected before checkpoint
reads. Latest-head resume fixes the concrete snapshot ID read at admission. It
does not implement a latest-head compare-and-swap against concurrent writers.
Legacy checkpoints without a definition digest retain their existing behavior.
A normal new user turn may select a new Agent version; same-Run continuations
keep their admitted reference. Bootstrap cannot bypass an expected reference.

## Skills and provider limits

Published skill packages currently support exactly one SKILL.md file. Other
resources, scripts or subdirectories are explicitly rejected: a body hash must
not be presented as whole-package identity. Existing mutable skill packages
retain their ordinary resource support.

Assembly parses discovery metadata from the exact verified bytes. Before
sandbox acquisition, the source body and the actual physical thread projection
are checked. Only a provider declaring immutable projection support may execute
this path; AIO implements it with read-only category mounts. Other providers
default to refusal. The provider's real deployment mounts still require a live
environment acceptance test. The feature does not confer filesystem isolation
on an untrusted third-party provider merely because it advertises a boolean.

Slash activation verifies the body and uses verified secret metadata. Active
allowed-tools and secret-autonomy decisions revalidate live source bytes. A
missing, changed, disabled or unauthorized pinned active reference fails closed
for the active set, rather than dropping a restriction. Read_file and alternate
paths resolve to the physical isolated projection; already delivered model
context cannot be erased by subsequent revocation.

The standalone embedded DeerFlowClient does not have native admission and
physical pinning and explicitly rejects published definitions before model
construction. Invalid named config is not silently downgraded to a default.
Delegated scoped execution remains unsupported by the scoped authorization
provider; this feature does not create delegation authority.

## Storage and deletion limits

The default fallback snapshot for third-party legacy stores makes no atomic
promise for mutable definitions. File compatibility mirrors can still be
changed manually, but cannot override a valid canonical published document.
Operator replacement of canonical data is detected against an admitted digest.
SQL deletion is bound to the observed row ID, so a concurrent new publication
with the same natural key is not removed by an earlier missing-row delete.

The native delete route rejects an already published definition before memory
queue cancellation. The legacy cancel/delete/cancel debounce order is retained;
this is not a transaction spanning a concurrent create and memory manager.
Do not claim concurrent deletion cannot cancel newly queued memory. The business
Agent candidates in this migration have memory disabled.

## Validation

Tests use synthetic definitions and skills without model/network calls and cover
both stores, CRUD, canonical corruption, worker references, checkpoint carriers,
conflicts, thread identity, exact bytes, physical projection tampering, live
policy/secret metadata and unsupported embedded/provider paths. These source
checks do not constitute business answer quality or DEV/STG acceptance.
