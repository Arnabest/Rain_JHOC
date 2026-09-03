from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.guard.path import PathAccessMode, PathGuard


class TestPathGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_safe_workspace_file_allowed(self) -> None:
        safe_file = self.workspace / "project" / "main.py"
        evaluated = PathGuard.evaluate(safe_file, self.workspace, PathAccessMode.READ)
        self.assertEqual(evaluated, safe_file.resolve())

    def test_path_traversal_escape_denied(self) -> None:
        escape_path = self.workspace / ".." / "outside_file.txt"
        with self.assertRaises(ContractError) as ctx:
            PathGuard.evaluate(escape_path, self.workspace, PathAccessMode.READ)
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)
        self.assertIn("escapes workspace root", str(ctx.exception))

    def test_sensitive_ssh_key_denied(self) -> None:
        sensitive = self.workspace / ".ssh" / "id_rsa"
        with self.assertRaises(ContractError) as ctx:
            PathGuard.evaluate(sensitive, self.workspace, PathAccessMode.READ)
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)
        self.assertIn("access to sensitive asset denied", str(ctx.exception))

    def test_sensitive_env_file_denied(self) -> None:
        env_file = self.workspace / ".env"
        with self.assertRaises(ContractError) as ctx:
            PathGuard.evaluate(env_file, self.workspace, PathAccessMode.WRITE)
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)
        self.assertIn("access to sensitive asset denied", str(ctx.exception))

    def test_sensitive_credentials_denied(self) -> None:
        creds = self.workspace / "config" / "credentials.yaml"
        with self.assertRaises(ContractError) as ctx:
            PathGuard.evaluate(creds, self.workspace, PathAccessMode.READ)
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)
        self.assertIn("access to sensitive asset denied", str(ctx.exception))

    def test_sensitive_private_key_extension_denied(self) -> None:
        pem_file = self.workspace / "certs" / "server.key"
        with self.assertRaises(ContractError) as ctx:
            PathGuard.evaluate(pem_file, self.workspace, PathAccessMode.READ)
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

    def test_empty_arguments_denied(self) -> None:
        with self.assertRaises(ContractError) as ctx:
            PathGuard.evaluate("", self.workspace)
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)


if __name__ == "__main__":
    unittest.main()
