from __future__ import annotations

from .classifier import IntentClassifier
from .schema import EnforcedPayload, IntentType


class IntentEnforcer:
    """Pre-flight physical prompt assembler and contract enforcer."""

    _DEFAULT_BANNED = ("心跳", "轮询", "超时重试", "Gossip", "广播", "增加缓存", "读写分离")

    def __init__(self, classifier: IntentClassifier | None = None) -> None:
        self._classifier = classifier or IntentClassifier()

    def enforce(self, prompt: str, *, allow_tier_3: bool = False) -> EnforcedPayload:
        decision = self._classifier.classify(prompt, allow_tier_3=allow_tier_3)

        if decision.intent != IntentType.LATENT_SPACE_ACTIVATION:
            return EnforcedPayload(
                original_prompt=prompt,
                effective_prompt=prompt,
                decision=decision,
                was_transformed=False,
            )

        # 物理拼装四重算子紧箍咒
        banned = decision.banned_tokens or self._DEFAULT_BANNED
        banned_str = "、".join(f"【{tok}】" for tok in banned)
        keywords_str = "、".join(decision.matched_keywords) if decision.matched_keywords else "跨界创新"

        scaffolding = (
            f"\n\n=======================================================\n"
            f"【JHOC 外部前置安检门禁：已物理装配 LATENT_SPACE_ACTIVATOR 算子】\n"
            f"触发级别: {decision.tier_hit} | 置信度: {decision.confidence:.2f} | 命中特征: {keywords_str}\n"
            f"根据 JHOC Rule 0 (LESSONS #147) 与宪法守则，严禁输出常规工程套话与顺从迎合，强制按以下规约执行：\n\n"
            f"【0. 显式前置：蒸馏三问 + 批判性反问 (强制置顶输出)】\n"
            f"- 问 1（层 1 统计素材）：当前事实是什么？（提取已知代码、客观数据、原始文本事实，绝不凭猜想推测）\n"
            f"- 问 2（层 2 抽象原则）：素材之间有什么模式与规律？（归纳底层模式、命名既有规约或机制同构）\n"
            f"- 问 3（层 3 推导判断）：这意味着什么、应该做什么？（给出物理事实/可运行代码可证伪的具体行动）\n"
            f"- 批判性反问：反问自查“是否有反例？我是否在顺从奉承？是否存在隐藏死穴或更优 Plan B？”\n\n"
            f"【1. 四重工程算子展开】\n"
            f"1. [负向阻断]：严禁在回答中出现以下套路词汇：{banned_str}；\n"
            f"2. [异构同构锚定]：将该问题的一级矛盾映射为具象的自然科学物理/生物/控制论机制，给出 1:1 状态映射表；\n"
            f"3. [动力学方程契约]：给出离散时间步下的状态转移数学表达式（含输入项、阻尼项、扩散项）；\n"
            f"4. [代码与死穴拷问]：给出单节点可运行 Python class 逻辑，并阐明面临【物理饱和/梯度消失风暴】时的自愈对策。\n"
            f"=======================================================\n"
        )

        effective_prompt = f"{prompt.strip()}{scaffolding}"

        # 记录装配凭据
        decision_with_scaffolding = decision.__class__(
            intent=decision.intent,
            confidence=decision.confidence,
            tier_hit=decision.tier_hit,
            matched_keywords=decision.matched_keywords,
            banned_tokens=banned,
            enforced_scaffolding=scaffolding.strip(),
            decision_id=decision.decision_id,
            created_at=decision.created_at,
        )

        return EnforcedPayload(
            original_prompt=prompt,
            effective_prompt=effective_prompt,
            decision=decision_with_scaffolding,
            was_transformed=True,
        )
