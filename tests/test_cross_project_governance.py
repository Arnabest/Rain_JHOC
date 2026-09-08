from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc_hook_gate import evaluate_payload
from jhoc_kaigong import check_workspace, run_kaigong
from jhoc_provision import provision_workspace


class TestCrossProjectGovernance(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jhoc_test_proj_"))

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        graph_db = ROOT / "logs" / "p19-graph.sqlite"
        if graph_db.is_file():
            import sqlite3
            with sqlite3.connect(graph_db) as conn:
                conn.execute("DELETE FROM jhoc_graph_relation WHERE source_node LIKE 'project:jhoc_test_proj_%'")
                conn.execute("DELETE FROM jhoc_graph_node WHERE node_id LIKE 'project:jhoc_test_proj_%'")

    def test_jhoc_provision_external_project_end_to_end(self) -> None:
        # Step 1: Provision project under JHOC
        exit_code = provision_workspace(self.temp_dir)
        self.assertEqual(exit_code, 0)

        # Step 2: Verify artifacts
        hooks_file = self.temp_dir / ".agents" / "hooks.json"
        agents_md = self.temp_dir / "AGENTS.md"
        claude_md = self.temp_dir / "CLAUDE.md"

        self.assertTrue(hooks_file.is_file(), "hooks.json must exist in target project")
        self.assertTrue(agents_md.is_file(), "AGENTS.md must exist in target project")
        self.assertTrue(claude_md.is_file(), "CLAUDE.md must exist in target project")

        # Step 3: Verify dynamic kaigong workspace check
        ok, msg = check_workspace(self.temp_dir)
        self.assertTrue(ok, f"check_workspace failed for external project: {msg}")

        # Step 4: Run kaigong against external project
        k_code = run_kaigong("External Project Init", workspace=self.temp_dir)
        self.assertEqual(k_code, 0)

        # Step 5: Verify Hook Gate protects external project
        clean_payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(self.temp_dir / "main.py"),
                    "CodeContent": "def add(a, b): return a + b",
                },
            },
            "workspacePaths": [str(self.temp_dir)],
        }
        res_clean = evaluate_payload(clean_payload)
        self.assertEqual(res_clean["decision"], "allow")

        # Step 6: Verify Hook Gate denies Emoji in external project
        emoji_payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(self.temp_dir / "main.py"),
                    "CodeContent": "def add(a, b): return a + b  # \U0001f600",
                },
            },
            "workspacePaths": [str(self.temp_dir)],
        }
        res_emoji = evaluate_payload(emoji_payload)
        self.assertEqual(res_emoji["decision"], "deny")
        self.assertIn("Rule 7 Violation", res_emoji["reason"])

        # Step 7: Verify Hook Gate denies out of boundary escape
        escape_payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "C:\\Windows\\System32\\escape.dll",
                    "CodeContent": "dangerous",
                },
            },
            "workspacePaths": [str(self.temp_dir)],
        }
        res_escape = evaluate_payload(escape_payload)
        self.assertEqual(res_escape["decision"], "deny")
        self.assertIn("Rule 5 Violation", res_escape["reason"])

    def test_global_skills_json_contains_jhoc(self) -> None:
        global_skills = Path.home() / ".gemini" / "config" / "skills.json"
        self.assertTrue(global_skills.is_file())
        data = json.loads(global_skills.read_text(encoding="utf-8"))
        paths = [e.get("path") for e in data.get("entries", [])]
        self.assertTrue(any("JHOC" in p for p in paths), f"JHOC missing from global skills: {paths}")

    def test_claude_and_codex_globals_anchor_jhoc(self) -> None:
        claude_md = Path.home() / ".claude" / "CLAUDE.md"
        codex_md = Path.home() / ".codex" / "AGENTS.md"

        self.assertTrue(claude_md.is_file())
        self.assertTrue(codex_md.is_file())

        claude_txt = claude_md.read_text(encoding="utf-8")
        codex_txt = codex_md.read_text(encoding="utf-8")

        self.assertIn("JHOC Constitution", claude_txt)
        self.assertIn("JHOC Constitution", codex_txt)
        self.assertIn("jhoc_kaigong.py", claude_txt)
        self.assertIn("jhoc_kaigong.py", codex_txt)


if __name__ == "__main__":
    unittest.main()
