from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from jhoc.contracts.errors import ContractError
from jhoc.lessons import LessonsAccumulator, LessonsStore


class TestLessonsAccumulator(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lessons_dir = Path(self.temp_dir.name)
        self.accumulator = LessonsAccumulator(self.lessons_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_append_lesson_creates_file_and_entry(self) -> None:
        entry = self.accumulator.append_lesson(
            category="process",
            title="测试死锁排查",
            symptom="调度线程陷入死锁",
            root_cause="跨线程未释放全局锁",
            rule="必须使用上下文管理器 RLock",
        )

        self.assertEqual(entry.lesson_id, "1")
        self.assertEqual(entry.category, "02-process-and-concurrency")
        self.assertEqual(entry.title, "测试死锁排查")

        # Verify via LessonsStore
        store = LessonsStore(self.lessons_dir)
        lessons = store.all_lessons()
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0].lesson_id, "1")
        self.assertIn("死锁", lessons[0].symptom)

    def test_append_multiple_lessons_increments_id(self) -> None:
        e1 = self.accumulator.append_lesson(
            category="tool",
            title="工具异常 1",
            symptom="症状 1",
            root_cause="根因 1",
            rule="规约 1",
        )
        e2 = self.accumulator.append_lesson(
            category="tool",
            title="工具异常 2",
            symptom="症状 2",
            root_cause="根因 2",
            rule="规约 2",
        )

        self.assertEqual(e1.lesson_id, "1")
        self.assertEqual(e2.lesson_id, "2")

    def test_append_with_explicit_id(self) -> None:
        entry = self.accumulator.append_lesson(
            category="cognitive",
            title="显式编号教训",
            symptom="症状",
            root_cause="根因",
            rule="规约",
            lesson_id="999",
        )
        self.assertEqual(entry.lesson_id, "999")

    def test_append_empty_fields_raises_contract_error(self) -> None:
        with self.assertRaises(ContractError):
            self.accumulator.append_lesson(
                category="tool",
                title="",
                symptom="symptom",
                root_cause="root",
                rule="rule",
            )


if __name__ == "__main__":
    unittest.main()
