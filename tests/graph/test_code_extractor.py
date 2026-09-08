from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from jhoc.graph.code_extractor import CodeGraphExtractor
from jhoc.graph.store import GraphStore


class TestCodeGraphExtractor(unittest.TestCase):
    def test_extract_code_entities_and_relations(self) -> None:
        source = """
import os
from jhoc.guard import PathGuard

class SecurityManager(PathGuard):
    def check_access(self, target):
        return self.evaluate(target)

def standalone_helper():
    pass
"""
        nodes, relations = CodeGraphExtractor.extract_from_source(
            "sample.py", source, "jhoc.security.manager"
        )
        node_ids = {n.node_id for n in nodes}
        self.assertIn("code:module:jhoc.security.manager", node_ids)
        self.assertIn("code:class:jhoc.security.manager.SecurityManager", node_ids)
        self.assertIn("code:func:jhoc.security.manager.SecurityManager.check_access", node_ids)
        self.assertIn("code:func:jhoc.security.manager.standalone_helper", node_ids)
        self.assertIn("code:module:jhoc.guard", node_ids)

        rel_types = {(r.source_node, r.relation_type, r.target_node) for r in relations}
        # Class belongs to module
        self.assertIn(
            ("code:class:jhoc.security.manager.SecurityManager", "belongs_to", "code:module:jhoc.security.manager"),
            rel_types,
        )
        # Method belongs to class
        self.assertIn(
            ("code:func:jhoc.security.manager.SecurityManager.check_access", "belongs_to", "code:class:jhoc.security.manager.SecurityManager"),
            rel_types,
        )
        # Module depends on import
        self.assertIn(
            ("code:module:jhoc.security.manager", "depends_on", "code:module:jhoc.guard"),
            rel_types,
        )

    def test_index_directory_projection(self) -> None:
        store = GraphStore()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg = tmppath / "pkg"
            pkg.mkdir()
            (pkg / "mod_a.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
            (pkg / "mod_b.py").write_text("import pkg.mod_a\nclass Beta(pkg.mod_a.Alpha):\n    pass\n", encoding="utf-8")

            count = CodeGraphExtractor.index_directory(pkg, store, package_prefix="pkg")
            self.assertGreater(count, 0)
            self.assertGreater(len(store.relations()), 0)


if __name__ == "__main__":
    unittest.main()
