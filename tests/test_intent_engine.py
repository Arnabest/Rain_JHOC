from __future__ import annotations

import json
from pathlib import Path
import unittest
import jsonschema

from jhoc.intent import DetectionTier, IntentClassifier, IntentDecision, IntentEnforcer, IntentType

ROOT = Path(__file__).resolve().parents[1]


class TestIntentEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = IntentClassifier()
        self.enforcer = IntentEnforcer(self.classifier)
        schema_doc = json.loads((ROOT / "schemas" / "intent-decision-1.0.json").read_text(encoding="utf-8"))
        self.schema = schema_doc

    def test_tier_1_explicit_command_trigger(self) -> None:
        decision = self.classifier.classify("请帮我进行 $latent 范式推演")
        self.assertEqual(decision.intent, IntentType.LATENT_SPACE_ACTIVATION)
        self.assertEqual(decision.tier_hit, DetectionTier.TIER_1_RULE)
        self.assertEqual(decision.confidence, 1.0)
        self.assertIn("$latent", decision.matched_keywords)
        self.assertTrue(len(decision.banned_tokens) > 0)

    def test_tier_1_anti_cliche_trigger(self) -> None:
        decision = self.classifier.classify("别说套话，从第一性原理给我重构这套分布式算法")
        self.assertEqual(decision.intent, IntentType.LATENT_SPACE_ACTIVATION)
        self.assertEqual(decision.tier_hit, DetectionTier.TIER_1_RULE)
        self.assertGreaterEqual(decision.confidence, 0.95)

    def test_tier_1_security_audit_trigger(self) -> None:
        decision = self.classifier.classify("检查该插件是否存在提权漏洞和 token_guard 绕过风险")
        self.assertEqual(decision.intent, IntentType.SECURITY_AUDIT)
        self.assertEqual(decision.tier_hit, DetectionTier.TIER_1_RULE)

    def test_tier_1_engineering_fault_trigger(self) -> None:
        decision = self.classifier.classify("线上组件突发 OOM crash，请根据 traceback 进行故障诊断与代码修复")
        self.assertEqual(decision.intent, IntentType.DETERMINISTIC_ENGINEERING)
        self.assertEqual(decision.tier_hit, DetectionTier.TIER_1_RULE)

    def test_tier_2_metric_topology_overlap(self) -> None:
        # 即使没有 Tier 1 的显式禁令词，但高频出现生物/物理/控制论词汇，由 Tier 2 捕获
        decision = self.classifier.classify("基于生物趋化性扩散和李雅普诺夫自愈函数的局部差分方程推导")
        self.assertEqual(decision.intent, IntentType.LATENT_SPACE_ACTIVATION)
        self.assertEqual(decision.tier_hit, DetectionTier.TIER_2_METRIC)
        self.assertGreaterEqual(decision.confidence, 0.70)

    def test_general_conversation_fallback(self) -> None:
        decision = self.classifier.classify("今天周几？")
        self.assertEqual(decision.intent, IntentType.GENERAL_CONVERSATION)
        self.assertEqual(decision.tier_hit, DetectionTier.FALLBACK)

    def test_enforcer_physical_pre_injection(self) -> None:
        raw_prompt = "设计一套异构多智能体的自愈架构，跳出套路和常规定式"
        payload = self.enforcer.enforce(raw_prompt)

        self.assertTrue(payload.was_transformed)
        self.assertEqual(payload.decision.intent, IntentType.LATENT_SPACE_ACTIVATION)
        self.assertIn("【JHOC 外部前置安检门禁：已物理装配 LATENT_SPACE_ACTIVATOR 算子】", payload.effective_prompt)
        self.assertIn("1. [负向阻断]", payload.effective_prompt)
        self.assertIn("2. [异构同构锚定]", payload.effective_prompt)
        self.assertIn("3. [动力学方程契约]", payload.effective_prompt)
        self.assertIn("4. [代码与死穴拷问]", payload.effective_prompt)
        self.assertTrue(payload.effective_prompt.startswith(raw_prompt))

    def test_enforcer_leaves_normal_prompts_intact(self) -> None:
        normal_prompt = "请帮我写一个简单的字符串反转函数"
        payload = self.enforcer.enforce(normal_prompt)
        self.assertFalse(payload.was_transformed)
        self.assertEqual(payload.effective_prompt, normal_prompt)

    def test_json_schema_conformance(self) -> None:
        decision = self.classifier.classify("请用 $latent 方式重构")
        payload = self.enforcer.enforce("请用 $latent 方式重构")
        data = payload.decision.to_dict()
        
        # 严格验证是否符合 schemas/intent-decision-1.0.json 契约
        jsonschema.validate(instance=data, schema=self.schema)
        self.assertEqual(data["schema_version"], "1.0")
        self.assertEqual(data["intent"], "LATENT_SPACE_ACTIVATION")


if __name__ == "__main__":
    unittest.main()
