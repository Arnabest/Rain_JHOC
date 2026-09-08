# Initial Threat Model

## Assets

- User data, credentials, task inputs, execution evidence, policy bundles, and local artifacts.

## Primary threats

- Untrusted plugin input or output crossing a contract boundary.
- A model attempting to select capabilities, grant permission, or mutate governance.
- Malicious reading or leakage of credentials, SSH keys, or environment secrets via sandbox bypass.
- Plugin supply-chain poisoning and dangerous primitive execution (subprocess, system commands, eval).
- Duplicate or reordered delivery causing repeated external side effects.
- Stale state, prompt injection, or untracked evidence being presented as task completion.
- Accidental runtime coupling to AIBOX, VERS, or the legacy bus.

## Required controls

- Versioned schemas and fail-closed validation.
- PathGuard bidirectional filesystem evaluation: strictly contained within workspace, sensitive assets (.ssh, credentials, .env) blocked unconditionally.
- PluginGatekeeper "Three Gates" supply-chain enforcement: manifest integrity, AST static X-ray for dangerous host primitives, and dependency depth bounds.
- Guard-owned authorization and Quota-owned resource enforcement (`mutable_by_agent: false` on governance).
- Idempotency keys, leases, bounded retries, dead letters, and reconciliation states.
- DataSanitizer de-instructioning: cleanses untrusted data streams, strips hidden unicode control markers, and neutralizes prompt injection directives before entering context.
- ParameterizedInvocationEngine: prepared-statement style command compilation and binding; data values remain passive string literals; shell execution is forbidden.
- CredentialVault zero-knowledge credential isolation: context and logs only handle anonymous token references (`vault://secret/...`); secrets dereferenced strictly at egress network boundary.
- Gate-owned completion backed by BlackBoxJournal five-tuple cryptographically-chained audit trails (`USER`, `SEEN`, `THINK`, `TOOL`, `BACK`), plane attribution (`DATA` vs `CONTROL`), and immutable evidence references.
- Offline migration only; no runtime imports of legacy systems.



