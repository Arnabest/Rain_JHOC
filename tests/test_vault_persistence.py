from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.guard.vault import CredentialVault
from jhoc.contracts.errors import ContractError, ErrorCode


class TestVaultPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jhoc_vault_test_"))
        self.vault_file = self.temp_dir / "test_vault.bin"

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_vault_encrypted_persistence_and_reloading(self) -> None:
        # 1. First instance: register secrets with persistence
        vault1 = CredentialVault(persistence_path=self.vault_file)
        ref1 = vault1.register_secret("TEST_API_KEY", "sk-secret-12345")
        ref2 = vault1.register_secret("GITHUB_TOKEN", "ghp_secure_67890")

        self.assertTrue(self.vault_file.is_file(), "Vault binary file must be created")
        raw_bytes = self.vault_file.read_bytes()
        self.assertNotIn(b"sk-secret-12345", raw_bytes, "Raw secret must NOT appear in encrypted binary")
        self.assertNotIn(b"ghp_secure_67890", raw_bytes, "Raw secret must NOT appear in encrypted binary")

        # 2. Second instance: loads from persistence file
        vault2 = CredentialVault(persistence_path=self.vault_file)
        self.assertEqual(vault2.list_secrets(), ["GITHUB_TOKEN", "TEST_API_KEY"])
        self.assertEqual(vault2.get_token_ref("TEST_API_KEY"), ref1)

        # 3. Resolve for authorized egress
        resolved = vault2.resolve_for_egress(ref1, "adapter.science")
        self.assertEqual(resolved, "sk-secret-12345")

        # 4. Resolve denied for unauthorized actor
        with self.assertRaises(ContractError) as ctx:
            vault2.resolve_for_egress(ref1, "malicious.agent")
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

    def test_vault_masking_protects_logs(self) -> None:
        vault = CredentialVault()
        vault.register_secret("CUSTOM_KEY", "super_secret_payload_xyz")
        text = "Calling API with authorization: super_secret_payload_xyz in header"
        masked = vault.mask_text(text)
        self.assertNotIn("super_secret_payload_xyz", masked)
        self.assertIn("[VAULT_MASKED:CUSTOM_KEY]", masked)


if __name__ == "__main__":
    unittest.main()
