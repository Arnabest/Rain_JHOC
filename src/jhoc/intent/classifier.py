from __future__ import annotations

import json
import re
import urllib.request
from typing import Mapping

from .schema import DetectionTier, IntentDecision, IntentType


class IntentClassifier:
    """Tri-tier hybrid deterministic intent classifier.
    
    Tier 1: Deterministic regex/rule match (< 0.1ms)
    Tier 2: Metric-space keyword topological overlap (~ 1ms)
    Tier 3: Local LLM structured arbitration with schema (fallback for gray zone)
    """

    # Tier 1: 确定性显式命令与强特征词
    _TIER_1_PATTERNS: tuple[tuple[re.Pattern[str], IntentType, float], ...] = (
        (re.compile(r"(\$latent|/paradigm|/latent|潜空间|跨界|机制同构|异构同构|仿生重构|第一性原理)", re.IGNORECASE), IntentType.LATENT_SPACE_ACTIVATION, 1.0),
        (re.compile(r"(别说套话|不要套话|跳出定式|跳出套路|打破套路|打破定式|颠覆传统|反常规)", re.IGNORECASE), IntentType.LATENT_SPACE_ACTIVATION, 0.95),
        (re.compile(r"(论文研读|研读论文|论文去包装|去学术包装|paper-to-knowledge-distiller|paper-distiller|去包装)", re.IGNORECASE), IntentType.PAPER_DISTILLATION, 1.0),
        (re.compile(r"(arxiv\.org|论文|前沿理论|新范式|学术包装|读一读这篇)", re.IGNORECASE), IntentType.LATENT_SPACE_ACTIVATION, 0.95),
        (re.compile(r"(反问|细化需求|提问|方向校准|开工反问|探针提问|task-inquiry|direction-probe)", re.IGNORECASE), IntentType.COUNTER_QUESTIONING, 1.0),
        (re.compile(r"(规划评审|方案评审|架构对齐|plan-review|codex-plan-review|对齐计划)", re.IGNORECASE), IntentType.PLAN_REVIEW, 1.0),
        (re.compile(r"(\$kaigong|/kaigong|^kaigong$|^/开工$|^开工$|开工门禁|启动任务)", re.IGNORECASE), IntentType.KAIGONG, 1.0),
        (re.compile(r"(\$shougong|/shougong|^shougong$|^/收工$|^收工$|收工清理|收工闭环)", re.IGNORECASE), IntentType.SHOUGONG, 1.0),
        (re.compile(r"(post-task-shared-memory|共享记忆归档|任务收尾归档|post task archive|落盘记忆)", re.IGNORECASE), IntentType.POST_TASK_MEMORY, 1.0),
        (re.compile(r"(token-stats|/token_stats|token_stats|额度查询|账户额度|账户配额|配额检测|token统计|配额统计)", re.IGNORECASE), IntentType.TOKEN_STATS, 1.0),
        (re.compile(r"(安全审计|提权|注入攻击|漏洞|CVE|bypass|token_guard|path_guard)", re.IGNORECASE), IntentType.SECURITY_AUDIT, 1.0),
        (re.compile(r"(排查|修复|报错|traceback|oom|crash|死锁排查|故障诊断|单测失败|test_.*fail)", re.IGNORECASE), IntentType.DETERMINISTIC_ENGINEERING, 0.95),
    )

    # Tier 2: 领域特征锚点词库
    _TIER_2_ANCHORS: Mapping[IntentType, tuple[str, ...]] = {
        IntentType.LATENT_SPACE_ACTIVATION: (
            "同构", "映射", "相变", "涌现", "物理", "生物", "趋化性", "信息素", "自噬", "控制论", "差分方程", "李雅普诺夫", "耐受", "自愈", "范式"
        ),
        IntentType.COUNTER_QUESTIONING: (
            "反问", "维度", "边界", "取舍", "兜底", "降级", "治理", "MVP", "选项"
        ),
        IntentType.PAPER_DISTILLATION: (
            "论文", "arxiv", "公式", "消融", "实验", "基准", "包装", "伪需求", "推导"
        ),
        IntentType.PLAN_REVIEW: (
            "规划", "审查", "影响路径", "DOWN", "UP", "FORK", "风险", "证伪", "回滚"
        ),
        IntentType.KAIGONG: (
            "开工", "启动", "门禁", "基准", "对齐"
        ),
        IntentType.SHOUGONG: (
            "收工", "清理", "交接", "未决", "完成"
        ),
        IntentType.POST_TASK_MEMORY: (
            "记忆", "归档", "落盘", "持久化", "session"
        ),
        IntentType.TOKEN_STATS: (
            "额度", "配额", "token", "5h", "weekly", "剩余", "阈值", "告警", "重置"
        ),
        IntentType.DETERMINISTIC_ENGINEERING: (
            "代码", "修复", "重构", "接口", "契约", "schema", "sqlite", "wal", "测试", "断言", "函数", "模块", "配置", "规约"
        ),
        IntentType.SECURITY_AUDIT: (
            "权限", "越权", "拦截", "fail_closed", "sanitizer", "字面量", "密钥", "vault", "证据", "哈希", "sha256"
        ),
    }

    _SCAFFOLDING_BY_INTENT: Mapping[IntentType, str] = {
        IntentType.LATENT_SPACE_ACTIVATION: ".agents/skills/latent-space-activator/SKILL.md",
        IntentType.COUNTER_QUESTIONING: ".agents/skills/counter-questioning-probe/SKILL.md",
        IntentType.PAPER_DISTILLATION: ".agents/skills/paper-to-knowledge-distiller/SKILL.md",
        IntentType.PLAN_REVIEW: ".agents/skills/codex-plan-review/SKILL.md",
        IntentType.KAIGONG: ".agents/skills/kaigong/SKILL.md",
        IntentType.SHOUGONG: ".agents/skills/shougong/SKILL.md",
        IntentType.POST_TASK_MEMORY: ".agents/skills/post-task-shared-memory/SKILL.md",
        IntentType.TOKEN_STATS: ".agents/skills/token-stats/SKILL.md",
    }

    def __init__(self, local_llm_url: str = "http://127.0.0.1:8768/v1/chat/completions") -> None:
        self._llm_url = local_llm_url

    def classify(self, prompt: str, *, allow_tier_3: bool = False) -> IntentDecision:
        if not prompt or not prompt.strip():
            return IntentDecision(
                intent=IntentType.GENERAL_CONVERSATION,
                confidence=1.0,
                tier_hit=DetectionTier.TIER_1_RULE,
            )

        clean_prompt = prompt.strip()

        # =========================================================
        # Tier 1: 确定性规则引擎 (< 0.1ms)
        # =========================================================
        matched_keywords: list[str] = []
        for pattern, intent, conf in self._TIER_1_PATTERNS:
            match = pattern.search(clean_prompt)
            if match:
                matched_keywords.append(match.group(0))
                banned_tokens = ("心跳", "轮询", "重试", "Gossip", "广播") if intent == IntentType.LATENT_SPACE_ACTIVATION else ()
                return IntentDecision(
                    intent=intent,
                    confidence=conf,
                    tier_hit=DetectionTier.TIER_1_RULE,
                    matched_keywords=tuple(matched_keywords),
                    banned_tokens=banned_tokens,
                    enforced_scaffolding=self._SCAFFOLDING_BY_INTENT.get(intent),
                )

        # =========================================================
        # Tier 2: 空间拓扑重叠度计算 (~ 1ms，基于直接子串匹配)
        # =========================================================
        scores: dict[IntentType, float] = {}
        matched_by_intent: dict[IntentType, list[str]] = {}

        for intent, anchors in self._TIER_2_ANCHORS.items():
            matched = [k for k in anchors if k in clean_prompt]
            matched_by_intent[intent] = matched
            if matched:
                scores[intent] = len(matched) / (len(anchors) ** 0.5)

        if scores:
            best_intent, best_score = max(scores.items(), key=lambda item: item[1])
            if best_score >= 0.5:
                conf = min(0.95, round(best_score * 0.35 + 0.5, 2))
                banned = ("心跳", "轮询", "重试", "Gossip", "广播") if best_intent == IntentType.LATENT_SPACE_ACTIVATION else ()
                return IntentDecision(
                    intent=best_intent,
                    confidence=conf,
                    tier_hit=DetectionTier.TIER_2_METRIC,
                    matched_keywords=tuple(matched_by_intent[best_intent]),
                    banned_tokens=banned,
                    enforced_scaffolding=self._SCAFFOLDING_BY_INTENT.get(best_intent),
                )

        # =========================================================
        # Tier 3: 灰度地带本地极速模型裁决 (带强类型 JSON Schema)
        # =========================================================
        if allow_tier_3 and self._llm_url:
            decision = self._arbitrate_with_local_llm(clean_prompt)
            if decision is not None:
                return decision

        # 默认兜底
        return IntentDecision(
            intent=IntentType.GENERAL_CONVERSATION,
            confidence=0.5,
            tier_hit=DetectionTier.FALLBACK,
        )

    def _arbitrate_with_local_llm(self, prompt: str) -> IntentDecision | None:
        """Call local DeepSeek endpoint at temperature 0.0 with strict classification prompt."""
        system_instruction = (
            "你是一个严格的意图分类门禁。对用户输入分类为以下四类之一："
            "1. LATENT_SPACE_ACTIVATION (跨学科同构/打破套路/机制颠覆)\n"
            "2. DETERMINISTIC_ENGINEERING (常规工程排障/代码/测试)\n"
            "3. SECURITY_AUDIT (安全合规/漏洞审计)\n"
            "4. GENERAL_CONVERSATION (常规问答)\n"
            "必须输出单行 JSON，格式为: {\"intent\": string, \"confidence\": float, \"matched\": [string]}"
        )
        payload = {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"分析以下输入的意图：\n{prompt[:300]}"}
            ],
            "temperature": 0.0
        }
        try:
            req = urllib.request.Request(
                self._llm_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                text = res["choices"][0]["message"]["content"].strip()
                # 提取 JSON
                json_match = re.search(r"\{.*\}", text, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(0))
                    raw_intent = data.get("intent", "").upper()
                    conf = float(data.get("confidence", 0.7))
                    matched = data.get("matched", [])
                    if raw_intent in IntentType.__members__:
                        target_intent = IntentType(raw_intent)
                        banned = ("心跳", "轮询", "重试", "Gossip", "广播") if target_intent == IntentType.LATENT_SPACE_ACTIVATION else ()
                        return IntentDecision(
                            intent=target_intent,
                            confidence=conf,
                            tier_hit=DetectionTier.TIER_3_LLM_ARBITER,
                            matched_keywords=tuple(matched),
                            banned_tokens=banned,
                        )
        except Exception:
            pass
        return None
