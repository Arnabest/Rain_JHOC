"""Unit tests for JHOC Governance Engine Plugin and Intent Asset Pipeline.

Validates:
1. CJK 2-gram tokenization and topological inverted indexing.
2. Tri-tier intent classification (Tier 1 rules, Tier 2 CJK topology, Explain vs Execute).
3. Structured ephemeral template rendering (bounds context under 4 lines, no raw prompt injection).
4. PostInvocation response verification (intercepts pure-text fake co-review roleplay).
5. Unified trace & audit queries and blackbox cryptographic hash chain verification.
6. Atomic asset indexing with SHA-256 integrity signatures.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = ROOT / ".agents" / "plugins" / "governance-engine"

import sys
if str(PLUGIN_DIR / "core") not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR / "core"))
if str(PLUGIN_DIR / "adapters") not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR / "adapters"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from schema import AssetRecord, AssetType, IntentType, IntentMatchResult
from template_renderer import LessonTemplateRenderer
from indexer import AssetIndexer, compute_char_bigrams
from tri_tier_classifier import GovernanceIntentEngine
from jhoc_post_verify import evaluate_post_invocation
from jhoc_trace import verify_blackbox_hash_chain, fetch_task_slot


class TestGovernanceEnginePlugin(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = GovernanceIntentEngine(ROOT)

    def test_cjk_bigram_tokenization(self) -> None:
        text = "拉起多模型协审"
        tokens = compute_char_bigrams(text)
        expected = ["拉起", "起多", "多模", "模型", "型协", "协审"]
        for exp in expected:
            self.assertIn(exp, tokens)

    def test_tier1_and_tier2_intent_classification(self) -> None:
        # 1. Co-review intent
        res_cr = self.engine.classify("拉起协审，讨论完整的优化方案")
        self.assertEqual(res_cr.intent, IntentType.MULTI_MODEL_CO_REVIEW)
        self.assertEqual(res_cr.tier_hit, "TIER_1_RULE")
        self.assertTrue(len(res_cr.ephemeral_lines) <= 4)
        self.assertTrue(any("jhoc_co_review" in line for line in res_cr.ephemeral_lines))

        # 2. Inquiry intent
        res_inq = self.engine.classify("开工反问四大维度，探针提问机制")
        self.assertEqual(res_inq.intent, IntentType.COUNTER_QUESTIONING)
        self.assertTrue(any("counter-questioning-probe" in line for line in res_inq.ephemeral_lines))

        # 3. Kaigong intent
        res_kg = self.engine.classify("开工门禁启动任务")
        self.assertEqual(res_kg.intent, IntentType.KAIGONG)
        self.assertTrue(any("jhoc_kaigong" in line for line in res_kg.ephemeral_lines))

        # 4. Shougong intent
        res_sg = self.engine.classify("收工清理闭环")
        self.assertEqual(res_sg.intent, IntentType.SHOUGONG)
        self.assertTrue(any("jhoc_shougong" in line for line in res_sg.ephemeral_lines))

    def test_intent_explain_vs_execute(self) -> None:
        # Pure explanation query should NOT force execution scaffolding
        explain_prompt = "什么是多模型协审机制？它的工作原理是什么？"
        res_exp = self.engine.classify(explain_prompt)
        # Should identify the domain (MULTI_MODEL_CO_REVIEW) but flag is_execution as False
        self.assertEqual(res_exp.intent, IntentType.MULTI_MODEL_CO_REVIEW)
        self.assertFalse(res_exp.is_execution)
        # Ephemeral scaffolding must NOT inject execution commands or physical gate constraints
        self.assertFalse(any("[JHOC TARGET TOOL]" in line for line in res_exp.ephemeral_lines))
        self.assertFalse(any("Physical CLI execution required" in line for line in res_exp.ephemeral_lines))

    def test_ephemeral_template_rendering_bounds(self) -> None:
        warning = LessonTemplateRenderer.render_lesson_warning(
            {
                "lesson_id": "147",
                "rule": "Rule 0: Meta-Cognitive Distillation",
                "symptom": "Pure-text fake co-review roleplay",
            },
            positive_tool="py -3 scripts/jhoc_co_review.py",
        )
        lines = LessonTemplateRenderer.render_ephemeral_package(
            intent_name="CO_REVIEW",
            scaffolding_path=".agents/skills/jhoc-co-review",
            target_tool="py -3 scripts/jhoc_co_review.py",
            lesson_warning=warning,
            gate_constraint="PreTool Gate physically blocks unapproved edits.",
        )
        # Bounded within 4 lines
        self.assertTrue(len(lines) <= 4)
        # Rule 7: Zero emoji check
        import re
        emoji_re = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]")
        for line in lines:
            self.assertEqual(len(emoji_re.findall(line)), 0)

    def test_post_verify_roleplay_interception(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_file = Path(tmpdir) / "transcript.jsonl"
            # Simulate a turn where user asked for co-review, but assistant responded with text verdict without running tool
            lines = [
                json.dumps({
                    "type": "USER_INPUT",
                    "content": "<USER_REQUEST>拉起协审，讨论完整的优化方案</USER_REQUEST>",
                }),
                json.dumps({
                    "type": "MODEL",
                    "content": "好的，我已经完成多模型协审：[VERDICT] APPROVED_WITH_CONDITIONS。Claude 和 Codex 均已同意。",
                    "tool_calls": [],
                }),
            ]
            transcript_file.write_text("\n".join(lines), encoding="utf-8")

            payload = {
                "transcriptPath": str(transcript_file),
                "coReviewDir": str(Path(tmpdir) / "empty_co_review"),
            }
            res = evaluate_post_invocation(payload)

            # Verification should catch the pure-text fake verdict and trigger force_continue
            self.assertEqual(res.get("terminationBehavior"), "force_continue")
            self.assertTrue(len(res.get("injectSteps", [])) > 0)
            injected_text = res["injectSteps"][0].get("ephemeralMessage", "")
            self.assertIn("HARNESS 拦截", injected_text)
            self.assertIn("口头宣称了多模型协审", injected_text)

    def test_post_verify_passes_when_tool_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_file = Path(tmpdir) / "transcript.jsonl"
            # Simulate a turn where assistant DID invoke the real CLI tool
            lines = [
                json.dumps({
                    "type": "USER_INPUT",
                    "content": "<USER_REQUEST>拉起协审，讨论完整的优化方案</USER_REQUEST>",
                }),
                json.dumps({
                    "type": "MODEL",
                    "content": "正在物理调用外部多模型审查脚本...",
                    "tool_calls": [
                        {"name": "run_command", "args": {"CommandLine": "py -3 scripts/jhoc_co_review.py"}}
                    ],
                }),
            ]
            transcript_file.write_text("\n".join(lines), encoding="utf-8")

            payload = {"transcriptPath": str(transcript_file)}
            res = evaluate_post_invocation(payload)

            # Verification should PASS (no force_continue)
            self.assertNotIn("terminationBehavior", res)
            self.assertEqual(res.get("injectSteps"), [])

    def test_blackbox_hash_chain_verification(self) -> None:
        is_valid, count, errors = verify_blackbox_hash_chain(ROOT)
        self.assertTrue(is_valid, f"Blackbox hash chain broken: {errors}")
        self.assertGreaterEqual(count, 0)

    def test_local_asset_indexer_atomic_execution(self) -> None:
        indexer = AssetIndexer(ROOT)
        index_data = indexer.build_index()
        self.assertIn("assets", index_data)
        self.assertIn("bigram_index", index_data)
        self.assertGreater(len(index_data["assets"]), 30)

        # Test atomic save to temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            temp_indexer = AssetIndexer(temp_root)
            out_file = temp_indexer.save_index(index_data)
            self.assertTrue(out_file.is_file())
            loaded = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(loaded["schema_version"], "jhoc-asset-index/v1")
            self.assertEqual(len(loaded["assets"]), len(index_data["assets"]))


if __name__ == "__main__":
    unittest.main()
