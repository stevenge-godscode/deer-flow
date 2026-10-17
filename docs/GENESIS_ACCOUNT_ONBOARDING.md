# Genesis DEV account onboarding

New verified identity users use native JIT provisioning. Existing accounts must prove their local password and their OIDC identity; email coincidence never merges accounts. The login page offers explicit association. IDs, password hashes and resource ownership stay unchanged. Linking/unlinking uses an atomic token-version check and revokes prior sessions; audit writes commit in the same transaction.

Migration 0026 extends 0025. Rollback must stop all writers and verify a database backup before reverting the schema stamp to 0025; the identity audit table remains. Re-upgrade validates its retained shape. Switching to an older image while retaining the unknown 0026 stamp is rejected.

The account source gate runs on exact commits with approved proxy downloads and isolated PostgreSQL/Redis. DEV targeted checks do not replace PostgreSQL, native image and browser acceptance. Real mailbox registration is still pending inbox verification. This identity work does not certify universal Ontology business admission.
