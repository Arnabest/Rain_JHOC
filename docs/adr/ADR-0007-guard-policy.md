# ADR-0007: Guard Policy Runtime

- Status: Accepted
- Date: 2026-09-01
- Scope: P8 baseline

## Decision

Guard evaluates a versioned PolicyBundle and returns an auditable PolicyDecision. No bundle, no matching rule, missing permission, offline network request, malformed input, or conflicting top-priority rules all fail closed to `DENY`. Rules may return `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`.

Guard decides whether work may begin; it does not select capabilities, execute tools, mutate task state, or declare completion. Gate remains the owner of accepted completion.

