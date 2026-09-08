import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.config import RuntimeMode  # noqa: E402
from jhoc.contracts import ContractError  # noqa: E402
from jhoc.guard import Decision, GuardRuntime, PolicyBundle, PolicyRequest, PolicyRule, SensitivityPolicy, SQLiteGuardRuntime  # noqa: E402
from jhoc.trust import Identity, IdentityType, PermissionSet  # noqa: E402


class GuardPolicyTests(unittest.TestCase):
    def setUp(self):
        self.identity = Identity("user", IdentityType.USER, PermissionSet(frozenset({"task.read"})))

    def test_unloaded_guard_defaults_to_deny(self):
        result = GuardRuntime().evaluate(self.identity, PolicyRequest("task.read", 0, "task.read"))
        self.assertEqual(result.decision, Decision.DENY)

    def test_matching_rule_allows_authorized_l0(self):
        guard = GuardRuntime()
        guard.load(PolicyBundle("2026.09.01", "local", (PolicyRule("read", "ALLOW", frozenset({"task.read"}), 1, required_permission="task.read"),)))
        result = guard.evaluate(self.identity, PolicyRequest("task.read", 0, "task.read"))
        self.assertEqual(result.decision, Decision.ALLOW)
        self.assertEqual(result.matched_rules, ("read",))

    def test_missing_permission_and_network_are_denied(self):
        guard = GuardRuntime()
        guard.load(PolicyBundle("v1", "local", (PolicyRule("safe", "ALLOW", frozenset({"task.write"}), 2),)))
        self.assertEqual(guard.evaluate(self.identity, PolicyRequest("task.write", 1, "task.write")).decision, Decision.DENY)
        self.assertEqual(guard.evaluate(self.identity, PolicyRequest("task.write", 1, requires_network=True), mode=RuntimeMode.OFFLINE).decision, Decision.DENY)

    def test_permission_and_network_matrix_fails_closed_for_identities_and_modes(self):
        guard = GuardRuntime()
        guard.load(PolicyBundle("v1", "local", (
            PolicyRule("read", "ALLOW", frozenset({"read"}), 1, required_permission="task.read"),
            PolicyRule("network", "ALLOW", frozenset({"fetch"}), 1, requires_network=True),
        )))
        identities = (None, Identity("no-permission", IdentityType.AGENT), self.identity)
        for identity in identities[:2]:
            self.assertEqual(guard.evaluate(identity, PolicyRequest("read", 0, permission="task.read")).decision, Decision.DENY)
        self.assertEqual(guard.evaluate(identities[2], PolicyRequest("read", 0, permission="task.read")).decision, Decision.ALLOW)
        self.assertEqual(guard.evaluate(self.identity, PolicyRequest("fetch", 0, requires_network=True), mode=RuntimeMode.OFFLINE).decision, Decision.DENY)
        self.assertEqual(guard.evaluate(self.identity, PolicyRequest("fetch", 0, requires_network=True), mode=RuntimeMode.ONLINE).decision, Decision.ALLOW)

    def test_high_risk_rule_requires_approval(self):
        guard = GuardRuntime()
        guard.load(PolicyBundle("v1", "local", (PolicyRule("risky", "REQUIRE_APPROVAL", frozenset({"device.control"}), 4, priority=5),)))
        result = guard.evaluate(self.identity, PolicyRequest("device.control", 4))
        self.assertEqual(result.decision, Decision.REQUIRE_APPROVAL)

    def test_conflicting_top_priority_rules_fail_closed(self):
        guard = GuardRuntime()
        guard.load(PolicyBundle("v1", "local", (
            PolicyRule("allow", "ALLOW", frozenset({"task"}), 1, priority=10),
            PolicyRule("deny", "DENY", frozenset({"task"}), 1, priority=10),
        )))
        result = guard.evaluate(self.identity, PolicyRequest("task", 0))
        self.assertEqual(result.decision, Decision.DENY)
        self.assertEqual(result.reason, "conflicting policy rules")

    def test_duplicate_rule_ids_rejected(self):
        with self.assertRaises(ContractError):
            PolicyBundle("v1", "local", (PolicyRule("x", "DENY"), PolicyRule("x", "ALLOW")))

    def test_sensitivity_clearance_is_monotonic_and_default_denies_unknown(self):
        self.assertTrue(SensitivityPolicy.allows("RESTRICTED", "CONFIDENTIAL"))
        self.assertFalse(SensitivityPolicy.allows("INTERNAL", "CONFIDENTIAL"))
        with self.assertRaises(ContractError):
            SensitivityPolicy.allows("SECRET", "PUBLIC")

    def test_decision_receipts_capture_policy_identity_operation_and_mode(self):
        guard = GuardRuntime()
        guard.load(PolicyBundle("audit:v1", "local", (PolicyRule("read", "ALLOW", frozenset({"task.read"}), 1),)))
        decision = guard.evaluate(self.identity, PolicyRequest("task.read", 0), mode=RuntimeMode.LIMITED_NETWORK)
        self.assertEqual(decision.policy_ref, "audit:v1")
        self.assertEqual(decision.operation, "task.read")
        self.assertEqual(decision.identity_id, str(self.identity.identity_id))
        self.assertEqual(decision.mode, RuntimeMode.LIMITED_NETWORK.value)
        self.assertEqual(guard.decisions(policy_ref="audit:v1"), (decision,))

    def test_sqlite_guard_restores_bundle_history_and_decision_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "guard.db")
            first = SQLiteGuardRuntime(path)
            first.load(PolicyBundle("audit:v1", "local", (PolicyRule("read", "ALLOW", frozenset({"task.read"}), 1),)))
            first.evaluate(self.identity, PolicyRequest("task.read", 0))
            first.load(PolicyBundle("audit:v2", "local", (PolicyRule("deny", "DENY", frozenset({"task.write"}), 2),)))
            first.evaluate(self.identity, PolicyRequest("task.write", 1))
            first.close()

            restored = SQLiteGuardRuntime(path)
            self.assertEqual([bundle.version for bundle in restored.bundle_history()], ["audit:v1", "audit:v2"])
            self.assertEqual([item.policy_ref for item in restored.decisions()], ["audit:v1", "audit:v2"])
            current = restored.evaluate(self.identity, PolicyRequest("task.write", 1))
            self.assertEqual(current.decision, Decision.DENY)
            self.assertEqual(current.matched_rules, ("deny",))
            restored.close()

    def test_sqlite_guard_refreshes_policy_before_cross_instance_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "guard.db")
            writer = SQLiteGuardRuntime(path)
            observer = SQLiteGuardRuntime(path)
            writer.load(
                PolicyBundle("policy:v1", "local", (PolicyRule("allow", "ALLOW", frozenset({"task.run"}), 1),))
            )
            self.assertEqual(
                observer.evaluate(self.identity, PolicyRequest("task.run", 0)).decision,
                Decision.ALLOW,
            )
            writer.load(
                PolicyBundle("policy:v2", "local", (PolicyRule("deny", "DENY", frozenset({"task.run"}), 1),))
            )
            denied = observer.evaluate(self.identity, PolicyRequest("task.run", 0))
            self.assertEqual(denied.decision, Decision.DENY)
            self.assertEqual(denied.policy_ref, "policy:v2")
            self.assertEqual([bundle.version for bundle in observer.bundle_history()], ["policy:v1", "policy:v2"])
            writer.close()
            observer.close()

    def test_sqlite_guard_rejects_policy_version_content_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = SQLiteGuardRuntime(str(Path(directory) / "guard.db"))
            guard.load(
                PolicyBundle("policy:v1", "local", (PolicyRule("allow", "ALLOW", frozenset({"task.run"}), 1),))
            )
            with self.assertRaises(ContractError):
                guard.load(
                    PolicyBundle("policy:v1", "local", (PolicyRule("deny", "DENY", frozenset({"task.run"}), 1),))
                )
            self.assertEqual(
                guard.evaluate(self.identity, PolicyRequest("task.run", 0)).decision,
                Decision.ALLOW,
            )
            guard.close()


if __name__ == "__main__":
    unittest.main()
