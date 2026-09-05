---
name: content-generative-harness
canonical_id: content-generative-harness
aliases: ["content-generative-harness", "内容生成式规范", "生成式Harness", "内容生成设计规范", "generative-skill-spec"]
description: "通用内容生成式 Skill 架构与驾驭工程规范 — 统领复杂内容创作（长文/视频/课件/研报）的输入归一、双阶段检查点、受控协议逃生舱、物理隔离并发与最小切片自愈进化。"
version: 1.0.0
category: methodology
trigger: ["content-generative-harness", "内容生成式规范", "生成式Harness", "内容生成设计规范", "内容生成Skill设计"]
when_to_use: ["设计、审查或重构任何面向复杂长内容的生成式 Skill 时", "构建具备高可控性、防幻觉、多检查点的人机协同内容流水线", "为长文、视频、课件、图表、报告等非对话型 Agent 建立工程边界与自检契约"]
mutable_by_agent: false
skill_tier: domain
---

# 通用内容生成式 Skill 架构与设计规范 (content-generative-harness)

> **Authority**: Governed under **JHOC Agent 宪法体系** ([`g:\JHOC\AGENTS.md`](file:///g:/JHOC/AGENTS.md)) 与 [`ADR-0009-registry-shelf-quota.md`](file:///g:/JHOC/docs/adr/ADR-0009-registry-shelf-quota.md)
> **Physical Location**: `g:\JHOC\.agents\skills\content-generative-harness\`
> **Design Pattern**: 确定性 Harness 外部驾驭工程，适用于所有多媒体与结构化长内容生成场景。

---

## 1. 规范定位与核心哲学

面向长文本、精美排版网页、多媒体课件、动效视频等复杂交付物，**严禁依赖 Prompt 玄学与模型黑盒裸写代码**。
本规范确立了复杂生成式任务必须遵循的**六大通用工程支柱**，作为 JHOC 体系内所有内容生成型技能（如 `web-video-presentation`, `beautiful-article` 等）的通用顶层契约。

---

## 2. 生成式 Harness 六大通用工程支柱

### 支柱一：输入归一化与事实锚点 (Input Standardization)
1. **唯一事实源 (`source.md`)**：
   - 外部多源素材（URL/PDF/DOCX/纯文本/语音转录等）必须在 Phase 1 统一提纯并编译为纯文本 Markdown 事实底座（`source/source.md`）。
   - 后续所有编辑、写作、分卷仅以该文件为唯一输入，阻断外部网络的不可控脏数据。
2. **缺陷显式暴露 (`extraction-notes.md`)**：
   - 转换中遇到模型低置信度内容（缺失图表、残缺公式、冲突参数），必须写入记录文件，严禁让模型在后续环节进行“无意识的合理化脑补与幻觉填充”。
3. **目标语言解耦**：
   - 最终文章语言若与源语言不一致，必须在事实源阶段先产出地道的目标语言翻译版（`source.<lang>.md`），严禁在复杂的排版与代码编写环节边写边译。

---

### 支柱二：两阶段人工检查点架构 (Two-Phase Gate Review)
严禁一键无人值守跑完全流程，人类裁判必须在两大关键节点把关：

```text
[素材标准化: source.md] -> [规划出方案: plan.md]
                                 |
                        [★ 检查点 1: 方案门禁] (禁止打包，逐项确认)
                                 |
                        [早期样张先行开发 (First Spread / Chapter 1)]
                                 |
                        [★ 检查点 2: 样张基准锁定] (确立全剧密度与视觉基准)
                                 |
                        [全量流水线生产 (顺序控费模式 或 多Agent并行模式)]
                                 |
                        [★ 检查点 3: 最终交付裁决]
```

1. **检查点 1 (方案门禁)**：
   - 必须停顿，独立确认 5 大关键决策：**保留比例/类型、视觉主题选型、版式规格、配图策略、结构开关**。
   - 严禁替用户偷渡默认选项，必须独立收集决策。
2. **检查点 2 (早期样张验收)**：
   - 强制先单独完成第一章或“首屏 + 第一节 + 代表性复杂图表”。
   - 以极小成本确立全剧的字阶、行高、留白比例与动效节奏；若方向偏差立即纠偏。

---

### 支柱三：受控组件协议与主题逃生舱 (Component Protocol & Escape Hatch)
1. **高层语义组件层**：
   - 大模型只负责拼装规范化的语义组件（如 `reacticle` 或规范卡片）；排版布局由底层样式库保证，杜绝模型自行手写裸 CSS 导致的排版崩塌。
2. **主题受控逃生舱 (Raw 容器)**：
   - 复杂图表、SVG、微交互允许进入 Raw 容器自由发挥；
   - **铁律约束**：Raw 内的所有颜色、字号、圆角必须强制使用主题全局 CSS Token，严禁硬编码写死十六进制色值，牢牢守住设计系统一致性。

---

### 支柱四：物理隔离与并发编排 (Physical Isolation & Concurrency)
1. **一节一文件物理隔离**：
   - 强制将各章节拆分为独立的物理文件（如 `sections/NN-*.tsx` 或 `chapters/chNN/`）。
   - 顶层入口（`Article.tsx` / `App.tsx`）仅作为 Assembler 装配器，只负责 import 排序，不承载具体业务排版。
2. **样式命名空间前缀**：
   - 模块 CSS 类名强制携带前缀（如 `.ch01-title`），杜绝多 Agent 并行开发时的全局样式污染。
3. **步数唯一事实源恒等式 (Invariants)**：
   - 涉及多模态（分镜、配音）时，步数最大值必须与音频清单长度绝对恒等：
     $$\max(\text{Step}) + 1 \equiv \text{Manifest.length}$$

---

### 支柱五：上下文阶段性分片与文件化工作记忆 (Context & Working Memory)
1. **渐进式加载 (Phase-Scoped Context)**：
   - 严禁开局全量倾倒所有手册；阶段一仅读抽取规范，阶段二仅读大纲规范，阶段三仅读代码模板与对应主题 Token。
2. **文件化持久状态**：
   - 中间决策必须物理落盘（`source.md`, `plan.md`, `narrations.ts`），长任务后续步骤强制回读物理文件，抵抗长窗口滚动遗忘。

---

### 支柱六：独立多视角审查与自愈进化闭环 (Review & Self-Evolution)
1. **击破模型自评失真**：
   - 严禁编写代码的 Agent 口头自评放行，必须由独立 Reviewer Agent 执行跨视角审查：
     - **内容审查员 (Editorial)**：事实完整度、有无过度阉割、逻辑连贯性；
     - **视觉审查员 (Visual)**：响应式溢出、留白空洞、主题 Token 合规性；
     - **技术审查员 (Technical)**：控制台报错、构建构建完整性、失效链接。
2. **最小切片定向修复原则**：
   - 严禁出现缺陷时推倒重做整章；将问题定位至 [节奏 / 视觉 / 内容 / 代码]，仅修补具体受损文件。
3. **Skill 自我进化飞轮**：
   - 审查与修复记录沉淀至 `review/repair-log.md`；高频重复缺陷自动回流并固化为 Skill 前置 Checklist 与拦截规则。

---

## 3. 设计审查自检清单 (Skill Designer's Checklist)

- [PASS] 交付载体是否为状态可控媒介（HTML/SVG/TSX 状态机），而非黑盒不可控抽卡？
- [PASS] 是否设计了 `source.md` 事实底座与 `extraction-notes.md` 缺陷标注？
- [PASS] 是否具备方案确认门禁 (Checkpoint 1) 且严禁偷渡默认值？
- [PASS] 是否具备首屏/第一章独立验收基准 (Checkpoint 2)？
- [PASS] 是否落实了“一节一文件 + 独立样式前缀”的物理隔离？
- [PASS] 复杂视觉是否通过受全局主题 Token 约束的 Raw 逃生舱实现？
- [PASS] 是否具备独立 Reviewer 审查与最小切片定向修复机制？
- [PASS] 修复日志是否物理落盘，具备反思自进化链路？
