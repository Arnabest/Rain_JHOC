import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from jhoc.contracts import (
    ContractError,
    MessageEnvelope,
    PluginManifest,
    PluginType,
    ResultStatus,
    SideEffectState,
    WorkItem,
    WorkResult,
)


class ContractModelTests(unittest.TestCase):
    def test_work_item_serializes_stable_native_fields(self):
        item = WorkItem(uuid4(), "contract.validate", {"value": 1}, "once-1")
        value = item.to_dict()
        self.assertEqual(value["schema_version"], "1.0")
        self.assertEqual(value["idempotency_key"], "once-1")

    def test_unknown_side_effect_requires_reconciliation_signal(self):
        with self.assertRaises(ContractError):
            WorkResult(
                uuid4(),
                uuid4(),
                ResultStatus.FAILED,
                SideEffectState.UNKNOWN_SIDE_EFFECT,
            )

    def test_governance_plugin_is_default_denied(self):
        manifest = PluginManifest("guard", "JHOC Guard", "1.0.0", "1.0", PluginType.GOVERNANCE)
        self.assertFalse(manifest.shelf_eligible)
        with self.assertRaises(ContractError):
            PluginManifest("guard", "JHOC Guard", "1.0.0", "1.0", PluginType.GOVERNANCE, shelf_eligible=True)

    def test_message_envelope_has_correlation(self):
        envelope = MessageEnvelope("event", "telemetry.contract", "contracts", {}, uuid4())
        self.assertEqual(envelope.to_dict()["message_type"], "event")


if __name__ == "__main__":
    unittest.main()
