from __future__ import annotations

import unittest
from pathlib import Path

from jhoc.contracts.models import PluginType
from jhoc.intent.classifier import IntentClassifier
from jhoc.intent.schema import DetectionTier, IntentType
from jhoc.registry import CapabilityRegistry, VerificationStatus
from jhoc.shelf import SkillShelfLoader, SQLiteShelf

ROOT = Path(__file__).resolve().parent.parent


class TestSkillsShelfCompliance(unittest.TestCase):
    def setUp(self) -> None:
        self.skills_dir = ROOT / ".agents" / "skills"
        self.loader = SkillShelfLoader(self.skills_dir)
        self.classifier = IntentClassifier()

    def test_all_skills_discovered_and_valid_manifests(self) -> None:
        skills = self.loader.discover_skills()
        self.assertGreaterEqual(len(skills), 4, "Expected at least 4 registered skills")

        skill_names = {s.name for s in skills}
        expected_core = {
            "codex-plan-review",
            "counter-questioning-probe",
            "latent-space-activator",
            "paper-to-knowledge-distiller",
            "kaigong",
            "shougong",
            "post-task-shared-memory",
        }
        self.assertTrue(expected_core.issubset(skill_names), f"Missing core skills: {expected_core - skill_names}")

        for s in skills:
            self.assertTrue(s.version, f"Skill {s.name} missing version")
            self.assertTrue(s.category, f"Skill {s.name} missing category")
            self.assertTrue(s.description, f"Skill {s.name} missing description")
            self.assertGreaterEqual(len(s.triggers), 1, f"Skill {s.name} missing triggers")

            manifest = s.record.manifest
            self.assertEqual(manifest.plugin_type, PluginType.CAPABILITY)
            self.assertEqual(manifest.verification_status, "VERIFIED")
            self.assertTrue(manifest.shelf_eligible, f"Skill {s.name} must be shelf_eligible")
            self.assertTrue(manifest.runtime_selectable, f"Skill {s.name} must be runtime_selectable")
            self.assertFalse(manifest.mutable_by_agent, f"Skill {s.name} must not be mutable_by_agent")

    def test_shelf_admission_pipeline(self) -> None:
        registry = CapabilityRegistry()
        test_db = ROOT / "logs" / "test-shelf.sqlite"
        if test_db.exists():
            test_db.unlink()

        shelf = SQLiteShelf(str(test_db))
        try:
            admitted = self.loader.sync_to_shelf(registry, shelf)
            self.assertGreaterEqual(len(admitted), 7)

            # Assert all admitted entries are queryable
            shelf_entries = shelf.entries()
            self.assertEqual(len(shelf_entries), len(admitted))
            for entry in shelf_entries:
                self.assertEqual(entry.health, "HEALTHY")
                self.assertIsNotNone(shelf.get(entry.capability_id, entry.version))
        finally:
            shelf.close()
            if test_db.exists():
                test_db.unlink()

    def test_shelf_ledger_markdown_integrity(self) -> None:
        shelf_md = self.skills_dir / "SHELF.md"
        self.assertTrue(shelf_md.exists(), "SHELF.md must exist in .agents/skills")
        content = shelf_md.read_text(encoding="utf-8")
        self.assertIn("codex-plan-review", content)
        self.assertIn("counter-questioning-probe", content)
        self.assertIn("latent-space-activator", content)
        self.assertIn("paper-to-knowledge-distiller", content)
        self.assertIn("VERIFIED", content)

    def test_intent_classifier_routes_to_shelf_skills(self) -> None:
        # 1. Counter Questioning
        res1 = self.classifier.classify("开始制定新功能计划前，进行开工反问和方向校准")
        self.assertEqual(res1.intent, IntentType.COUNTER_QUESTIONING)
        self.assertEqual(res1.tier_hit, DetectionTier.TIER_1_RULE)
        self.assertIn("counter-questioning-probe", str(res1.enforced_scaffolding))

        # 2. Paper Distillation
        res2 = self.classifier.classify("请帮我研读这篇 arxiv.org 论文并去包装")
        self.assertEqual(res2.intent, IntentType.PAPER_DISTILLATION)
        self.assertEqual(res2.tier_hit, DetectionTier.TIER_1_RULE)
        self.assertIn("paper-to-knowledge-distiller", str(res2.enforced_scaffolding))

        # 3. Plan Review
        res3 = self.classifier.classify("在编码前执行规划评审和方案评审")
        self.assertEqual(res3.intent, IntentType.PLAN_REVIEW)
        self.assertEqual(res3.tier_hit, DetectionTier.TIER_1_RULE)
        self.assertIn("codex-plan-review", str(res3.enforced_scaffolding))

        # 4. Latent Space Activation
        res4 = self.classifier.classify("从第一性原理和仿生重构角度打破定式")
        self.assertEqual(res4.intent, IntentType.LATENT_SPACE_ACTIVATION)
        self.assertEqual(res4.tier_hit, DetectionTier.TIER_1_RULE)
        self.assertIn("latent-space-activator", str(res4.enforced_scaffolding))

        # 5. Kaigong
        res5 = self.classifier.classify("开工")
        self.assertEqual(res5.intent, IntentType.KAIGONG)
        self.assertEqual(res5.tier_hit, DetectionTier.TIER_1_RULE)
        self.assertIn("kaigong", str(res5.enforced_scaffolding))

        # 6. Shougong
        res6 = self.classifier.classify("/收工")
        self.assertEqual(res6.intent, IntentType.SHOUGONG)
        self.assertEqual(res6.tier_hit, DetectionTier.TIER_1_RULE)
        self.assertIn("shougong", str(res6.enforced_scaffolding))

        # 7. Post-task shared memory
        res7 = self.classifier.classify("任务收尾归档并持久化共享记忆")
        self.assertEqual(res7.intent, IntentType.POST_TASK_MEMORY)
        self.assertEqual(res7.tier_hit, DetectionTier.TIER_1_RULE)
        self.assertIn("post-task-shared-memory", str(res7.enforced_scaffolding))

    # =========================================================================
    # 可证伪反例与异常攻防测试 (Falsifiable Counterexample & Negative Tests)
    # =========================================================================

    def test_falsifiable_reject_unverified_skill_admission(self) -> None:
        """反例 1: 未通过安全审计的技能 (UNVERIFIED) 试图强行上架，必须被 Fail-Closed 拦截。"""
        from jhoc.contracts.errors import ContractError, ErrorCode
        from jhoc.contracts.models import PluginManifest, PluginType
        from jhoc.registry import CapabilityRecord, VerificationStatus
        from jhoc.shelf import Shelf

        unverified_manifest = PluginManifest(
            plugin_id="jhoc.skill.rogue",
            name="rogue-skill",
            version="1.0.0",
            protocol_version="1.0",
            plugin_type=PluginType.CAPABILITY,
            capabilities=("rogue_action",),
            verification_status="UNVERIFIED",
            shelf_eligible=True,
        )
        record = CapabilityRecord(
            capability_id="skill:rogue",
            version="1.0.0",
            manifest=unverified_manifest,
            input_schema_ref="schemas/work-item-1.0.json",
            output_schema_ref="schemas/work-result-1.0.json",
            verification_status=VerificationStatus.UNVERIFIED,
        )
        shelf = Shelf()
        with self.assertRaises(ContractError) as ctx:
            shelf.admit(record)
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)
        self.assertIn("only verified shelf-eligible capabilities may be admitted", str(ctx.exception))

    def test_falsifiable_reject_not_shelf_eligible_skill(self) -> None:
        """反例 2: 即使已 VERIFIED，若未标记 shelf_eligible: True，绝不得准入上架。"""
        from jhoc.contracts.errors import ContractError, ErrorCode
        from jhoc.contracts.models import PluginManifest, PluginType
        from jhoc.registry import CapabilityRecord, VerificationStatus
        from jhoc.shelf import Shelf

        ineligible_manifest = PluginManifest(
            plugin_id="jhoc.skill.internal_tool",
            name="internal_tool",
            version="1.0.0",
            protocol_version="1.0",
            plugin_type=PluginType.CAPABILITY,
            capabilities=("internal_cmd",),
            verification_status="VERIFIED",
            shelf_eligible=False,  # <--- 明确不可上架
        )
        record = CapabilityRecord(
            capability_id="skill:internal_tool",
            version="1.0.0",
            manifest=ineligible_manifest,
            input_schema_ref="schemas/work-item-1.0.json",
            output_schema_ref="schemas/work-result-1.0.json",
            verification_status=VerificationStatus.VERIFIED,
        )
        shelf = Shelf()
        with self.assertRaises(ContractError) as ctx:
            shelf.admit(record)
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)

    def test_falsifiable_reject_governance_plugin_in_shelf(self) -> None:
        """反例 3: 治理类特权插件 (GOVERNANCE) 严禁伪装成货架能力准入。"""
        from jhoc.contracts.errors import ContractError, ErrorCode
        from jhoc.contracts.models import PluginManifest, PluginType

        # 契约约束: GOVERNANCE 插件若声明 shelf_eligible: True，必须在构造阶段直接抛出 POLICY_DENIED
        with self.assertRaises(ContractError) as ctx:
            PluginManifest(
                plugin_id="jhoc.gov.privilege_escalation",
                name="privilege_escalation",
                version="1.0.0",
                protocol_version="1.0",
                plugin_type=PluginType.GOVERNANCE,
                capabilities=("override_guard",),
                verification_status="VERIFIED",
                shelf_eligible=True,  # <--- 治理插件严禁入架
            )
        self.assertEqual(ctx.exception.code, ErrorCode.POLICY_DENIED)
        self.assertIn("governance plugins cannot enter the capability shelf", str(ctx.exception))

    def test_falsifiable_negative_prompts_zero_noise_scaffolding(self) -> None:
        """反例 4: 无关指令与日常问答绝不产生误触，enforced_scaffolding 必须严格为 None。"""
        negative_prompts = [
            "写一个快速排序算法实现",
            "今天北京天气怎么样？",
            "将这个 JSON 字符串格式化输出",
            "计算 12345 乘以 67890",
            "帮我把这个英文单词翻译成中文",
        ]
        for prompt in negative_prompts:
            decision = self.classifier.classify(prompt)
            # 必须绝不误判为反问、论文或规划评审
            self.assertNotIn(
                decision.intent,
                {IntentType.COUNTER_QUESTIONING, IntentType.PAPER_DISTILLATION, IntentType.PLAN_REVIEW},
                f"Negative prompt '{prompt}' falsely triggered intent {decision.intent}",
            )
            # 严禁悬挂多余技能紧箍咒
            self.assertIsNone(
                decision.enforced_scaffolding,
                f"Negative prompt '{prompt}' produced unwanted scaffolding: {decision.enforced_scaffolding}",
            )

    def test_falsifiable_detect_uncatalogued_rogue_skill(self) -> None:
        """反例 5: 若磁盘上存在未在 SHELF.md 备案的黑户技能目录，合规巡检必须直接报错。"""
        import tempfile
        # 创建临时伪造的未备案技能
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_skills = Path(temp_dir)
            rogue_dir = temp_skills / "rogue-backdoor-skill"
            rogue_dir.mkdir()
            (rogue_dir / "SKILL.md").write_text(
                "---\nname: rogue-backdoor-skill\nversion: 0.0.1\ncategory: exploit\n---\n# Rogue",
                encoding="utf-8"
            )
            # 建立一个不含该黑户技能的 SHELF.md
            (temp_skills / "SHELF.md").write_text("# Shelf Ledger\n| legal-skill |", encoding="utf-8")

            # 执行合规巡检探针
            loader = SkillShelfLoader(temp_skills)
            discovered = loader.discover_skills()
            shelf_content = (temp_skills / "SHELF.md").read_text(encoding="utf-8")

            unregistered = [s.name for s in discovered if s.name not in shelf_content]
            # 核心证伪断言: 必须能抓出黑户技能！
            self.assertEqual(unregistered, ["rogue-backdoor-skill"])


if __name__ == "__main__":
    unittest.main()
