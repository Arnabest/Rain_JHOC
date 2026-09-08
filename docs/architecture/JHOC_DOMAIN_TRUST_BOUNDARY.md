# JHOC Domain And Trust Boundary

| Domain | Owns | May consume | Must not own |
|---|---|---|---|
| Origin/Core | startup state, lifecycle and shared store services | Trust, Config | capability selection or policy mutation |
| Guard/Trust | identity, permission and policy decisions | native requests | execution side effects |
| Relay | envelope delivery, leases and retries | MessageEnvelope | task, memory or evidence business state |
| Conductor/Quota | capability selection and resource leases | Guard decision, Registry/Shelf | policy authority |
| Context | authorized source composition and snapshots | Guard-approved sources | new permissions |
| Runner/Gate | execution result and completion evidence | Context, Proof | user-facing output bypass |
| Output | delivery of accepted evidence | Gate/Proof | task re-execution |
| Ingest/Restore/Ops | offline migration, snapshots and cutover checks | hashes and manifests | runtime legacy services |

The table is the P1 ownership contract. Any new module must declare its owner, consumers, side effects and trust boundary before implementation.
