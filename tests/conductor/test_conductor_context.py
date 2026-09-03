import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.config import RuntimeMode  # noqa: E402
from jhoc.conductor import CandidateDecision, CapabilityRequest, Conductor, PlanDecision  # noqa: E402
from jhoc.context import ContextOrchestrator, ContextSource  # noqa: E402
from jhoc.guard import GuardRuntime, PolicyBundle, PolicyRequest, PolicyRule  # noqa: E402
from jhoc.quota import QuotaManager, ResourcePlan  # noqa: E402
from jhoc.registry import CapabilityRecord, CapabilityRegistry  # noqa: E402
from jhoc.shelf import Shelf  # noqa: E402
from jhoc.trust import Identity, IdentityType, PermissionSet  # noqa: E402
from jhoc.contracts import ContractError, PluginManifest  # noqa: E402


class ConductorContextTests(unittest.TestCase):
    @staticmethod
    def source(source_id, data, sensitivity, *, consumers=frozenset({"runner"}), expires_at=None):
        return ContextSource(
            source_id,
            data,
            sensitivity,
            expires_at or datetime.now(timezone.utc) + timedelta(minutes=5),
            consumers,
            (f"source:{source_id}",),
        )

    def test_capability_request_rejects_empty_or_malformed_candidates(self):
        with self.assertRaises(ContractError):
            CapabilityRequest("", (), ResourcePlan())
        with self.assertRaises(ContractError):
            CapabilityRequest("run", (("", "1.0.0"),), ResourcePlan())

    def test_conductor_rejects_policy_and_capability_operation_mismatch(self):
        conductor = Conductor(CapabilityRegistry(), Shelf(), QuotaManager(ResourcePlan()), GuardRuntime())
        request = CapabilityRequest("write", (("cap", "1.0.0"),), ResourcePlan())
        with self.assertRaisesRegex(ContractError, "operations must match"):
            conductor.select(None, PolicyRequest("read", 0), request)

    def test_guard_rejection_preserves_considered_candidates_for_audit(self):
        guard = GuardRuntime()
        guard.load(PolicyBundle("v1", "local", (PolicyRule("other", "ALLOW", frozenset({"other"}), 1),)))
        request = CapabilityRequest("run", (("cap-a", "1.0.0"), ("cap-b", "2.0.0")), ResourcePlan())
        plan = Conductor(CapabilityRegistry(), Shelf(), QuotaManager(ResourcePlan()), guard).select(
            None, PolicyRequest("run", 0), request, mode=RuntimeMode.OFFLINE
        )
        self.assertEqual(plan.decision, PlanDecision.REJECTED)
        self.assertEqual(plan.considered, request.candidates)
        self.assertTrue(all(item.decision == CandidateDecision.NOT_EVALUATED for item in plan.assessments))

    def test_conductor_selects_verified_shelf_entry_under_guard_and_quota(self):
        manifest = PluginManifest("cap", "Cap", "1.0.0", "1.0", "capability", verification_status="VERIFIED", shelf_eligible=True)
        registry = CapabilityRegistry()
        registry.register(CapabilityRecord("cap", "1.0.0", manifest, "in", "out"))
        verified = registry.verify("cap", "1.0.0", health="HEALTHY")
        shelf = Shelf()
        shelf.admit(verified)
        guard = GuardRuntime()
        guard.load(PolicyBundle("v1", "local", (PolicyRule("run", "ALLOW", frozenset({"run"}), 1),)))
        conductor = Conductor(registry, shelf, QuotaManager(ResourcePlan(cpu_units=1, memory_mb=512, token_budget=1000, max_concurrency=1)), guard)
        identity = Identity("user", IdentityType.USER, PermissionSet())
        plan = conductor.select(identity, PolicyRequest("run", 0), CapabilityRequest("run", (("cap", "1.0.0"),), ResourcePlan(cpu_units=1, memory_mb=128, token_budget=100)), mode=RuntimeMode.OFFLINE)
        self.assertEqual(plan.decision, PlanDecision.SELECTED)
        conductor.release(plan)

    def test_conductor_rejects_unverified_or_quota_exhausted_candidates(self):
        manifest = PluginManifest("cap", "Cap", "1.0.0", "1.0", "capability", verification_status="VERIFIED", shelf_eligible=True)
        registry = CapabilityRegistry()
        registry.register(CapabilityRecord("cap", "1.0.0", manifest, "in", "out"))
        guard = GuardRuntime()
        guard.load(PolicyBundle("v1", "local", (PolicyRule("run", "ALLOW", frozenset({"run"}), 1),)))
        conductor = Conductor(registry, Shelf(), QuotaManager(ResourcePlan()), guard)
        plan = conductor.select(None, PolicyRequest("run", 0), CapabilityRequest("run", (("cap", "1.0.0"),), ResourcePlan()), mode=RuntimeMode.OFFLINE)
        self.assertEqual(plan.decision, PlanDecision.REJECTED)
        self.assertEqual(plan.assessments[0].reason, "registry record is not verified")

    def test_conductor_explains_rejected_candidate_and_selected_fallback(self):
        registry = CapabilityRegistry()
        shelf = Shelf()
        for capability_id in ("unhealthy", "fallback"):
            manifest = PluginManifest(
                capability_id, capability_id.title(), "1.0.0", "1.0", "capability",
                verification_status="VERIFIED", shelf_eligible=True,
            )
            registry.register(CapabilityRecord(capability_id, "1.0.0", manifest, "in", "out"))
            health = "UNAVAILABLE" if capability_id == "unhealthy" else "HEALTHY"
            shelf.admit(registry.verify(capability_id, "1.0.0", health=health))
        guard = GuardRuntime()
        guard.load(PolicyBundle("v1", "local", (PolicyRule("run", "ALLOW", frozenset({"run"}), 1),)))
        conductor = Conductor(registry, shelf, QuotaManager(ResourcePlan()), guard)
        plan = conductor.select(
            None,
            PolicyRequest("run", 0),
            CapabilityRequest("run", (("unhealthy", "1.0.0"), ("fallback", "1.0.0")), ResourcePlan()),
        )
        self.assertEqual(plan.selected, ("fallback", "1.0.0"))
        self.assertEqual([item.decision for item in plan.assessments], [CandidateDecision.REJECTED, CandidateDecision.SELECTED])
        self.assertIn("UNAVAILABLE", plan.assessments[0].reason)
        conductor.release(plan)

    def test_context_pass_b_only_includes_authorized_sources_and_is_stable(self):
        context = ContextOrchestrator()
        pass_a = context.pass_a("hello", {"task": "t1"}, policy_ref="policy:v1")
        sources = (self.source("public", {"text": "ok"}, "public"), self.source("secret", {"token": "x"}, "secret"))
        package = context.pass_b(pass_a, sources, authorized_source_ids=frozenset({"public"}), consumer_id="runner", resource_plan_ref="plan:v1")
        self.assertEqual(tuple(source.source_id for source in package.sources), ("public",))
        self.assertTrue(package.snapshot_id.startswith("context:"))
        package_again = context.pass_b(pass_a, sources, authorized_source_ids=frozenset({"public"}), consumer_id="runner", resource_plan_ref="plan:v1")
        self.assertEqual(package.snapshot_id, package_again.snapshot_id)
        rebuilt = context.rebuild(package.snapshot_id)
        self.assertEqual(rebuilt, package)

    def test_context_redacts_sensitive_keys_recursively(self):
        context = ContextOrchestrator()
        pass_a = context.pass_a("hello", {}, policy_ref="policy:v1")
        source = self.source(
            "private",
            {"token": "secret", " token ": "wrapped", "nested": [{"password": "pw"}], "safe": "ok"},
            "private",
        )
        package = context.pass_b(
            pass_a, (source,), authorized_source_ids=frozenset({"private"}), consumer_id="runner", resource_plan_ref="plan:v1",
            redact_keys=frozenset({"TOKEN", "PASSWORD"}),
        )
        self.assertEqual(
            package.sources[0].data,
            {
                "token": "[REDACTED]",
                " token ": "[REDACTED]",
                "nested": [{"password": "[REDACTED]"}],
                "safe": "ok",
            },
        )

    def test_context_rejects_cyclic_or_excessively_deep_source_data(self):
        context = ContextOrchestrator()
        pass_a = context.pass_a("hello", {}, policy_ref="policy:v1")
        cyclic = {}
        cyclic["self"] = cyclic
        with self.assertRaises(ContractError):
            context.pass_b(
                pass_a,
                (self.source("cyclic", cyclic, "private"),),
                authorized_source_ids=frozenset({"cyclic"}),
                consumer_id="runner",
                resource_plan_ref="plan:v1",
            )

        too_deep = {}
        cursor = too_deep
        for _ in range(ContextOrchestrator.MAX_REDACTION_DEPTH + 1):
            child = {}
            cursor["child"] = child
            cursor = child
        with self.assertRaises(ContractError):
            context.pass_b(
                pass_a,
                (self.source("deep", too_deep, "private"),),
                authorized_source_ids=frozenset({"deep"}),
                consumer_id="runner",
                resource_plan_ref="plan:v1",
            )

    def test_context_rejects_expired_or_wrong_consumer_sources(self):
        context = ContextOrchestrator()
        now = datetime.now(timezone.utc)
        pass_a = context.pass_a("hello", {}, policy_ref="policy:v1")
        sources = (
            self.source("expired", {"value": 1}, "public", expires_at=now - timedelta(seconds=1)),
            self.source("wrong-consumer", {"value": 2}, "public", consumers=frozenset({"forge"})),
            self.source("allowed", {"value": 3}, "public", consumers=frozenset({"runner"})),
        )
        package = context.pass_b(
            pass_a,
            sources,
            authorized_source_ids=frozenset(source.source_id for source in sources),
            consumer_id="runner",
            resource_plan_ref="plan:v1",
            now=now,
        )
        self.assertEqual([source.source_id for source in package.sources], ["allowed"])
        self.assertEqual(package.sources[0].provenance, ("source:allowed",))

    def test_context_source_requires_aware_expiry_consumers_and_provenance(self):
        with self.assertRaises(ContractError):
            ContextSource("bad", {}, "public", datetime.now(), frozenset({"runner"}), ("source:bad",))
        with self.assertRaises(ContractError):
            ContextSource(
                "bad", {}, "public", datetime.now(timezone.utc) + timedelta(minutes=1), frozenset(), ("source:bad",)
            )
        with self.assertRaises(ContractError):
            ContextSource(
                "bad", {}, "public", datetime.now(timezone.utc) + timedelta(minutes=1), frozenset({"runner"}), ()
            )


if __name__ == "__main__":
    unittest.main()
