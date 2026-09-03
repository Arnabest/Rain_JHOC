import tempfile
import unittest
from pathlib import Path

from scripts.prepare_incremental_migration_inventory import _classify, _scan


class IncrementalInventoryTests(unittest.TestCase):
    def test_classification_keeps_import_and_review_separate(self):
        self.assertEqual(_classify("aibox-memory", "MEMORY.md")[0], "ALREADY_IMPORTED")
        self.assertEqual(_classify("aibox-memory", "qqmusicoverlay-legacy/architecture.md")[0], "ALREADY_IMPORTED")
        self.assertEqual(_classify("aibox-memory", "token_stats_sessions/summary.md")[0], "REFERENCE_ONLY_RETAIN_SOURCE")
        self.assertEqual(_classify("aibox-intercom", "state.json")[0], "REFERENCE_ONLY_RETAIN_SOURCE")
        self.assertEqual(_classify("verse-skills", "skill-a/SKILL.md")[0], "REFERENCE_ONLY_RETAIN_SOURCE")
        self.assertEqual(_classify("verse-data", "cache.db")[0], "REFERENCE_ONLY_RETAIN_SOURCE")
        self.assertEqual(_classify("verse-data", "browser_profile/Default/Cache/data_0")[0], "EXCLUDED_RUNTIME_CACHE")
        self.assertEqual(_classify("verse-data", "temp_audio/voice.wav")[0], "EXCLUDED_RUNTIME_CACHE")
        self.assertEqual(_classify("aibox-memory", "quantum_phase_memory.json")[0], "EXPLICIT_QUARANTINE")
        self.assertEqual(_classify("verse-memory", "__pycache__/x.pyc")[0], "EXCLUDED_RUNTIME_CACHE")
        self.assertEqual(_classify("verse-memory", "backups/state.json")[0], "REFERENCE_ONLY_RETAIN_SOURCE")

    def test_scan_records_metadata_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "MEMORY.md").write_text("private content", encoding="utf-8")
            report = _scan("aibox-memory", root)
            self.assertEqual(report["file_count"], 1)
            entry = report["entries"][0]
            self.assertEqual(entry["disposition"], "ALREADY_IMPORTED")
            self.assertNotIn("private content", entry)
            self.assertEqual(report["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
