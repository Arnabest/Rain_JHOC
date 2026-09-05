"""Tri-Tier Hybrid Governance Intent Engine.

Tier 1: Deterministic regex and exact command anchors (< 0.1ms).
Tier 2: In-memory CJK 2-gram / token topology overlap match against local_asset_index.json (~ 1ms).
Tier 3: Safe fallback to GENERAL_CONVERSATION with conservative scaffolding (never lags hot path).

Critical Constraints:
1. Explanatory vs Execution intent split (prevents false-positive tool activation on 'what is...').
2. Bounded fast-path execution (< 5ms).
3. Pure UTF-8, zero emojis (Rule 7).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from .schema import AssetRecord, AssetType, IntentMatchResult, IntentType
    from .template_renderer import LessonTemplateRenderer
    from .indexer import compute_char_bigrams
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from schema import AssetRecord, AssetType, IntentMatchResult, IntentType
    from template_renderer import LessonTemplateRenderer
    from indexer import compute_char_bigrams


class GovernanceIntentEngine:
    """Deterministic, low-latency intent classifier and local asset binder."""

    _TIER_1_RULES: tuple[tuple[re.Pattern[str], IntentType, str, str, str], ...] = (
        # (Pattern, IntentType, target_tool, scaffolding, lesson_id)
        (
            re.compile(r"(多模型协审|拉起协审|多模型商讨|拉起多模型|协同评审|co-review|商讨.*方案)", re.IGNORECASE),
            IntentType.MULTI_MODEL_CO_REVIEW,
            "py -3 scripts/jhoc_co_review.py",
            ".agents/skills/codex-plan-review/SKILL.md",
            "147",
        ),
        (
            re.compile(r"(规划评审|方案评审|架构对齐|plan-review|对齐计划)", re.IGNORECASE),
            IntentType.PLAN_REVIEW,
            "py -3 scripts/jhoc_co_review.py",
            ".agents/skills/codex-plan-review/SKILL.md",
            "147",
        ),
        (
            re.compile(r"(开工反问|探针提问|方向校准|细化需求|task-inquiry|direction-probe|反问四大维度)", re.IGNORECASE),
            IntentType.COUNTER_QUESTIONING,
            "py -3 scripts/jhoc_kaigong.py --inquiry",
            ".agents/skills/counter-questioning-probe/SKILL.md",
            "InquiryGate",
        ),
        (
            re.compile(r"(\$kaigong|/kaigong|^kaigong$|^/开工$|^开工$|开工门禁|启动任务)", re.IGNORECASE),
            IntentType.KAIGONG,
            "py -3 scripts/jhoc_kaigong.py",
            ".agents/skills/kaigong/SKILL.md",
            "InquiryGate",
        ),
        (
            re.compile(r"(\$shougong|/shougong|^shougong$|^/收工$|^收工$|收工清理|收工闭环|36协审)", re.IGNORECASE),
            IntentType.SHOUGONG,
            "py -3 scripts/jhoc_shougong.py",
            ".agents/skills/shougong/SKILL.md",
            "36CoReview",
        ),
        (
            re.compile(r"(论文研读|研读论文|去学术包装|paper-to-knowledge-distiller|paper-distiller)", re.IGNORECASE),
            IntentType.PAPER_DISTILLATION,
            "py -3 scripts/deep_read_paper_vs_video.py",
            ".agents/skills/paper-to-knowledge-distiller/SKILL.md",
            "AntiSycophancy",
        ),
        (
            re.compile(r"(\$latent|/paradigm|/latent|潜空间|跨界同构|机制同构|仿生重构|第一性原理|打破定式)", re.IGNORECASE),
            IntentType.LATENT_SPACE_ACTIVATION,
            "",
            ".agents/skills/latent-space-activator/SKILL.md",
            "147",
        ),
        (
            re.compile(r"(token-stats|/token_stats|token_stats|额度查询|账户额度|账户配额|配额检测|token统计)", re.IGNORECASE),
            IntentType.TOKEN_STATS,
            "py -3 scripts/jhoc_token_stats.py",
            ".agents/skills/token-stats/SKILL.md",
            "QuotaFuse",
        ),
        (
            re.compile(r"(安全审计|提权攻击|注入攻击|漏洞|CVE|bypass|token_guard|path_guard)", re.IGNORECASE),
            IntentType.SECURITY_AUDIT,
            "py -3 scripts/validate_acceptance_artifacts.py",
            "",
            "394",
        ),
        (
            re.compile(r"(死锁排查|单测失败|test_.*fail|修复报错|排查报错|traceback|crash)", re.IGNORECASE),
            IntentType.DETERMINISTIC_ENGINEERING,
            "py -3 -m unittest discover tests",
            "",
            "402",
        ),
    )

    _EXPLANATORY_RE = re.compile(
        r"(什么是|解释一下|为什么|介绍一下|介绍下|区别是什么|原理是|how does|what is|why does|explain)",
        re.IGNORECASE,
    )

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.root = workspace_root or ROOT
        self._cached_index: dict | None = None
        self._index_mtime: float = 0.0
        self.index_path = self.root / ".agents" / "plugins" / "governance-engine" / "data" / "local_asset_index.json"

    def _load_index(self) -> dict | None:
        if not self.index_path.is_file():
            # Try memory backup
            mem_path = self.root / "memory" / "local_asset_index.json"
            if mem_path.is_file():
                self.index_path = mem_path
            else:
                return None

        try:
            mtime = self.index_path.stat().st_mtime
            if self._cached_index is None or mtime != self._index_mtime:
                self._cached_index = json.loads(self.index_path.read_text(encoding="utf-8"))
                self._index_mtime = mtime
            return self._cached_index
        except Exception:
            return None

    def classify(self, prompt: str) -> IntentMatchResult:
        if not prompt or not prompt.strip():
            return IntentMatchResult(
                intent=IntentType.GENERAL_CONVERSATION,
                confidence=1.0,
                tier_hit="TIER_1_RULE",
                is_execution=False,
            )

        clean_prompt = prompt.strip()
        is_execution = not bool(self._EXPLANATORY_RE.search(clean_prompt))

        # -------------------------------------------------------------
        # 1. Tier 1: Deterministic Rules (< 0.1ms)
        # -------------------------------------------------------------
        for pattern, intent, target_tool, scaffolding, lesson_id in self._TIER_1_RULES:
            match = pattern.search(clean_prompt)
            if match:
                matched_kw = match.group(0)
                lesson_warning = ""
                if lesson_id == "147":
                    lesson_warning = "[LESSON #147 WARNING] Anti-Pattern: Roleplaying external models | Invariant: Never roleplay Codex/Claude; must invoke real CLI"
                elif lesson_id == "InquiryGate":
                    lesson_warning = "[GATE INVARIANT] Inquiry Gate: Pre-flight inquiry must be confirmed before editing code"
                elif lesson_id == "36CoReview":
                    lesson_warning = "[36 CO-REVIEW INVARIANT] 3 self-audits + 6 invariant co-reviews mandatory before task close"
                elif lesson_id == "402":
                    lesson_warning = "[LESSON #402 WARNING] Anti-Pattern: Paper architecture without dynamic recall | Invariant: Every capability must have query path"

                # Gate constraint
                gate_constraint = ""
                if intent in {IntentType.MULTI_MODEL_CO_REVIEW, IntentType.PLAN_REVIEW} and is_execution:
                    gate_constraint = "Physical CLI execution required. Pure-text narrative roleplay will be rejected."

                ephemeral = LessonTemplateRenderer.render_ephemeral_package(
                    intent_name=intent.value,
                    scaffolding_path=scaffolding,
                    target_tool=target_tool if is_execution else "",
                    lesson_warning=lesson_warning,
                    gate_constraint=gate_constraint,
                )

                return IntentMatchResult(
                    intent=intent,
                    confidence=1.0,
                    tier_hit="TIER_1_RULE",
                    is_execution=is_execution,
                    matched_triggers=(matched_kw,),
                    ephemeral_lines=ephemeral,
                )

        # -------------------------------------------------------------
        # 2. Tier 2: In-Memory CJK 2-Gram Topology Overlap (~ 1ms)
        # -------------------------------------------------------------
        index_data = self._load_index()
        if index_data:
            bigram_index = index_data.get("bigram_index", {})
            assets_list = index_data.get("assets", [])
            assets_by_id = {a["asset_id"]: a for a in assets_list}

            prompt_bigrams = set(compute_char_bigrams(clean_prompt))
            asset_scores: dict[str, int] = {}
            for bg in prompt_bigrams:
                for aid in bigram_index.get(bg, []):
                    asset_scores[aid] = asset_scores.get(aid, 0) + 1

            if asset_scores:
                best_id, best_count = max(asset_scores.items(), key=lambda x: x[1])
                # Require at least 2 bigram hits to prevent random noise
                if best_count >= 2:
                    asset_raw = assets_by_id.get(best_id, {})
                    rec = AssetRecord.from_dict(asset_raw)
                    intent_str = rec.intent_affinity[0] if rec.intent_affinity else "DETERMINISTIC_ENGINEERING"
                    try:
                        resolved_intent = IntentType(intent_str)
                    except ValueError:
                        resolved_intent = IntentType.DETERMINISTIC_ENGINEERING

                    tool_cmd = rec.executable_tools[0] if rec.executable_tools else ""
                    lesson_warning = ""
                    if rec.negative_lessons:
                        nl = rec.negative_lessons[0]
                        lesson_warning = LessonTemplateRenderer.render_lesson_warning(nl, positive_tool=tool_cmd)

                    ephemeral = LessonTemplateRenderer.render_ephemeral_package(
                        intent_name=resolved_intent.value,
                        scaffolding_path=rec.path,
                        target_tool=tool_cmd if is_execution else "",
                        lesson_warning=lesson_warning,
                    )

                    return IntentMatchResult(
                        intent=resolved_intent,
                        confidence=min(0.95, 0.5 + 0.1 * best_count),
                        tier_hit="TIER_2_TOPOLOGY",
                        matched_asset=rec,
                        is_execution=is_execution,
                        matched_triggers=tuple(prompt_bigrams),
                        ephemeral_lines=ephemeral,
                    )

        # -------------------------------------------------------------
        # 3. Tier 3: Safe Fallback
        # -------------------------------------------------------------
        return IntentMatchResult(
            intent=IntentType.GENERAL_CONVERSATION,
            confidence=0.5,
            tier_hit="TIER_3_FALLBACK",
            is_execution=is_execution,
        )
