---
name: post-task-shared-memory
canonical_id: post-task-shared-memory
aliases: ["post-task-shared-memory", "共享记忆归档", "任务收尾归档", "post task archive"]
description: "JHOC 任务收尾跨模型记忆持久化：将任务流转、DOWN/UP/FORK 原因推导、可证伪验证与教训自动落盘至 memory/ 与 docs/lessons/。"
version: 2.1.0
category: memory
trigger: ["post-task-shared-memory", "共享记忆归档", "任务收尾归档", "post task archive", "WUPDT", "落盘记忆"]
when_to_use: ["任务完成后写最终回复之前的自动记忆持久化", "沉淀新错题或经验教训", "跨会话与跨模型任务交接"]
skill_tier: core
---

# Post-Task Shared Memory — 任务收尾跨模型记忆持久化

## 1. 触发条件

- **触发时机**：属于生命周期阶段 6 (CLOSURE)，必须在 `python scripts/jhoc_shougong.py` 单测与契约 100% 满绿通过后方可执行；
- **前置阻断**：严禁在未运行或未通过 `shougong` 验收前提前归档；若测试失败，由 `shougong` 自动注入 `MemoryType.ERROR`，严禁写入虚假成功事实；
- **免除条件**：纯日常问答无任务沉淀时声明 `shared-memory skipped: pure chat`。

---

## 2. 机械持久化四步流

1. **第 1 步：提炼会话状态与交接**：
   - 记录或更新至 `memory/session-YYYYMMDD-topic.md`；
   - 包含：任务目标、改动文件清单、核心理由（Rationale）；
2. **第 2 步：三维影响分析归档**：
   - 记录修改节点的 DOWNSTREAM（下游依赖）、UPSTREAM（上游依赖）与 FORK（分支状态）；
3. **第 3 步：错题与教训永久固化**：
   - 若本次排查过程中发现了隐蔽 Bug、治理疏漏或反直觉陷阱（如 Emoji 遗漏、未接入检索等），**强制在 `docs/lessons/` 追加编号教训**，并在错题库注册；
4. **第 4 步：索引自适应更新**：
   - 确保新增教训与记忆能够被 `MemoryRetriever` 与 `GraphKnowledgeIndex` 正确索引与召回。
