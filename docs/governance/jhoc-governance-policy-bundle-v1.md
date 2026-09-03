# JHOC Core Governance Policy Bundle v1.0

- Bundle Version: `jhoc-governance-v1.0`
- Generated At: `2026-09-02T16:35:17.738328+00:00`
- Storage Path: `G:\JHOC\logs\p19-guard.sqlite`
- Evaluation Checks Passed: **YES**

## Policy Rules Summary

| Rule ID | Effect | Max Risk | Priority | Operations |
|---|:---:|:---:|:---:|---|
| `RULE_READ_ONLY_SAFE` | **ALLOW** | 1 | 10 | `check_status`, `inspect_graph`, `query_memory`, `read_file`, `read_knowledge`, `read_provenance` |
| `RULE_ONLINE_QUERY_SAFE` | **ALLOW** | 2 | 10 | `http_fetch`, `model_query`, `web_search` |
| `RULE_MUTATION_APPROVAL_REQUIRED` | **REQUIRE_APPROVAL** | 4 | 50 | `delete_file`, `deploy`, `git_commit`, `mutate_code`, `run_terminal`, `system_change` |
| `RULE_DENY_LEGACY_RUNTIME` | **DENY** | 4 | 100 | `legacy_audio_record`, `legacy_bus_connect`, `legacy_profile_mount`, `legacy_script_exec` |
| `RULE_DENY_POLICY_MUTATION` | **DENY** | 4 | 100 | `alter_policy_bundle`, `modify_guard_rule`, `override_security_gate` |
| `RULE_DENY_RAW_SECRETS` | **DENY** | 4 | 100 | `dump_credentials`, `export_raw_token`, `print_api_key` |

## Verification Receipts

- `read_knowledge` (Safe Query) -> **ALLOW**
- `mutate_code` (Side Effect) -> **REQUIRE_APPROVAL**
- `legacy_bus_connect` (Legacy Runtime) -> **DENY**
- `print_api_key` (Sensitive Secret) -> **DENY**
