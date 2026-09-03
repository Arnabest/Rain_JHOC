import unittest

from scripts.execute_incremental_import import select_entry


class IncrementalImportSelectionTests(unittest.TestCase):
    def test_selects_important_documents(self):
        self.assertEqual(select_entry("aibox-memory", "qqmusicoverlay-legacy/architecture.md")[0], "ProjectMemory")
        self.assertEqual(select_entry("aibox-knowledge", "core/architecture.md")[0], "PROJECT_KNOWLEDGE")
        self.assertEqual(select_entry("verse-memory", "distilled/lesson.md")[0], "ProjectMemory")
        self.assertEqual(select_entry("aibox-knowledge", "index.json")[0], "PROJECT_KNOWLEDGE")
        self.assertEqual(select_entry("verse-memory", "lessons_index.json")[0], "ErrorMemory")
        self.assertEqual(select_entry("verse-memory", "sessions_index.json")[0], "ProjectMemory")
        self.assertEqual(select_entry("verse-memory", "conversation_summary.json")[0], "ProjectMemory")
        self.assertEqual(select_entry("aibox-knowledge", "surf/deepseek-v4-pro.md")[0], "PROJECT_KNOWLEDGE")
        self.assertEqual(select_entry("aibox-knowledge", "pipeline-runs/bilibili-analysis.md")[0], "PROJECT_KNOWLEDGE")
        self.assertEqual(select_entry("aibox-knowledge", "boards/know_ai-ml.jsonl")[0], "PROJECT_KNOWLEDGE")
        self.assertEqual(select_entry("verse-memory", "archive/20260816-task.md")[0], "ProjectMemory")

    def test_excludes_logs_tests_and_secrets(self):
        self.assertIsNone(select_entry("aibox-memory", "token_stats_sessions/session/summary.md"))
        self.assertIsNone(select_entry("verse-memory", "backups/state.md"))
        self.assertIsNone(select_entry("aibox-memory", "oauth-client-secret.md"))
        self.assertIsNone(select_entry("aibox-knowledge", "boards/dev_agent.jsonl.lock"))
        self.assertIsNone(select_entry("verse-data", "sessions/default.events.jsonl"))
        self.assertIsNone(select_entry("verse-data", "temp_audio/voice.wav"))
        self.assertIsNone(select_entry("verse-memory", "user_settings.json"))
        self.assertIsNone(select_entry("verse-memory", "prevention_rules.json"))
        self.assertIsNone(select_entry("verse-memory", "self_organizing_knowledge_graph.json"))
        self.assertEqual(select_entry("verse-memory", "sessions/2026-08/session.md")[0], "ProjectMemory")
        self.assertIsNone(select_entry("verse-memory", "sessions/session.json"))
        self.assertEqual(select_entry("verse-memory", "README.md")[0], "ProjectMemory")


if __name__ == "__main__":
    unittest.main()
