from __future__ import annotations

from pathlib import Path
import unittest

from jhoc.lessons import LessonsStore

ROOT = Path(__file__).resolve().parents[1]


class TestLessonsStore(unittest.TestCase):
    def setUp(self) -> None:
        self.store = LessonsStore(ROOT / "docs" / "lessons")
        self.store.load()

    def test_lessons_loaded_successfully(self) -> None:
        lessons = self.store.all_lessons()
        self.assertGreaterEqual(len(lessons), 10)

    def test_get_lesson_147(self) -> None:
        lesson = self.store.get_by_id("147")
        self.assertIsNotNone(lesson)
        self.assertIn("蒸馏三问", lesson.title)
        self.assertIn("首轮", lesson.symptom)
        self.assertIn("硬纪律", lesson.rule)

    def test_find_by_keyword(self) -> None:
        results = self.store.find_by_keyword("蒸馏三问")
        self.assertGreaterEqual(len(results), 1)
        ids = [e.lesson_id for e in results]
        self.assertIn("147", ids)

    def test_get_lesson_95_hidden_window(self) -> None:
        lesson = self.store.get_by_id("95")
        self.assertIsNotNone(lesson)
        self.assertIn("黑框", lesson.title)
        self.assertIn("CREATE_NO_WINDOW", lesson.rule)

    def test_get_lesson_393_unittest_isolation(self) -> None:
        lesson = self.store.get_by_id("393")
        self.assertIsNotNone(lesson)
        self.assertIn("discover", lesson.title)
        self.assertIn("物理隔离", lesson.rule)

    def test_get_cognitive_guard_lessons(self) -> None:
        cog_lessons = self.store.get_cognitive_guard_lessons()
        self.assertGreaterEqual(len(cog_lessons), 3)
        titles = " ".join(e.title for e in cog_lessons)
        self.assertIn("蒸馏三问", titles)
        self.assertIn("过度思虑", titles)

    def test_get_lesson_407_and_408_markdown_headings(self) -> None:
        l407 = self.store.get_by_id("407")
        self.assertIsNotNone(l407)
        self.assertIn("显存", l407.title)
        self.assertTrue(l407.symptom)
        self.assertTrue(l407.root_cause)
        self.assertTrue(l407.rule)
        self.assertIn("急切水合", l407.title)
        self.assertIn("元数据", l407.rule)

        l408 = self.store.get_by_id("408")
        self.assertIsNotNone(l408)
        self.assertIn("输入法", l408.title)
        self.assertTrue(l408.symptom)
        self.assertTrue(l408.root_cause)
        self.assertTrue(l408.rule)
        self.assertIn("TSF", l408.root_cause)
        self.assertIn("PromptSection", l408.rule)


if __name__ == "__main__":
    unittest.main()

