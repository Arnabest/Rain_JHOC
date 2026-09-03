from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from jhoc_dispatch import build_dispatched_context  # noqa: E402


class TestDispatchContext(unittest.TestCase):
    def test_dispatch_with_socket_keyword_extracts_lesson_90(self) -> None:
        context = build_dispatched_context("系统发生 Socket 轮询超时异常", "agent-runner")
        self.assertIn("lessons", context)
        self.assertGreaterEqual(len(context["lessons"]), 1)
        lesson_ids = [l["lesson_id"] for l in context["lessons"]]
        self.assertIn("90", lesson_ids)
        self.assertIn("snapshot_id", context)
        self.assertTrue(context["snapshot_id"].startswith("context:"))

    def test_dispatch_with_paper_keyword_extracts_cognitive_lesson(self) -> None:
        context = build_dispatched_context("解读这篇论文 arxiv.org/abs/2608.27454", "agent-runner")
        self.assertIn("lessons", context)
        self.assertGreaterEqual(len(context["lessons"]), 1)
        lesson_ids = [l["lesson_id"] for l in context["lessons"]]
        self.assertIn("147", lesson_ids)

    def test_dispatch_fallback_mounts_tier_0_lesson_147(self) -> None:
        context = build_dispatched_context("普通文件编辑需求", "agent-runner")
        self.assertIn("lessons", context)
        self.assertGreaterEqual(len(context["lessons"]), 1)
        lesson_ids = [l["lesson_id"] for l in context["lessons"]]
        self.assertIn("147", lesson_ids)

    def test_dispatch_hooks_kaigong_skill_scaffolding(self) -> None:
        context = build_dispatched_context("开工", "agent-runner")
        self.assertIn("skill", context)
        self.assertIsNotNone(context["skill"])
        self.assertEqual(context["skill"]["intent"], "KAIGONG")
        self.assertIn("kaigong", context["skill"]["scaffolding_path"])

    def test_dispatch_hooks_shougong_skill_scaffolding(self) -> None:
        context = build_dispatched_context("/收工", "agent-runner")
        self.assertIn("skill", context)
        self.assertIsNotNone(context["skill"])
        self.assertEqual(context["skill"]["intent"], "SHOUGONG")
        self.assertIn("shougong", context["skill"]["scaffolding_path"])

    def test_dispatch_hooks_post_task_memory_skill_scaffolding(self) -> None:
        context = build_dispatched_context("任务收尾归档并持久化共享记忆", "agent-runner")
        self.assertIn("skill", context)
        self.assertIsNotNone(context["skill"])
        self.assertEqual(context["skill"]["intent"], "POST_TASK_MEMORY")
        self.assertIn("post-task-shared-memory", context["skill"]["scaffolding_path"])

    def test_dispatch_pure_chat_does_not_hook_skill(self) -> None:
        context = build_dispatched_context("你好，今天天气不错", "agent-runner")
        self.assertIsNone(context.get("skill"))

    def test_dispatch_injects_shelf_capabilities_brief(self) -> None:
        context = build_dispatched_context("日常工程开发", "agent-runner")
        self.assertIn("shelf", context)
        shelf = context["shelf"]
        self.assertIsInstance(shelf, list)
        self.assertGreaterEqual(len(shelf), 7)
        skill_names = {item["name"] for item in shelf}
        self.assertIn("kaigong", skill_names)
        self.assertIn("shougong", skill_names)
        self.assertIn("codex-plan-review", skill_names)


if __name__ == "__main__":
    unittest.main()
