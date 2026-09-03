from __future__ import annotations

from pathlib import Path
import unittest

from jhoc.intent import IntentClassifier, IntentEnforcer, IntentType

ROOT = Path(__file__).resolve().parents[1]


class TestCognitiveProtocol(unittest.TestCase):
    def setUp(self) -> None:
        self.rule_path = ROOT / ".agents" / "rules" / "cognitive-tier0-protocol.md"
        self.agents_md = ROOT / "AGENTS.md"
        self.classifier = IntentClassifier()
        self.enforcer = IntentEnforcer(self.classifier)

    def test_rule_file_exists_and_has_tier_0(self) -> None:
        self.assertTrue(self.rule_path.is_file())
        content = self.rule_path.read_text(encoding="utf-8")
        self.assertIn("蒸馏三问 + 批判性反问", content)
        self.assertIn("问 1（层 1：统计素材）", content)
        self.assertIn("问 2（层 2：抽象原则）", content)
        self.assertIn("问 3（层 3：推导判断）", content)
        self.assertIn("批判性反问", content)
        self.assertIn("Anti-Sycophancy", content)
        self.assertIn("LESSONS #147", content)

    def test_agents_md_indexes_rule_0(self) -> None:
        content = self.agents_md.read_text(encoding="utf-8")
        self.assertIn("cognitive-tier0-protocol.md", content)
        self.assertIn("### 0. 元认知蒸馏与反顺从法则 (Rule 0)", content)

    def test_paper_url_triggers_cognitive_guard_scaffolding(self) -> None:
        paper_prompt = "读一读这篇：https://arxiv.org/abs/2608.27454 WikiSkill 论文"
        payload = self.enforcer.enforce(paper_prompt)

        self.assertTrue(payload.was_transformed)
        self.assertEqual(payload.decision.intent, IntentType.LATENT_SPACE_ACTIVATION)
        self.assertIn("【0. 显式前置：蒸馏三问 + 批判性反问 (强制置顶输出)】", payload.effective_prompt)
        self.assertIn("问 1（层 1 统计素材）", payload.effective_prompt)
        self.assertIn("问 2（层 2 抽象原则）", payload.effective_prompt)
        self.assertIn("问 3（层 3 推导判断）", payload.effective_prompt)
        self.assertIn("批判性反问", payload.effective_prompt)
        self.assertIn("LESSONS #147", payload.effective_prompt)


if __name__ == "__main__":
    unittest.main()
