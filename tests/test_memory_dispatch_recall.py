from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from jhoc.memory_store.retriever import MemoryRetriever
from jhoc_dispatch import build_dispatched_context


class TestMemoryDispatchRecall(unittest.TestCase):
    def setUp(self) -> None:
        self.retriever = MemoryRetriever()

    def test_memory_retriever_l1_hot_context_recall(self) -> None:
        l1_items = self.retriever.retrieve_l1_hot_context(limit=1)
        self.assertEqual(len(l1_items), 1, "Expected exactly 1 L1 hot context item")
        item = l1_items[0]
        self.assertEqual(item.tier, "L1")
        self.assertTrue(item.title, "L1 title must not be empty")
        self.assertTrue(item.domain, "L1 domain must not be empty")
        self.assertTrue(item.summary, "L1 summary must not be empty")
        self.assertLessEqual(len(item.summary), 300, "L1 summary must be concise and bounded")

    def test_memory_retriever_l2_domain_inference_and_recall(self) -> None:
        # 1. Test Proxy / Network domain
        proxy_items = self.retriever.retrieve_l2_distilled_memory("排查网络代理与 urllib 环境变量配置", limit=2)
        self.assertGreaterEqual(len(proxy_items), 1)
        for item in proxy_items:
            self.assertEqual(item.tier, "L2")
            self.assertEqual(item.domain, "Network & Proxy Routing")

        # 2. Test Multi-Model / Provider domain
        model_items = self.retriever.retrieve_l2_distilled_memory("多模型协同分发与 provider 状态机", limit=2)
        self.assertGreaterEqual(len(model_items), 1)
        for item in model_items:
            self.assertEqual(item.tier, "L2")
            self.assertEqual(item.domain, "Multi-Model & Provider Interop")

        # 3. Test Architecture / Infrastructure domain
        arch_items = self.retriever.retrieve_l2_distilled_memory("系统重构与微内核架构设计原则", limit=2)
        self.assertGreaterEqual(len(arch_items), 1)
        for item in arch_items:
            self.assertEqual(item.tier, "L2")
            self.assertEqual(item.domain, "Architecture & Infrastructure")

    def test_memory_bundle_structure(self) -> None:
        bundle = self.retriever.retrieve_active_memory_bundle("网络代理配置")
        self.assertIn("l1_hot_context", bundle)
        self.assertIn("l2_distilled_architecture", bundle)
        self.assertGreaterEqual(len(bundle["l1_hot_context"]), 1)
        self.assertGreaterEqual(len(bundle["l2_distilled_architecture"]), 1)
        self.assertGreaterEqual(bundle["total_recalled"], 2)

    def test_dispatch_context_integrates_active_memory_source(self) -> None:
        context = build_dispatched_context("重构网络代理模块与 urllib 路由", "agent-runner")
        self.assertIn("memory", context)
        mem = context["memory"]
        self.assertIn("l1_hot_context", mem)
        self.assertIn("l2_distilled_architecture", mem)
        self.assertGreaterEqual(len(mem["l1_hot_context"]), 1)
        self.assertGreaterEqual(len(mem["l2_distilled_architecture"]), 1)

        # Snapshot ID must be generated via Pass B
        self.assertIn("snapshot_id", context)
        self.assertTrue(context["snapshot_id"].startswith("context:"))

    # =========================================================================
    # 可证伪反例与边界防御测试 (Falsifiable Counterexample & Negative Tests)
    # =========================================================================

    def test_falsifiable_cold_l3_archive_never_leaked_into_active_recall(self) -> None:
        """反例 1: L3 冷归档数据绝不得漏入前台活跃召回 (L1/L2 隔离原则)。"""
        # 测试各类查询，断言返回的绝对不包含任何 L3 记录
        test_queries = [
            "历史对话实录与遗留资产",
            "QQMusicOverlay 播放记录",
            "网络代理配置",
            "架构重构",
            "多模型协同",
        ]
        for q in test_queries:
            bundle = self.retriever.retrieve_active_memory_bundle(q)
            for item in bundle["l1_hot_context"]:
                self.assertNotEqual(item.get("tier"), "L3", f"L3 record leaked in L1 context: {item}")
            for item in bundle["l2_distilled_architecture"]:
                self.assertNotEqual(item.get("tier"), "L3", f"L3 record leaked in L2 context: {item}")

    def test_falsifiable_graceful_degradation_on_missing_store(self) -> None:
        """反例 2: 当底层 SQLite 损坏或缺失时，检索器必须安全降级返回空包，绝不崩溃主调度。"""
        fake_retriever = MemoryRetriever(
            db_path=ROOT / "logs" / "non_existent_fake_db.sqlite",
            catalog_path=ROOT / "docs" / "taxonomy" / "non_existent_fake_catalog.json"
        )
        l1 = fake_retriever.retrieve_l1_hot_context()
        self.assertEqual(l1, ())
        l2 = fake_retriever.retrieve_l2_distilled_memory("任意查询")
        self.assertEqual(l2, ())
        bundle = fake_retriever.retrieve_active_memory_bundle("任意查询")
        self.assertEqual(bundle["total_recalled"], 0)


if __name__ == "__main__":
    unittest.main()
