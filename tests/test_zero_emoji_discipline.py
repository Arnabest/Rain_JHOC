from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.context.sanitizer import DataSanitizer


class TestZeroEmojiDiscipline(unittest.TestCase):
    _EMOJI_PATTERN = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]")

    def test_agents_md_and_rules_contain_zero_emojis(self) -> None:
        """断言 AGENTS.md, .agents/rules/*.md, docs/lessons/*.md 中绝无任何 Emoji 字符。"""
        scan_files: list[Path] = [ROOT / "AGENTS.md"]
        scan_files.extend((ROOT / ".agents" / "rules").glob("*.md"))
        scan_files.extend((ROOT / "docs" / "lessons").glob("*.md"))

        violations: list[str] = []
        for file_path in scan_files:
            if not file_path.exists():
                continue
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            matches = self._EMOJI_PATTERN.findall(content)
            if matches:
                violations.append(f"{file_path.relative_to(ROOT)}: found {len(matches)} emojis -> {set(matches)}")

        self.assertEqual(violations, [], f"Found emoji discipline violations in constitutional files: {violations}")

    def test_agents_md_indexes_rule_7(self) -> None:
        agents_md = ROOT / "AGENTS.md"
        content = agents_md.read_text(encoding="utf-8")
        self.assertIn("zero-emoji-discipline.md", content)
        self.assertIn("### 7. 零 Emoji 表情与字符纯度法则", content)

    def test_rule_file_and_lesson_148_exist(self) -> None:
        rule_file = ROOT / ".agents" / "rules" / "zero-emoji-discipline.md"
        self.assertTrue(rule_file.is_file(), "zero-emoji-discipline.md must exist")

        lesson_file = ROOT / "docs" / "lessons" / "03-tool-and-storage.md"
        content = lesson_file.read_text(encoding="utf-8")
        self.assertIn("LESSON #148", content)
        self.assertIn("Zero-Emoji Discipline", content)

    def test_data_sanitizer_physically_strips_emojis(self) -> None:
        """断言 DataSanitizer 在数据清洗层物理滤除 Emoji，并记录审计标记。"""
        tainted_text = "系统执行报告：[状态] 🟢 成功，请查看 👉 详情日志 💡"
        cleaned, flags = DataSanitizer.sanitize_text(tainted_text)

        # 检查 Emoji 已被完全剔除
        self.assertNotIn("🟢", cleaned)
        self.assertNotIn("👉", cleaned)
        self.assertNotIn("💡", cleaned)
        self.assertIn("stripped_3_emoji_characters", flags)


if __name__ == "__main__":
    unittest.main()
