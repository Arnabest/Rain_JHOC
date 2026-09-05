---
name: worklog-distiller
canonical_id: worklog-distiller
aliases: ["worklog-distiller", "工作日志", "日志总结", "worklog", "worklog-summary", "日报总结", "成果简报"]
version: 1.0.0
category: presentation
mutable_by_agent: false
trigger: ["worklog-distiller", "工作日志", "日志总结", "worklog", "worklog-summary", "日报总结", "成果简报", "/worklog"]
when_to_use: ["用户要求总结今天或近期工作日志、生成开发日报或向非技术人员汇报工作进展", "任务收尾或阶段性交付时将代码变动与技术堆栈转译为人类阅读友好的白话成果", "需要提取 Git 提交、Session 记忆与单测数据并按四层结构（极速看板/直观变化/待办事项/技术存证）排版输出"]
description: "面向人类阅读友好的自动化工作日志总结 Skill — 从 Git 提交、会话记忆与测试产物中提取事实，去除技术黑话并转译为业务价值，按四层结构（30秒看板/直观变化/待办事项/技术证据）生成清爽纯净的 Markdown/终端日志。"
skill_tier: domain
---

# Worklog Distiller (面向人类阅读友好向的工作日志白话蒸馏器)

> **Authority**: Governed under **JHOC Agent 宪法体系** ([`g:\JHOC\AGENTS.md`](file:///g:/JHOC/AGENTS.md)) 与 [`ADR-0009-registry-shelf-quota.md`](file:///g:/JHOC/docs/adr/ADR-0009-registry-shelf-quota.md)
> **Physical Location**: `g:\JHOC\.agents\plugins\domain-content\skills\worklog-distiller\`
> **Core Engine**: `scripts/jhoc_worklog.py`
> **Output Target**: 终端 / 聊天窗口直出，持久化归档至 `docs/worklogs/worklog-YYYY-MM-DD.md`

---

## 1. 技能定位与核心原则

---

## 2. 交付形态与双模态架构

`worklog-distiller` 支持两种互补的输出模式，满足不同阅读场景：

### 模式 A：四层速览看板模式 (Standard Glance Mode)
适合日常站会、每日下班前 30 秒快速了解状态、以及向非技术管理者快速同步进度：
- **顶层：30 秒极速看板**：一句话核心成果、整体状态标签、单测通过率与改动模块量；
- **二层：人类可感知的直观改动**：采用“痛点 -> 改进 -> 现状效果”三段式阐述用户看得见、摸得着的改动；
- **三层：幕后系统加固与技术改造**：用大白话阐述底层代码重构、防崩溃锁机制与接口统一；
- **四层：需要人类拍板或配合的事项**：醒目标注 `[ACTION]` / `[INFO]`，不淹没关键决策；
- **底层：自动化验证与存证记录**：提供单测命令、通过率、文件统计与 Git 提交锚点。

### 模式 B：单问题独立技术日志复盘模式 (One Problem = One Standalone Blog Post)
面向**开发新手与工程团队**，坚持“一个问题对应一篇独立日志”。内容详实、背景丰富、技术分析思路清晰、解释通俗易懂，杜绝空洞黑话与自恋吹捧。每篇日志包含 9 大结构化章节：
0. **【零、 知识图谱与全链路关系链】**：
   - 全网拓扑锚点与节点实体映射（`worklog` 唯一标识）；
   - 强关系图谱：关联任务归档（`derived_from`）、Git 提交（`observed_in`）、解决源码模块（`solves`）、可证伪单测（`verified_by`）、沉淀教训（`related_to`）；
1. **【一、 业务背景：我们在做什么系统？】**：系统架构定位、业务初衷与长效价值目标；
2. **【二、 案发现场：问题是怎么出现的？】**：现场还原、操作链路触发、特定数据输入与首次暴露表象；
3. **【三、 技术深潜：问题的本质与底层机理】**：用通俗易懂的白话和物理比喻剖析深层根因与状态机/操作系统机制；
4. **【四、 避坑排障：我们走过的弯路与失败尝试】**：探索走过的弯路、新手直觉解法 A/B 为什么失败以及踩坑教训；
5. **【五、 终局方案：彻底解决的代码实现与 Diff】**：
   - 核心架构重构设计；
   - **5.1 案例核心代码段落 (Case Code Snippets)**：展示生产环境核心实现与逐行注释；
   - **5.2 精准变更比对 (Unified Code Diff)**：包含 `+` 和 `-` 的标准 diff 语法块；
6. **【六、 经验沉淀：给开发新手的思考与心智模型】**：防御性编程准则、设计取舍与错题库心智模型；
7. **【七、 物理实测：如何证明真的修好了？】**：单元测试通过率、覆盖度与可证伪单机验收证据；
8. **【八、 问题生命周期与演进履历 (Dynamic Lifecycle & Evolution)】**：
   - 当前生命周期状态：`INVESTIGATING` / `MITIGATED` / `RESOLVED` / `SUPERSEDED` / `REOPENED_UNRESOLVED`；
   - **8.1 异构条件复现追踪**：记录在网络抖动、容器环境、嵌套语法等不同软硬件边界下的复现现象与根本原因；
   - **8.2 更优解迭代演进**：记录后续开发学习中发现的更优架构方案、改进版源码及 Unified Diff。

---

## 3. 触发方式与指令映射

当用户输入以下任何形式时自动激活：
- `/worklog` / `工作日志` / `总结工作日志` / `今日日报` -> 默认激活速览看板
- `/worklog blog` / `技术博客日志` / `一个问题一篇日志` / `写问题复盘日志` -> 激活单问题独立复盘模式
- 命令行直接调用：

```bash
# 1. 默认速览看板（直接输出到终端，适合管理者与站会）
python scripts/jhoc_worklog.py

# 2. 技术博客模式：一个问题对应一篇日志（输出每个问题的完整独立长文）
python scripts/jhoc_worklog.py --blog

# 3. 批量生成并保存为独立日志文件：docs/worklogs/YYYY-MM-DD-<slug>.md 并构建关系图谱
python scripts/jhoc_worklog.py --blog --save --graph

# 4. 指定单个问题 slug 仅输出/保存该问题的独立日志
python scripts/jhoc_worklog.py --blog --case windows-app-alias-python-conflict --save

# 5. 构建全链路知识图谱文件 (docs/worklogs/worklog-knowledge-graph.json)
python scripts/jhoc_worklog.py --graph

# 6. 原地修改与生命周期演进：记录异构条件复现 / 发现更优解时同步更新日志文件与图谱
python scripts/jhoc_worklog.py --update-case windows-app-alias-python-conflict \
  --new-status SUPERSEDED \
  --reproduce-condition "Windows Server Core 无图形界面无微软应用商店环境" \
  --reproduce-symptom "py -3 依然被 AppExecutionAlias 重定向至空死循环" \
  --better-solution "引入注册表真实可执行文件枚举与4级保底探测矩阵" \
  --better-code "def detect_python_robust(): ..." \
  --better-diff "@@ -10,3 +10,12 @@ ..." \
  --better-takeaway "不要信任环境变量中的符号链接，直接探测可执行头"
```

---

## 4. 知识图谱与动态演进引擎规范 (Knowledge Graph & In-Place Evolution)

### 4.1 实体与关系链标准 (Entity & Relationship Schema)
图谱生成器将日志中的问题与开发轨迹、任务归档进行实体三元组绑定并保存至 `docs/worklogs/worklog-knowledge-graph.json`，同时支持同步至 SQLite 知识库：
- **节点类型 (Node Types)**：`worklog`（日志长文）、`task_archive`（任务归档）、`git_commit`（开发轨迹提交）、`code_entity`（解决的代码文件/类）、`evidence`（单测与物理存证）、`lesson`（沉淀教训）。
- **关系谓词 (Relation Types)**：
  - `worklog` --[`derived_from`]-> `task_archive`（溯源到 `memory/session-*.md`）
  - `worklog` --[`observed_in`]-> `git_commit`（溯源到真实 Git 提交哈希）
  - `worklog` --[`solves`]-> `code_entity`（定位修改的业务代码文件）
  - `worklog` --[`verified_by`]-> `evidence`（关联物理单测与测试套件）
  - `worklog` --[`related_to`]-> `lesson`（关联经验沉淀库条目）
  - `worklog` --[`supersedes`]-> `worklog`（新版本更优解取代旧解法）

### 4.2 日志原地生命周期动态修改 (In-Place Dynamic Lifecycle Modification)
当满足以下任一条件时，**必须原地修改对应日志文件与知识图谱**，绝不推倒重来：
1. **不同边界条件复现 (Heterogeneous Reproduction)**：在不同硬件（如蓝牙耳机/外置声卡）、不同系统（如 Windows Server Core）、不同语境（如嵌套代码块）下复现，更新第 8.1 节，追加复现环境、表象与原因分析。
2. **后续学习发现更优解 (Superior Solution Evolution)**：在后续开发演进中找到开销更低、稳定性更高、更优雅的算法或架构，更新状态为 `SUPERSEDED`，并在第 8.2 节追加更优方案说明、更优代码段落与 Unified Diff，并重构经验沉淀。

---

## 5. 标准生成流水线 (The Distillation Pipeline)

1. **第 1 步：多源事实与 Diff 抽取 (Data & Diff Extraction)**
   - 调用 `git log`、`git diff HEAD~1 HEAD` 获取精确统一代码变动块；
   - 扫描 `memory/session-*.md` 提取结构化任务目标、改动清单与单测验收断言；
   - 扫描 `memory/task_timeline.jsonl` 获取任务生命周期状态。
2. **第 2 步：术语清洗与去黑话 (Sanitization & Translation)**
   - 过滤格式排版、临时脚本等代码级噪音；
   - 映射底层术语至用户视角（如 AST -> 代码语法结构，PUA -> 防乱码占位符，AEC -> 回声消除）；
   - 分流：用户可感知功能 (Visible) vs 底层架构加固 (Under-the-hood)。
3. **第 3 步：模版组装与字符纯度审查 (Rendering & Rule 7 Check)**
   - 根据参数渲染看板或技术博客复盘模版（包含章节 0 与章节 8）；
   - 嵌入实际案例代码段落与 unified diff 块；
   - 校验全文字符集，若存在任何 Emoji 或非法符号立即剔除并阻断；
4. **第 4 步：落盘与图谱关系同步 (Persistence & Graph Sync)**
   - 若指定 `--save`，独立日志分别落盘至 `docs/worklogs/YYYY-MM-DD-<slug>.md`；
   - 若指定 `--graph`，构建全链路关系图谱并落盘至 `docs/worklogs/worklog-knowledge-graph.json`；
   - 若执行 `--update-case`，原地修改目标日志并同步刷新图谱。

