# ADR-0009: Registry, Shelf, and Quota

- Status: Accepted
- Date: 2026-09-01
- Scope: P10 baseline

## Decision

Registry owns capability metadata and verification status. Shelf owns only verified, explicitly shelf-eligible capability entries; governance plugins are rejected before admission. Quota owns hard resource capacities and expiring leases for CPU, GPU, memory, tokens, concurrency, duration, network availability, temperature, power, and battery constraints. Durable mode persists Registry and Shelf independently and uses transactional SQLite Quota admission so concurrent processes share one capacity boundary; crashed leases remain fenced until TTL expiry.

Conductor will be the only runtime selector in P11. Registry and Shelf never dispatch work or grant permissions.
