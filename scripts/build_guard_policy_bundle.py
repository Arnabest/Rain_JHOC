"""Builds and registers the official JHOC Immutable Governance PolicyBundle.

Translates the V5 core governance principles and security boundaries into a formal
PolicyBundle loaded into SQLiteGuardRuntime (logs/p19-guard.sqlite).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.guard.policy import (  # noqa: E402
    Decision,
    PolicyBundle,
    PolicyRequest,
    PolicyRule,
    RuleEffect,
)
from jhoc.guard.sqlite import SQLiteGuardRuntime  # noqa: E402

GUARD_DB = ROOT / "logs" / "p19-guard.sqlite"
REPORT_PATH = ROOT / "docs" / "governance" / "jhoc-governance-policy-bundle-v1.json"
REPORT_MD = ROOT / "docs" / "governance" / "jhoc-governance-policy-bundle-v1.md"


def build_policy_bundle() -> dict[str, Any]:
    rules = (
        PolicyRule(
            rule_id="RULE_READ_ONLY_SAFE",
            effect=RuleEffect.ALLOW,
            operations=frozenset({
                "read_knowledge", "query_memory", "inspect_graph", "check_status", "read_provenance", "read_file"
            }),
            max_risk_level=1,
            external_side_effect=False,
            requires_network=False,
            sensitive=False,
            priority=10,
        ),
        PolicyRule(
            rule_id="RULE_ONLINE_QUERY_SAFE",
            effect=RuleEffect.ALLOW,
            operations=frozenset({"http_fetch", "model_query", "web_search"}),
            max_risk_level=2,
            external_side_effect=False,
            requires_network=True,
            sensitive=False,
            priority=10,
        ),
        PolicyRule(
            rule_id="RULE_MUTATION_APPROVAL_REQUIRED",
            effect=RuleEffect.REQUIRE_APPROVAL,
            operations=frozenset({
                "mutate_code", "run_terminal", "delete_file", "git_commit", "deploy", "system_change"
            }),
            max_risk_level=4,
            external_side_effect=True,
            priority=50,
        ),
        PolicyRule(
            rule_id="RULE_DENY_LEGACY_RUNTIME",
            effect=RuleEffect.DENY,
            operations=frozenset({
                "legacy_bus_connect", "legacy_script_exec", "legacy_audio_record", "legacy_profile_mount"
            }),
            max_risk_level=4,
            priority=100,
        ),
        PolicyRule(
            rule_id="RULE_DENY_POLICY_MUTATION",
            effect=RuleEffect.DENY,
            operations=frozenset({
                "modify_guard_rule", "alter_policy_bundle", "override_security_gate"
            }),
            max_risk_level=4,
            priority=100,
        ),
        PolicyRule(
            rule_id="RULE_DENY_RAW_SECRETS",
            effect=RuleEffect.DENY,
            operations=frozenset({
                "export_raw_token", "print_api_key", "dump_credentials"
            }),
            max_risk_level=4,
            sensitive=True,
            priority=100,
        ),
    )

    bundle = PolicyBundle(
        version="jhoc-governance-v1.0",
        source="jhoc://v5/plan/governance",
        rules=rules,
    )

    if GUARD_DB.exists():
        GUARD_DB.unlink()

    guard = SQLiteGuardRuntime(str(GUARD_DB))
    guard.load(bundle)

    # Test evaluation sanity checks
    eval_safe = guard.evaluate(None, PolicyRequest(operation="read_knowledge", risk_level=0))
    eval_mutation = guard.evaluate(None, PolicyRequest(operation="mutate_code", risk_level=3, external_side_effect=True))
    eval_legacy = guard.evaluate(None, PolicyRequest(operation="legacy_bus_connect", risk_level=2))
    eval_secret = guard.evaluate(None, PolicyRequest(operation="print_api_key", risk_level=4, sensitive=True))

    guard.close()

    result = {
        "status": "PASS",
        "bundle_version": bundle.version,
        "bundle_source": bundle.source,
        "rules_count": len(bundle.rules),
        "rules": [
            {
                "rule_id": r.rule_id,
                "effect": r.effect.value,
                "operations": sorted(r.operations),
                "priority": r.priority,
                "max_risk_level": r.max_risk_level,
            }
            for r in bundle.rules
        ],
        "evaluations_verified": {
            "read_knowledge": eval_safe.decision.value,
            "mutate_code": eval_mutation.decision.value,
            "legacy_bus_connect": eval_legacy.decision.value,
            "print_api_key": eval_secret.decision.value,
        },
        "all_checks_passed": (
            eval_safe.decision == Decision.ALLOW
            and eval_mutation.decision == Decision.REQUIRE_APPROVAL
            and eval_legacy.decision == Decision.DENY
            and eval_secret.decision == Decision.DENY
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    md_lines = [
        "# JHOC Core Governance Policy Bundle v1.0",
        "",
        f"- Bundle Version: `{bundle.version}`",
        f"- Generated At: `{result['generated_at_utc']}`",
        f"- Storage Path: `{GUARD_DB}`",
        f"- Evaluation Checks Passed: **{'YES' if result['all_checks_passed'] else 'NO'}**",
        "",
        "## Policy Rules Summary",
        "",
        "| Rule ID | Effect | Max Risk | Priority | Operations |",
        "|---|:---:|:---:|:---:|---|",
    ]
    for r in bundle.rules:
        ops = ", ".join(f"`{o}`" for o in sorted(r.operations))
        md_lines.append(f"| `{r.rule_id}` | **{r.effect.value}** | {r.max_risk_level} | {r.priority} | {ops} |")

    md_lines.extend([
        "",
        "## Verification Receipts",
        "",
        f"- `read_knowledge` (Safe Query) -> **{eval_safe.decision.value}**",
        f"- `mutate_code` (Side Effect) -> **{eval_mutation.decision.value}**",
        f"- `legacy_bus_connect` (Legacy Runtime) -> **{eval_legacy.decision.value}**",
        f"- `print_api_key` (Sensitive Secret) -> **{eval_secret.decision.value}**",
    ])

    REPORT_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    res = build_policy_bundle()
    print(json.dumps(res, indent=2))
