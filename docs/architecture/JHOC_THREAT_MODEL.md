# JHOC V5 Threat Model

## Assets

- User and task state
- Capability permissions and policy bundles
- Artifact bytes and owner references
- Relay delivery state and evidence packages
- Migration source hashes and archive manifests

## Trust Boundaries

1. User/producer input -> Contracts validation
2. Identity -> Trust and Guard authorization
3. Guard decision -> Conductor and Quota admission
4. Runner side effects -> Gate evidence verification
5. Gate evidence -> Output delivery
6. Offline migration source -> Quarantine and disposition review
7. SQLite file -> process-local and cross-process transactional stores

## Threats And Controls

| Threat | Control | Evidence |
|---|---|---|
| Untrusted or malformed input | native contract validation and schema checks | contract tests, schema validator |
| Permission escalation | default-deny Guard, identity allow-list | Guard matrix tests |
| Network unavailable | runtime mode denies network-required requests | Guard offline test |
| Duplicate or concurrent delivery | message idempotency and transactional lease | Relay tests |
| Lease owner crash | expiry reaping and retry/dead-letter | subprocess crash test |
| Cross-owner artifact disclosure | separate blob/reference tables and owner check | artifact isolation test |
| Unknown side effect | Gate rejects uncertain state | Gate tests |
| Migration source drift | source fingerprint re-scan | Ingest verification test |
| Unsafe cutover | independent scan, fresh process and Archive Manifest | P20/P21 report |

Secrets, cookies, tokens and device credentials are not copied into ordinary data, prompts, logs or migration manifests.
