---
name: paper-to-knowledge-distiller
canonical_id: paper-to-knowledge-distiller
aliases: ["paper-distiller", "academic-study", "论文研读", "学术提炼", "前沿技术学习", "论文去包装"]
description: "学术前沿论文研读与算法框架提炼套件 — 从 PDF/ArXiv 论文中系统提取问题定义、核心数学公式推导、消融实验证据、真金算法与伪创新/学术包装识别。"
version: 1.1.0
category: methodology
trigger: ["paper-to-knowledge-distiller", "paper-distiller", "论文研读", "研读论文", "学术提炼", "学习论文", "paper study", "论文去包装"]
when_to_use: ["接收到前沿学术论文（PDF/ArXiv）需要快速研读与提炼架构", "需要识别论文中是否存在学术名词通胀、虚浮包装与自指实验", "提取论文中的核心公式与代码实现路径并沉淀至本地工程"]
skill_tier: core
---

# 前沿论文研读与知识提炼套件 (paper-to-knowledge-distiller)

> **Authority**: Governed under **JHOC Agent 宪法体系** ([`g:\JHOC\AGENTS.md`](file:///g:/JHOC/AGENTS.md)) 与 [`anti-metaphysical-protocol.md`](file:///g:/JHOC/.agents/rules/anti-metaphysical-protocol.md)
> **Physical Location**: `g:\JHOC\.agents\skills\paper-to-knowledge-distiller\`

---

## 1. 论文研读五步实证法 (Five-Step Empirical Distillation)

面对任何学术论文或外部技术吹捧，必须执行以下五步物理蒸馏：

1. **问题本质与痛点定位 (Problem Formulation)**：
   - 论文声称解决的真实工程痛点是什么？
   - 是真痛点还是为了发论文生造的伪需求？
2. **核心数学公式与表象剥离 (Theoretical Foundation & Anti-Hype)**：
   - 剥离 LaTeX 符号与高大上物理/数学名词包装；
   - 还原其最质朴的代数方程、概率图模型或损失函数本质；
   - 严厉排查是否存在“把简单的查表/检索写成高维流形投影”的学术包装。
3. **消融实验与基准造假排查 (Ablation & Ground-Truth Verification)**：
   - 检查对比 Baseline 是否被刻意削弱？
   - 核心机制拿掉后，性能到底下降了多少？是否存在自指测试（输入断言输入）？
4. **与本地工程（JHOC）结合点 (Local Project Application)**：
   - 如果要引入本地，它的最小单机闭环是什么？
   - 它的物理代价（内存开销、延迟、复杂度、新故障面）是否被其带来的边际收益覆盖？
5. **知识沉淀与错题归档 (Knowledge Distillation)**：
   - 提炼出真正可落地的确定性算法伪代码；
   - 将其核心思路与可能的工程陷阱沉淀至知识图谱与经验库。

---

## 2. 批判性反问自查清单 (Paper Counter-Questioning Checklist)
- **包装排查**：这篇论文是否用玄学名词解释了已知的工程常识？
- **依赖排查**：是否必须依赖外部不可复现的庞大数据集或黑盒 API？
- **复杂度排查**：能否用 50 行纯 Python 和标准数据结构替代其庞大的框架？
