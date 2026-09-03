from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True, slots=True)
class LessonEntry:
    lesson_id: str
    category: str
    title: str
    symptom: str
    root_cause: str
    rule: str
    source_file: str


class LessonsStore:
    """Parser and query store for canonical JHOC lessons."""

    def __init__(self, lessons_dir: Path | str | None = None) -> None:
        if lessons_dir is None:
            self._root = Path(__file__).resolve().parents[3] / "docs" / "lessons"
        else:
            self._root = Path(lessons_dir)
        self._entries: list[LessonEntry] = []
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self._root.exists() or not self._root.is_dir():
            self._loaded = True
            return

        for path in sorted(self._root.glob("*.md")):
            self._parse_markdown(path)
        self._loaded = True

    def _parse_markdown(self, path: Path) -> None:
        content = path.read_text(encoding="utf-8")
        category = path.stem

        # 正则分割 ## 1. LESSON #...
        sections = re.split(r"\n##\s+", content)
        for sec in sections[1:]:
            lines = sec.strip().splitlines()
            if not lines:
                continue
            header = lines[0]
            m_id = re.search(r"LESSON\s*#?([A-Za-z0-9\-_]+)", header, re.IGNORECASE)
            lesson_id = m_id.group(1) if m_id else header[:20].strip()

            title_part = header.split(":", 1)[1].strip() if ":" in header else header

            symptom = self._extract_field(sec, "症状")
            root_cause = self._extract_field(sec, "根因")
            rule = self._extract_field(sec, "规约")

            self._entries.append(
                LessonEntry(
                    lesson_id=lesson_id,
                    category=category,
                    title=title_part,
                    symptom=symptom,
                    root_cause=root_cause,
                    rule=rule,
                    source_file=path.name,
                )
            )

    @staticmethod
    def _extract_field(text: str, field_name: str) -> str:
        pattern = rf"-\s*\*\*{field_name}\*\*[:：]\s*(.*?)(?=\n-\s*\*\*|\Z)"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return m.group(1).strip()
        return ""

    def all_lessons(self) -> tuple[LessonEntry, ...]:
        self.load()
        return tuple(self._entries)

    def find_by_keyword(self, keyword: str) -> tuple[LessonEntry, ...]:
        self.load()
        kw = keyword.lower()
        results = [
            e for e in self._entries
            if kw in e.lesson_id.lower() or kw in e.title.lower() or kw in e.symptom.lower() or kw in e.rule.lower()
        ]
        return tuple(results)

    def get_by_id(self, lesson_id: str) -> LessonEntry | None:
        self.load()
        target = lesson_id.lower().replace("#", "").strip()
        for e in self._entries:
            if e.lesson_id.lower().replace("#", "").strip() == target:
                return e
        return None

    def get_by_category(self, category: str) -> tuple[LessonEntry, ...]:
        self.load()
        return tuple(e for e in self._entries if category.lower() in e.category.lower())

    def get_cognitive_guard_lessons(self) -> tuple[LessonEntry, ...]:
        return self.get_by_category("01-cognitive-and-sycophancy")

    def query(self, text: str, limit: int = 2) -> tuple[LessonEntry, ...]:
        """Independent search engine scoring and retrieving top lessons for a query.

        Evaluates relevance across title, symptom, and rule fields.
        Falls back to Tier 0 Meta-Cognitive Guard Lesson (#147) when no specific match is found.
        """
        self.load()
        if not text.strip():
            fallback = self.get_by_id("147")
            return (fallback,) if fallback else ()

        text_lower = text.lower()
        tokens = set(re.findall(r"[A-Za-z0-9_\-#]{2,}", text_lower))
        cjk_terms = [
            "超时", "死锁", "轮询", "进程", "黑框", "测试", "扫描", "污染", "清洗",
            "标点", "退出码", "静默", "论文", "前沿", "三问", "顺从", "架构", "继续",
            "诱饵", "自指", "插件", "审计"
        ]
        for term in cjk_terms:
            if term in text_lower:
                tokens.add(term)

        scored: list[tuple[float, LessonEntry]] = []
        for e in self._entries:
            score = 0.0
            e_title = e.title.lower()
            e_symptom = e.symptom.lower()
            e_rule = e.rule.lower()

            for tok in tokens:
                if tok in e_title:
                    score += 5.0
                if tok in e_symptom:
                    score += 3.0
                if tok in e_rule:
                    score += 2.0
                if tok == e.lesson_id.lower() or f"#{tok}" == e.lesson_id.lower():
                    score += 10.0

            if score > 0.0:
                scored.append((score, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [e for _, e in scored[:limit]]

        # Automatic fallback to Tier 0 Cognitive Guard if nothing scored
        if not results:
            fallback = self.get_by_id("147")
            if fallback:
                results.append(fallback)

        return tuple(results)
