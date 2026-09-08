# ADR-0003: Native Plugin Protocol

- Status: Accepted
- Date: 2026-09-01
- Scope: P4 Plugin Protocol baseline

## Decision

Every plugin is hosted through a versioned native protocol with explicit lifecycle states:

`DISCOVERED -> VERIFIED -> INSTALLED -> LOADED -> NEGOTIATED -> INITIALIZED -> READY -> RUNNING -> DRAINING -> STOPPED`.

The host validates manifest identity and protocol version before negotiation. Public operations reject invalid lifecycle states by default. Invocation failures enter `FAILED` and never silently return to `READY`; shutdown is the only recovery transition from `FAILED` in this baseline.

## Boundary

`PluginManifest` describes permissions, side effects, resources, verification, and shelf eligibility. The host validates the protocol but does not grant capability selection or policy authority. Governance plugins remain in the control plane and cannot become shelf assets.

## Consequences

The host remains an in-process lifecycle boundary. `invoke`, `stream`, `cancel`, `checkpoint`, `drain`, and `shutdown` are executable protocol operations, including early stream-close recovery and fail-closed transitions. Durable delivery and recovery evidence are composed through Relay, State Store, Lens, and Proof rather than embedded in the plugin host; lifecycle pressure probes cover 250 test cycles and 100 runtime-report cycles.
