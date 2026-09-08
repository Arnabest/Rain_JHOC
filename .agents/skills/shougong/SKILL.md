---
name: shougong
canonical_id: shougong
aliases: ["/收工", "收工", "shougong", "$shougong"]
description: "JHOC 任务收工闭环作业流：执行产物完整性复核、Git 状态核验、未决事项清单核对与环境清洁。"
version: 2.1.0
category: workflow
trigger: ["/收工", "收工", "shougong", "$shougong", "/shougong", "收工清理", "收工闭环"]
when_to_use: ["任务开发或重构完成后的最终交付阶段", "用户输入 /收工 或 收工", "复核全局状态并交接未决事项"]
skill_tier: core
---

# /收工 — JHOC 任务收工闭环作业流

## 1. 触发条件

- **强制执行**：用户输入 `/收工`、`收工`、`$shougong`；或阶段性代码开发与重构任务宣告结束之前；
- **免除条件**：纯日常问答无代码或配置变动；跳过时简要说明 `shougong skipped: pure chat`。

---

## 2. 机械执行两阶段 36 协审闭环（不可跳步）

### 阶段一：3 次收工物理自审 (Triple Self-Audits)
1. **自审 1：全量单测与契约硬验收**：
   - 运行原生物理收工闭环脚本（一键自动执行 Schema 校验、全量 380+ 单测与零 Emoji 门禁）：
     ```powershell
     python scripts/jhoc_shougong.py
     ```
   - 必须确认输出 `shougong: SUCCESS` 且退出码为 0，严禁带着失败或跳过状态收工；
2. **自审 2：零 Emoji 字符与控制台安全纯度**：
   - 扫描本次任务产生的所有文件和提交记录，确保绝无任何 Emoji 表情字符，杜绝 Windows GBK 终端崩溃；
3. **自审 3：Git 状态核查与临时文件清洁**：
   - 运行 `git status -s`，逐项检查改动清单，确认无遗留临时调试文件（如未清理的 `test_*.tmp`、临时 scratch 脚本）。

### 阶段二：6 维度多模型铁律协审 (Sextuple Invariant Co-Review)
- 调度真实外部模型 CLI（Codex CLI 与 Claude Code CLI），针对 JHOC 宪法六大铁律逐项执行对抗式独立审查：
  - Rule 1：物理真实（无虚假 Mock、无循环自指断言）；
  - Rule 2：零信任边界（外部 Fail-Closed 拦截）；
  - Rule 3：双平面隔离（数据清洗去指令化）；
  - Rule 4：静态能力封闭（反自变异与动态注入）；
  - Rule 5：单机极简自持（单机确定性保证）；
  - Rule 6：五元组链式证据（带 SHA-256 签名证据包落盘 `logs/co-review/`）。
- 生成统一的跨模型交接包 `memory/handoff-latest.json` 并正式交付。
