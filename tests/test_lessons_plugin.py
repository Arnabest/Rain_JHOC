from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from jhoc.contracts.models import PluginManifest
from jhoc.plugins import PluginGatekeeper, PluginHost, PluginLifecycle
from jhoc.plugins.lessons import LessonsPlugin

ROOT = Path(__file__).resolve().parents[1]


class TestLessonsPlugin(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lessons_dir = Path(self.temp_dir.name)
        # 预制一个错题
        self.plugin = LessonsPlugin(self.lessons_dir)
        self.plugin.initialize({"lessons_dir": str(self.lessons_dir)})

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_describe_and_health(self) -> None:
        desc = self.plugin.describe()
        self.assertEqual(desc["plugin_id"], "jhoc.lessons")
        self.assertEqual(desc["protocol_version"], "1.0")

        health = self.plugin.health()
        self.assertEqual(health["status"], "READY")

    def test_invoke_add_get_search_list(self) -> None:
        # 1. Add
        add_res = self.plugin.invoke({
            "action": "add",
            "category": "cognitive",
            "title": "测试插件追加",
            "symptom": "插件行为异常",
            "root": "参数未校验",
            "rule": "必须通过 validate",
            "id": "777",
        })
        self.assertEqual(add_res["status"], "CREATED")
        self.assertEqual(add_res["lesson"]["lesson_id"], "777")

        # 2. Get
        get_res = self.plugin.invoke({"action": "get", "id": "777"})
        self.assertEqual(get_res["status"], "OK")
        self.assertEqual(get_res["lesson"]["title"], "测试插件追加")

        # 3. Search
        search_res = self.plugin.invoke({"action": "search", "keyword": "插件追加"})
        self.assertEqual(search_res["status"], "OK")
        self.assertGreaterEqual(search_res["count"], 1)

        # 4. List
        list_res = self.plugin.invoke({"action": "list"})
        self.assertEqual(list_res["status"], "OK")
        self.assertGreaterEqual(list_res["count"], 1)

        # 5. Query (Natural text scoring)
        query_res = self.plugin.invoke({"action": "query", "query": "我想排查测试插件追加的问题", "limit": 1})
        self.assertEqual(query_res["status"], "OK")
        self.assertEqual(len(query_res["lessons"]), 1)
        self.assertEqual(query_res["lessons"][0]["lesson_id"], "777")

    def test_gatekeeper_ast_inspection_passes(self) -> None:
        plugin_code_path = ROOT / "src" / "jhoc" / "plugins" / "lessons.py"
        manifest = PluginManifest(
            plugin_id="jhoc.lessons",
            name="JHOC Lessons Plugin",
            version="1.0.0",
            protocol_version="1.0",
            plugin_type="capability",
            capabilities=("list", "search", "get", "add", "query"),
            verification_status="VERIFIED",
            mutable_by_agent=False,
        )
        source = (plugin_code_path.name, plugin_code_path.read_text(encoding="utf-8"))
        report = PluginGatekeeper.audit(manifest, [source])
        self.assertTrue(report.gate_2_code_ok)
        self.assertTrue(report.is_admissible, f"Violations: {report.violations}")

    def test_plugin_host_lifecycle(self) -> None:
        manifest = PluginManifest(
            plugin_id="jhoc.lessons",
            name="JHOC Lessons Plugin",
            version="1.0.0",
            protocol_version="1.0",
            plugin_type="capability",
            capabilities=("list", "search", "get", "add", "query"),
            verification_status="VERIFIED",
            mutable_by_agent=False,
        )
        host = PluginHost(manifest, self.plugin)
        host.verify()
        self.assertEqual(host.state, PluginLifecycle.VERIFIED)
        host.install()
        self.assertEqual(host.state, PluginLifecycle.INSTALLED)
        host.load()
        self.assertEqual(host.state, PluginLifecycle.LOADED)
        host.handshake()
        self.assertEqual(host.state, PluginLifecycle.NEGOTIATED)
        host.initialize({"lessons_dir": str(self.lessons_dir)})
        self.assertEqual(host.state, PluginLifecycle.READY)


if __name__ == "__main__":
    unittest.main()
