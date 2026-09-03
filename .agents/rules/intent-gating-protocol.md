# 意图前置安检与技能装配强制门禁协议 (Intent Gating & Skill Assembly Protocol)

> **核心戒律**：模型对意图的自然语言软判断极易发生“注意力钝化”与“惯性偷懒”。在 JHOC 体系中，**严禁凭惯性直接输出平庸方案。遇架构突围、开工反问、学术论文或规划评审诉求，必须前置执行意图判定并强制装配对应货架技能。**

---

## 1. 触发场景与意图特征识别 (Intent Triggers)

意图分类器 [`src/jhoc/intent/classifier.py`](file:///g:/JHOC/src/jhoc/intent/classifier.py) 将用户输入严格分类，并映射到 [`SHELF.md`](file:///g:/JHOC/.agents/skills/SHELF.md) 中已准入的权威技能：

| 意图枚举 (`IntentType`) | 核心触发特征 | 强制装配货架技能 | 必须产出的规范结构 |
| :--- | :--- | :--- | :--- |
| **`LATENT_SPACE_ACTIVATION`** | 突破套话/机制颠覆/跨学科映射/第一性原理/相变涌现 | [`latent-space-activator`](file:///g:/JHOC/.agents/skills/latent-space-activator/SKILL.md) | **四重算子**：黑名单禁词 + 物理映射表 + 离散方程 + 极端防暴代码 |
| **`COUNTER_QUESTIONING`** | 新功能需求/架构改造/开工反问/方向校准/细化需求 | [`counter-questioning-probe`](file:///g:/JHOC/.agents/skills/counter-questioning-probe/SKILL.md) | **四大正交反问**：范围与边界 + 架构取舍 + 异常降级 + 长期治理 |
| **`PAPER_DISTILLATION`** | 前沿论文/ArXiv/学术包装/研读论文/去包装/算法提炼 | [`paper-to-knowledge-distiller`](file:///g:/JHOC/.agents/skills/paper-to-knowledge-distiller/SKILL.md) | **五步实证法**：痛点定位 + 剥离 LaTeX 表象 + 消融造假排查 + 本地单机闭环 |
| **`PLAN_REVIEW`** | 规划评审/方案评审/架构对齐/执行风险/plan-review | [`codex-plan-review`](file:///g:/JHOC/.agents/skills/codex-plan-review/SKILL.md) | **三维路径清单**：改动项 + DOWN/UP/FORK 影响分析 + 可证伪单测命令 |
| **`KAIGONG`** | 开工/启动任务/开工门禁/kaigong | [`kaigong`](file:///g:/JHOC/.agents/skills/kaigong/SKILL.md) | **开工五步门禁**：物理路径核对 + 宪法与零Emoji纯度 + 蒸馏三问 + 目标基准绑定 |
| **`SHOUGONG`** | 收工/完成交付/收工清理/shougong | [`shougong`](file:///g:/JHOC/.agents/skills/shougong/SKILL.md) | **收工五步闭环**：全量单测硬通 + Git状态核对 + 字符纯度复核 + 未决交接清单 |
| **`POST_TASK_MEMORY`** | 共享记忆归档/任务收尾归档/落盘记忆 | [`post-task-shared-memory`](file:///g:/JHOC/.agents/skills/post-task-shared-memory/SKILL.md) | **记忆持久化四步**：Session提炼 + 三维影响归档 + 新错题/教训落盘 + 索引自适应更新 |

---

## 2. 意图前置硬门禁约束 (Pre-Flight Gate)

- **严禁行为**：
  1. 严禁直接跳过技能，凭自回归惯性生成泛泛而谈的工程套话；
  2. 严禁在命中 `COUNTER_QUESTIONING` 时由外部 Review Policy 的自动审批（`stop hook auto-approval`）直接静默推向执行；
  3. 严禁在命中 `PAPER_DISTILLATION` 时盲目赞叹论文中的 LaTeX 高深包装；
- **强制前置动作**：
  1. 必须判定该任务命中的 `IntentDecision`；
  2. 必须确认已装配并严格遵从 `enforced_scaffolding` 指定的货架技能；
  3. 输出中必须显式呈现该技能规定的专业骨架。

---

## 3. 契约违规判定 (Contract Violation)

- 若用户提出了符合上述意图特征的命题，而 Agent 的输出中缺失对应货架技能的规约结构，一律判定为触发 **`E_GATING_VIOLATION`** 契约违规；
- 违规输出必须立即自我熔断并按本协议推倒重来。
