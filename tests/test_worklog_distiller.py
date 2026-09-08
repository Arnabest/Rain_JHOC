"""Unit tests for worklog-distiller skill and scripts/jhoc_worklog.py."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from jhoc_worklog import (
    GitCommitFact,
    ProblemCase,
    SessionFact,
    WorklogSummary,
    build_problem_knowledge_graph,
    distill_worklog,
    extract_session_facts,
    get_curated_problem_cases,
    render_markdown,
    render_single_problem_blog,
    render_tech_blog,
    strip_emojis,
    translate_jargon,
    update_problem_log_in_place,
    _EMOJI_RE,
)


class TestWorklogDistiller(unittest.TestCase):
    def test_translate_jargon(self) -> None:
        raw_text = "Refactor AST parser, add PUA protection and AEC filter for STT and TTS."
        translated = translate_jargon(raw_text)
        self.assertIn("代码重构优化", translated)
        self.assertIn("代码语法结构", translated)
        self.assertIn("防乱码占位符", translated)
        self.assertIn("麦克风回声消除", translated)
        self.assertIn("语音识别输入", translated)
        self.assertIn("文字朗读发音", translated)

    def test_zero_emoji_discipline(self) -> None:
        dirty = "这是带表情的标题 🚀 🔥 [PASS] 全部通过 ✅"
        clean = strip_emojis(dirty)
        self.assertFalse(_EMOJI_RE.search(clean), "Cleaned text must have zero emojis")
        self.assertIn("[PASS]", clean)
        self.assertIn("全部通过", clean)

    def test_distill_worklog_with_mock_data(self) -> None:
        git_facts = [
            GitCommitFact(
                commit_hash="a1b2c3d",
                author="Codex Local",
                date_str="2026-09-05",
                subject="feat(ui): add voice mode switcher card",
            )
        ]
        session_facts = [
            SessionFact(
                task_id="session-20260905-test",
                date_str="2026-09-05",
                title="语音输入清洗与朗读防乱码优化",
                goal="解决朗读时公式杂音并统一基座",
                status="COMPLETED",
                visible_changes=["朗读前自动清理公式与无意义符号，避免朗读杂音"],
                tech_changes=["统一基座服务接口，强化多任务并发防崩溃写保护"],
                action_items=["需确认是否在设置面板增加切换卡片"],
                test_results=["15/15 PASS (100%)"],
            )
        ]
        git_stats = {"files_changed": 3, "insertions": 120, "deletions": 15}
        timeline_stats = {"total_tasks": 1, "closed": 1, "failed": 0, "armed": 1}

        summary = distill_worklog(
            date_str="2026-09-05",
            git_facts=git_facts,
            session_facts=session_facts,
            git_stats=git_stats,
            timeline_stats=timeline_stats,
        )

        self.assertIn("[PASS]", summary.overall_status)
        self.assertIn("语音输入清洗", summary.executive_glance)
        self.assertEqual(len(summary.visible_items), 1)
        self.assertEqual(len(summary.tech_items), 1)
        self.assertEqual(len(summary.action_items), 1)
        self.assertIn("15/15 PASS", summary.test_metrics)

        # Render markdown
        md = render_markdown(summary)
        self.assertIn("# 工作日志与成果简报 (2026-09-05)", md)
        self.assertIn("### [30秒极速看板]", md)
        self.assertIn("### [一、 人类可感知的关键改动]", md)
        self.assertIn("### [二、 幕后系统加固与技术改造]", md)
        self.assertIn("### [三、 需要您拍板或注意的事项]", md)
        self.assertIn("### [四、 自动化验证与存证记录]", md)
        self.assertFalse(_EMOJI_RE.search(md), "Rendered Markdown must contain 0 emojis")

    def test_extract_session_facts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            mem_dir = tmp_root / "memory"
            mem_dir.mkdir(parents=True)
            session_file = mem_dir / "session-20260905-demo.md"
            session_file.write_text(
                "# Session Memory: 测试演示任务\n\n"
                "- **目标**: 验证会话事实抽取器\n"
                "- **状态**: COMPLETED\n\n"
                "## 1. 核心落地与修改清单\n\n"
                "- 界面优化：新增深色模式切换按钮\n"
                "- 底层加固：修复并发死锁漏洞\n\n"
                "## 2. 物理可证伪验收结果\n\n"
                "- 10/10 项断言全数通过 (100% PASS)\n\n"
                "## 3. 下一步建议\n\n"
                "- 建议用户在客户端体验深色主题\n",
                encoding="utf-8",
            )

            facts = extract_session_facts(tmp_root, "2026-09-05")
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0].title, "测试演示任务")
            self.assertEqual(facts[0].goal, "验证会话事实抽取器")
            self.assertIn("深色模式切换按钮", facts[0].visible_changes[0])
            self.assertIn("并发死锁漏洞", facts[0].tech_changes[0])
            self.assertIn("100% PASS", facts[0].test_results[0])
            self.assertIn("体验深色主题", facts[0].action_items[0])

    def test_cli_execution_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_file = Path(td) / "worklog_test.md"
            res = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "jhoc_worklog.py"),
                    "--workspace",
                    str(ROOT),
                    "--date",
                    "2026-09-05",
                    "--output",
                    str(out_file),
                    "--save",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            self.assertEqual(res.returncode, 0, f"CLI exited with error: {res.stderr}")
            self.assertTrue(out_file.is_file(), "Worklog file must be created")
            saved_content = out_file.read_text(encoding="utf-8")
            self.assertIn("工作日志与成果简报", saved_content)
            self.assertIn("[30秒极速看板]", saved_content)
            self.assertFalse(_EMOJI_RE.search(saved_content), "Saved file must be zero-emoji compliant")

    def test_render_tech_blog_structure(self) -> None:
        summary = WorklogSummary(
            date_str="2026-09-05",
            overall_status="[PASS] 稳定推进",
            executive_glance="统一基座与双向清洗流水线收敛",
            visible_items=["文字朗读发音: 保护公式防乱码"],
            tech_items=["统一基座服务"],
            action_items=["需确认模式选择"],
            test_metrics="29/29 PASS (100%)",
            git_commits_count=1,
            files_changed_count=3,
            insertions=50,
            deletions=10,
            recent_commits=[{"commit_hash": "1234567", "subject": "feat: test", "author": "dev", "date_str": "2026-09-05"}],
        )
        session_facts = [
            SessionFact(
                task_id="session-demo",
                date_str="2026-09-05",
                title="TTS/STT 双向清洗",
                goal="解决公式乱码与回声自激",
                status="COMPLETED",
                visible_changes=["公式朗读不报乱码"],
                tech_changes=["状态哈希回声检测"],
                action_items=["建议支持模式切换卡片"],
                test_results=["29/29 PASS"],
            )
        ]
        blog_md = render_tech_blog(summary, session_facts, [], git_diff_text="- old\n+ new")

        self.assertIn("技术博客实战复盘日志", blog_md)
        self.assertIn("## 一、 开发背景与业务初衷", blog_md)
        self.assertIn("## 二、 问题是怎么出现的", blog_md)
        self.assertIn("## 三、 问题的细节与底层机理", blog_md)
        self.assertIn("## 四、 尝试解决的曲折过程", blog_md)
        self.assertIn("## 五、 终局解决方案与代码剖析", blog_md)
        self.assertIn("### 5.2 案例代码段落", blog_md)
        self.assertIn("### 5.3 精准变更比对", blog_md)
        self.assertIn("```diff", blog_md)
        self.assertIn("## 六、 问题解决后对我们的启发", blog_md)
        self.assertIn("## 七、 自动化物理验证与基准度量", blog_md)
        self.assertFalse(_EMOJI_RE.search(blog_md), "Blog Markdown must have 0 emojis")

    def test_render_single_problem_blog(self) -> None:
        case = ProblemCase(
            slug="test-case-demo",
            title="测试单问题独立日志：演示用例",
            overview="测试用例导读说明",
            background="这是详实的背景描述，面向开发新手，解释通俗易懂。",
            emergence="问题是在执行某某操作时出现的现场还原。",
            root_cause="这是对底层机理的深入剖析，通俗解释为什么发生。",
            trial_and_error="这是尝试走过的弯路与为什么失败。",
            solution="这是终局解决方案描述。",
            code_snippet="```python\n# 核心代码\ndef solve(): pass\n```",
            code_diff="```diff\n- old\n+ new\n```",
            takeaways=["经验教训 1", "经验教训 2"],
            benchmarks="自动化单测 10/10 PASS",
        )
        rendered = render_single_problem_blog(case, "2026-09-05")
        self.assertIn("# 技术复盘日志：测试单问题独立日志：演示用例 (2026-09-05)", rendered)
        self.assertIn("## 一、 业务背景：我们在做什么系统？", rendered)
        self.assertIn("## 二、 案发现场：问题是怎么出现的？", rendered)
        self.assertIn("## 三、 技术深潜：问题的本质与底层机理", rendered)
        self.assertIn("## 四、 避坑排障：我们走过的弯路与失败尝试", rendered)
        self.assertIn("## 五、 终局方案：彻底解决的代码实现与 Diff", rendered)
        self.assertIn("### 5.1 案例核心代码段落", rendered)
        self.assertIn("### 5.2 精准变更比对", rendered)
        self.assertIn("## 六、 经验沉淀：给开发新手的思考与心智模型", rendered)
        self.assertIn("## 七、 物理实测：如何证明真的修好了？", rendered)
        self.assertIn("```diff", rendered)
        self.assertFalse(_EMOJI_RE.search(rendered), "Rendered post must contain 0 emojis")

    def test_get_curated_problem_cases(self) -> None:
        cases = get_curated_problem_cases("2026-09-05")
        self.assertGreaterEqual(len(cases), 3, "Must have at least 3 curated problem cases")
        slugs = [c.slug for c in cases]
        self.assertIn("latex-tts-scramble-and-aec-echo", slugs)
        self.assertIn("windows-app-alias-python-conflict", slugs)
        self.assertIn("session-parser-state-machine-keyword-bleed", slugs)
        self.assertIn("verse-search-box-focus-and-magnifier-misalignment", slugs)
        for c in cases:
            self.assertTrue(len(c.background) > 50, "Background must be detailed and rich")
            self.assertTrue(len(c.emergence) > 50, "Emergence must be detailed")
            self.assertTrue(len(c.root_cause) > 50, "Root cause must be detailed")
            self.assertTrue(len(c.solution) > 50, "Solution must be detailed")
            self.assertIn("```", c.code_snippet, "Must have code snippet")
            self.assertIn("```diff", c.code_diff, "Must have code diff")
            self.assertTrue(len(c.takeaways) >= 2, "Must have at least 2 takeaways")

    def test_cli_blog_execution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_file = Path(td) / "blog_test.md"
            res = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "jhoc_worklog.py"),
                    "--workspace",
                    str(ROOT),
                    "--date",
                    "2026-09-05",
                    "--blog",
                    "--output",
                    str(out_file),
                    "--save",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            self.assertEqual(res.returncode, 0, f"CLI blog mode failed: {res.stderr}")
            self.assertTrue(out_file.is_file(), "Blog worklog compilation file must be created")
            saved_content = out_file.read_text(encoding="utf-8")
            self.assertIn("技术复盘日志", saved_content)
            self.assertIn("## 一、 业务背景", saved_content)
            self.assertIn("## 二、 案发现场", saved_content)
            self.assertIn("```diff", saved_content)
            self.assertFalse(_EMOJI_RE.search(saved_content), "Blog file must be zero-emoji compliant")

            # Check individual problem files were also saved
            individual_files = list(Path(td).glob("2026-09-05-*.md"))
            cases = get_curated_problem_cases("2026-09-05")
            self.assertEqual(len(individual_files), len(cases), "All individual problem files must be saved")

    def test_build_problem_knowledge_graph(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            cases = get_curated_problem_cases("2026-09-05")
            graph = build_problem_knowledge_graph(cases, tmp_root)
            self.assertGreaterEqual(graph["total_nodes"], 20, "Must have comprehensive node count")
            self.assertGreaterEqual(graph["total_relations"], 20, "Must have comprehensive relation count")

            # Check json file was created on disk
            graph_json = tmp_root / "docs" / "worklogs" / "worklog-knowledge-graph.json"
            self.assertTrue(graph_json.is_file(), "Knowledge graph JSON must exist")

            # Verify relation types
            relation_types = {r["relation_type"] for r in graph["relations"]}
            self.assertIn("derived_from", relation_types)
            self.assertIn("observed_in", relation_types)
            self.assertIn("solves", relation_types)
            self.assertIn("verified_by", relation_types)
            self.assertIn("related_to", relation_types)
            self.assertIn("supersedes", relation_types)

    def test_update_problem_log_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            # 1. First render initial log
            cases = get_curated_problem_cases("2026-09-05")
            target_case = [c for c in cases if c.slug == "session-parser-state-machine-keyword-bleed"][0]
            initial_post = render_single_problem_blog(target_case, "2026-09-05")
            log_file = tmp_root / "docs" / "worklogs" / f"2026-09-05-{target_case.slug}.md"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text(initial_post, encoding="utf-8")

            # 2. Update in-place with new reproduction condition and superior solution
            success = update_problem_log_in_place(
                workspace_root=tmp_root,
                slug="session-parser-state-machine-keyword-bleed",
                date_str="2026-09-05",
                reproduce_condition="在极端多层嵌套语法中复现",
                reproduce_symptom="三层反引号未被正确成对识别",
                better_solution="使用 AST 词法栈替代简单的标志位切换",
                better_code="```python\n# 词法栈解法\n```",
                better_diff="```diff\n- flag\n+ stack\n```",
                better_takeaway="复杂标记语言解析必须使用栈式作用域分析",
            )
            self.assertTrue(success, "Update must succeed")

            # 3. Read back updated file
            updated_content = log_file.read_text(encoding="utf-8")
            self.assertIn("在极端多层嵌套语法中复现", updated_content)
            self.assertIn("使用 AST 词法栈替代简单的标志位切换", updated_content)
            self.assertIn("复杂标记语言解析必须使用栈式作用域分析", updated_content)
            self.assertIn("[EVOLVED]", updated_content)
            self.assertFalse(_EMOJI_RE.search(updated_content), "Updated content must be zero-emoji compliant")


if __name__ == "__main__":
    unittest.main()
