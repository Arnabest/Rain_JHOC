import json
from copy import deepcopy
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.contracts import (  # noqa: E402
    MessageEnvelope,
    PluginManifest,
    ResultStatus,
    WorkItem,
    WorkResult,
)


def validate(schema_name: str, instance: dict) -> None:
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)


class SchemaCompatibilityTests(unittest.TestCase):
    def test_models_serialize_to_their_public_schemas(self):
        task_id = uuid4()
        item = WorkItem(task_id, "contract.validate", {"value": 1}, "once-1")
        result = WorkResult(task_id, item.work_id, ResultStatus.SUCCEEDED)
        envelope = MessageEnvelope("event", "task.completed", "contracts", result.to_dict(), task_id)
        manifest = PluginManifest("local.echo", "Local Echo", "1.0.0", "1.0", "capability")

        validate("work-item-1.0.json", item.to_dict())
        validate("work-result-1.0.json", result.to_dict())
        validate("message-envelope-1.0.json", envelope.to_dict())
        validate("plugin-manifest-1.0.json", manifest.to_dict())

    def test_schemas_reject_version_shape_governance_and_side_effect_violations(self):
        task_id = uuid4()
        item = WorkItem(task_id, "contract.validate", {"value": 1}, "once-1").to_dict()
        result = WorkResult(task_id, item["work_id"], ResultStatus.SUCCEEDED).to_dict()
        envelope = MessageEnvelope("event", "task.completed", "contracts", result, task_id).to_dict()
        manifest = PluginManifest("local.echo", "Local Echo", "1.0.0", "1.0", "capability").to_dict()

        cases = []
        value = deepcopy(item); value["schema_version"] = "2.0"; cases.append(("work-item-1.0.json", value))
        value = deepcopy(item); value["task_id"] = "not-a-uuid"; cases.append(("work-item-1.0.json", value))
        value = deepcopy(item); value["unexpected"] = True; cases.append(("work-item-1.0.json", value))
        value = deepcopy(result); value["side_effect_state"] = "UNKNOWN_SIDE_EFFECT"; value["error_code"] = None; cases.append(("work-result-1.0.json", value))
        value = deepcopy(envelope); value["message_type"] = "control"; cases.append(("message-envelope-1.0.json", value))
        value = deepcopy(manifest); value["version"] = "latest"; cases.append(("plugin-manifest-1.0.json", value))
        value = deepcopy(manifest); value.update({"plugin_type": "governance", "shelf_eligible": True}); cases.append(("plugin-manifest-1.0.json", value))

        for schema_name, value in cases:
            with self.subTest(schema=schema_name, value=value), self.assertRaises(ValidationError):
                validate(schema_name, value)


if __name__ == "__main__":
    unittest.main()
