# ADR-0014: Local Application Assembly

- Status: Accepted
- Date: 2026-09-01
- Scope: P5-P21 integration baseline

## Decision

`JHOCApplication` is the local assembly root for the independently rebuilt modules. It starts Origin/Core and exposes a health surface while leaving model, memory, plugin, network, and legacy services optional. The assembly root owns wiring only; module ownership remains with each subsystem.

With `ApplicationConfig(storage_path=...)`, the assembly restores Trust, Guard, canonical stores, Registry/Shelf/Quota, Relay, knowledge/memory/proof, background planes, Lens, and Commons from isolated SQLite tables. It closes handles in reverse construction order and releases every already-open handle if any later constructor fails.
