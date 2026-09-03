from __future__ import annotations

import unittest

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.guard.vault import CredentialVault


class TestCredentialVault(unittest.TestCase):
    def setUp(self) -> None:
        self.vault = CredentialVault()
        self.secret_val = "sk-live-secret-999888777"
        self.token_ref = self.vault.register_secret("deepseek_key", self.secret_val)

    def test_register_secret_returns_opaque_token(self) -> None:
        self.assertTrue(self.token_ref.startswith("vault://secret/deepseek_key#"))
        self.assertNotIn(self.secret_val, self.token_ref)
        self.assertTrue(CredentialVault.is_vault_ref(self.token_ref))

    def test_authorized_egress_can_dereference(self) -> None:
        dereferenced = self.vault.resolve_for_egress(self.token_ref, "adapter.http_client")
        self.assertEqual(dereferenced, self.secret_val)

        dereferenced_relay = self.vault.resolve_for_egress(self.token_ref, "relay.network_sink")
        self.assertEqual(dereferenced_relay, self.secret_val)

    def test_unauthorized_actor_cannot_dereference(self) -> None:
        # Context orchestrator or agent model cannot peek at raw keys
        with self.assertRaises(ContractError) as ctx:
            self.vault.resolve_for_egress(self.token_ref, "model.chat_agent")
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

        with self.assertRaises(ContractError) as ctx:
            self.vault.resolve_for_egress(self.token_ref, "context.snapshot")
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

    def test_unknown_token_rejected(self) -> None:
        with self.assertRaises(ContractError) as ctx:
            self.vault.resolve_for_egress("vault://secret/unknown#1234", "adapter.http")
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

    def test_mask_text_redacts_raw_secrets(self) -> None:
        leak_attempt = f"System prompt debug info: key is {self.secret_val} in environment"
        masked = self.vault.mask_text(leak_attempt)
        self.assertNotIn(self.secret_val, masked)
        self.assertIn("[VAULT_MASKED:deepseek_key]", masked)


if __name__ == "__main__":
    unittest.main()
