from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc_skill_gate import audit_skill, promote_skill_to_shelf, scan_candidate_skills


class TestSkillGate(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jhoc_skill_test_"))

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scan_candidate_skills_in_jhoc(self) -> None:
        skills = scan_candidate_skills(ROOT)
        self.assertGreaterEqual(len(skills), 7)
        self.assertTrue(all(s.is_on_shelf for s in skills))

    def test_scan_candidate_skills_in_external_project(self) -> None:
        ext_skill = self.temp_dir / ".agents" / "skills" / "my-custom-tool"
        ext_skill.mkdir(parents=True, exist_ok=True)
        (ext_skill / "SKILL.md").write_text(
            "---\nname: my-custom-tool\nversion: 1.0.0\ndescription: Custom\ntrigger: ['test']\n---\n# Tool\n```bash\npython tool.py\n```",
            encoding="utf-8",
        )
        candidates = scan_candidate_skills(self.temp_dir)
        self.assertEqual(len(candidates), 1)
        self.assertFalse(candidates[0].is_on_shelf)
        self.assertEqual(candidates[0].name, "my-custom-tool")

    def test_audit_skill_clean_passes(self) -> None:
        valid_skill = self.temp_dir / "valid-skill"
        valid_skill.mkdir(parents=True, exist_ok=True)
        (valid_skill / "SKILL.md").write_text(
            "---\nname: valid-skill\nversion: 1.0.0\ncategory: tooling\ndescription: Valid tool\ntrigger: ['valid']\nwhen_to_use: ['always']\n---\n# Valid\n```python\ndef run(): pass\n```",
            encoding="utf-8",
        )
        ok, violations = audit_skill(valid_skill)
        self.assertTrue(ok, f"Audit failed unexpectedly: {violations}")

    def test_audit_skill_emoji_denied(self) -> None:
        emoji_skill = self.temp_dir / "emoji-skill"
        emoji_skill.mkdir(parents=True, exist_ok=True)
        (emoji_skill / "SKILL.md").write_text(
            "---\nname: emoji-skill\nversion: 1.0.0\ncategory: tooling\ndescription: Has \U0001f600\ntrigger: ['emoji']\nwhen_to_use: ['always']\n---\n# Emoji\n```python\npass\n```",
            encoding="utf-8",
        )
        ok, violations = audit_skill(emoji_skill)
        self.assertFalse(ok)
        self.assertTrue(any("Rule 7 Violation" in v for v in violations))

    def test_audit_skill_dangerous_ast_denied(self) -> None:
        danger_skill = self.temp_dir / "danger-skill"
        danger_skill.mkdir(parents=True, exist_ok=True)
        (danger_skill / "SKILL.md").write_text(
            "---\nname: danger-skill\nversion: 1.0.0\ncategory: tooling\ndescription: Danger\ntrigger: ['danger']\nwhen_to_use: ['always']\n---\n# Danger\n```python\npass\n```",
            encoding="utf-8",
        )
        (danger_skill / "exploit.py").write_text("import os\neval('1 + 1')", encoding="utf-8")
        ok, violations = audit_skill(danger_skill)
        self.assertFalse(ok)
        self.assertTrue(any("AST Safety Violation" in v for v in violations))


if __name__ == "__main__":
    unittest.main()
