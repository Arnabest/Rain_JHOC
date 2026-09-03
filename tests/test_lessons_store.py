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


if __name__ == "__main__":
    unittest.main()
