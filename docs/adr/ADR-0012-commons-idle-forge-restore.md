# ADR-0012: Commons, Idle, Forge, and Restore

- Status: Accepted
- Date: 2026-09-01
- Scope: P14-P17 baseline

## Decision

Commons accepts only verified eligible evidence from a Trust-bound author with the matching `commons.*` permission, persists its archive in durable mode, and remains untrusted collaborative content. Idle jobs are low-priority and preemptible by foreground work. Forge candidates require replay evaluation and explicit approval before canary; it cannot mutate governance, permissions, core protocols, or Gate. Restore follows identity, policy, storage, capabilities, memory/graph, evidence/audit, and background ordering; emergency safe mode restores only the first three stages.

The Idle scheduler enforces foreground admission, TTL, maximum runtime, token budget, checkpoint and cancellation. Forge evaluation requires replay/regression/safety evidence and a benchmark result when supplied; governance, permission, protocol, completion-gate and policy-authority changes are rejected. Approved candidates enter an explicit canary state and resolve to promoted or rolled back with a score and reason. Restore operations emit in-process audit records and follow `docs/runbooks/JHOC_RESTORE_RUNBOOK.md`.
