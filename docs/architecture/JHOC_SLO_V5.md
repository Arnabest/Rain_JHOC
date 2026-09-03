# JHOC V5 Local SLO Baseline

This is the measurable baseline for the local acceptance harness. Values are targets for the current single-host implementation and must be re-measured before production deployment.

| Dimension | Target | Evidence command or test |
|---|---:|---|
| Empty-system startup | <= 2 s, no external services | `python scripts/smoke.py` |
| Contract/schema validation | 100% named schemas pass | `python scripts/validate_schemas.py` |
| Durable CAS correctness | exactly one writer per expected version | `tests/durable` concurrent CAS test |
| Relay duplicate leasing | one lease per message under concurrent consumers | `tests/durable` cross-instance test |
| Relay bounded queue | reject at configured `max_pending` | `test_sqlite_relay_applies_bounded_backpressure` |
| Evidence persistence | survives close/reopen | durable Proof and E2E restart tests |
| Independence | zero forbidden runtime references | `python scripts/check_independence.py` |
| Recovery integrity | hash verified; existing target never overwritten | database snapshot/restore acceptance test |

Unmeasured production characteristics, including hardware temperature, GPU pressure, network latency and multi-day uptime, remain release blockers rather than assumed values.
