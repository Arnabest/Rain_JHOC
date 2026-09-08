import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.contracts import ContractError, PluginManifest  # noqa: E402
from jhoc.registry import CapabilityRecord, CapabilityRegistry, SQLiteCapabilityRegistry, VerificationStatus  # noqa: E402
from jhoc.shelf import Shelf, SQLiteShelf  # noqa: E402
from jhoc.quota import HardwareState, QuotaManager, ResourcePlan, SQLiteQuotaManager  # noqa: E402


class RegistryShelfQuotaTests(unittest.TestCase):
    def record(self, eligible=True):
        manifest = PluginManifest("cap.echo", "Echo", "1.0.0", "1.0", "capability", verification_status="VERIFIED", shelf_eligible=eligible)
        return CapabilityRecord("echo", "1.0.0", manifest, "schema:in", "schema:out")

    def test_registry_verification_and_shelf_admission(self):
        registry = CapabilityRegistry()
        record = self.record()
        registry.register(record)
        with self.assertRaises(ContractError):
            Shelf().admit(record)
        verified = registry.verify("echo", "1.0.0", health="HEALTHY")
        shelf = Shelf()
        shelf.admit(verified)
        self.assertEqual(shelf.get("echo", "1.0.0").health, "HEALTHY")

    def test_non_eligible_capability_is_rejected(self):
        registry = CapabilityRegistry()
        registry.register(self.record(eligible=False))
        verified = registry.verify("echo", "1.0.0")
        with self.assertRaises(ContractError):
            Shelf().admit(verified)

    def test_quota_enforces_capacity_and_expiry(self):
        capacity = ResourcePlan(cpu_units=2, memory_mb=512, token_budget=1000, max_concurrency=2, max_seconds=10)
        quota = QuotaManager(capacity)
        lease = quota.acquire("task-1", ResourcePlan(cpu_units=1, memory_mb=256, token_budget=600, max_concurrency=1, max_seconds=1))
        with self.assertRaises(ContractError):
            quota.acquire("task-2", ResourcePlan(cpu_units=2, memory_mb=256, token_budget=500, max_concurrency=1, max_seconds=1))
        quota.release(lease.lease_id)
        quota.acquire("task-2", ResourcePlan(cpu_units=2, memory_mb=256, token_budget=500, max_concurrency=1, max_seconds=1))

    def test_revoked_capability_never_remains_verified(self):
        registry = CapabilityRegistry()
        registry.register(self.record())
        registry.verify("echo", "1.0.0")
        revoked = registry.revoke("echo", "1.0.0")
        self.assertEqual(revoked.verification_status, VerificationStatus.REVOKED)

    def test_quota_hardware_constraints_fail_closed_until_state_is_explicit(self):
        quota = QuotaManager(ResourcePlan(cpu_units=2, memory_mb=512, token_budget=1000, max_concurrency=2))
        network_plan = ResourcePlan(token_budget=100, requires_network=True)
        with self.assertRaises(ContractError):
            quota.acquire("network-task", network_plan)
        quota.set_hardware_state(HardwareState(temperature_c=82, power_watts=140, battery_percent=20, network_available=True))
        hot_plan = ResourcePlan(token_budget=100, max_temperature_c=75)
        with self.assertRaises(ContractError):
            quota.acquire("hot-task", hot_plan)
        power_plan = ResourcePlan(token_budget=100, max_power_watts=100)
        with self.assertRaises(ContractError):
            quota.acquire("power-task", power_plan)
        low_battery_plan = ResourcePlan(token_budget=100, min_battery_percent=30)
        with self.assertRaises(ContractError):
            quota.acquire("battery-task", low_battery_plan)
        quota.set_hardware_state(HardwareState(temperature_c=55, power_watts=80, battery_percent=90, network_available=True))
        lease = quota.acquire("network-task", network_plan)
        self.assertEqual(lease.owner, "network-task")

    def test_quota_accounts_usage_without_allowing_budget_overrun(self):
        quota = QuotaManager(ResourcePlan(token_budget=1000))
        lease = quota.acquire("usage-task", ResourcePlan(token_budget=100))
        self.assertEqual(quota.record_usage(lease.lease_id, tokens_used=60).tokens_used, 60)
        with self.assertRaises(ContractError):
            quota.record_usage(lease.lease_id, tokens_used=41)
        self.assertEqual(quota.usage(lease.lease_id).tokens_used, 60)

    def test_durable_registry_shelf_and_quota_coordinate_across_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "capabilities.db")
            registry = SQLiteCapabilityRegistry(path)
            registry.register(self.record())
            verified = registry.verify("echo", "1.0.0", health="HEALTHY")
            shelf = SQLiteShelf(path)
            shelf.admit(verified)

            capacity = ResourcePlan(cpu_units=1, memory_mb=256, token_budget=100, max_concurrency=1)
            first = SQLiteQuotaManager(path, capacity)
            second = SQLiteQuotaManager(path, capacity)
            now = datetime.now(timezone.utc)
            lease = first.acquire(
                "first", ResourcePlan(cpu_units=1, memory_mb=128, token_budget=50, max_concurrency=1, max_seconds=1), now=now
            )
            with self.assertRaises(ContractError):
                second.acquire(
                    "second", ResourcePlan(cpu_units=1, memory_mb=128, token_budget=50, max_concurrency=1), now=now
                )
            replacement = second.acquire(
                "second", ResourcePlan(cpu_units=1, memory_mb=128, token_budget=50, max_concurrency=1), now=now + timedelta(seconds=2)
            )
            second.record_usage(replacement.lease_id, tokens_used=30)
            first.close(); second.close(); registry.close(); shelf.close()

            registry = SQLiteCapabilityRegistry(path)
            shelf = SQLiteShelf(path)
            quota = SQLiteQuotaManager(path, capacity)
            self.assertEqual(registry.get("echo", "1.0.0").verification_status, VerificationStatus.VERIFIED)
            self.assertEqual(shelf.get("echo", "1.0.0").health, "HEALTHY")
            self.assertEqual(quota.usage(replacement.lease_id).tokens_used, 30)
            self.assertEqual([item.owner for item in quota.active()], ["second"])
            self.assertIsNone(quota.usage(lease.lease_id))
            quota.close(); registry.close(); shelf.close()


if __name__ == "__main__":
    unittest.main()
