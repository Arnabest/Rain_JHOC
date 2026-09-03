---
name: shougong
canonical_id: shougong
aliases: ["/收工", "收工", "shougong", "$shougong"]
description: "JHOC 任务收工闭环作业流：执行产物完整性复核、Git 状态核验、未决事项清单核对与环境清洁。"
version: 2.1.0
category: workflow
trigger: ["/收工", "收工", "shougong", "$shougong", "/shougong", "收工清理", "收工闭环"]
when_to_use: ["任务开发或重构完成后的最终交付阶段", "用户输入 /收工 或 收工", "复核全局状态并交接未决事项"]
---

# /收工 — JHOC 任务收工闭环作业流

## 1. 触发条件

- **强制执行**：用户输入 `/收工`、`收工`、`$shougong`；或阶段性代码开发与重构任务宣告结束之前；
- **免除条件**：纯日常问答无代码或配置变动；跳过时简要说明 `shougong skipped: pure chat`。

---

## 2. 机械执行五步闭环（不可跳步）

1. **第 1 步：全量单测与契约硬验收**：
   - 运行原生物理收工闭环脚本（一键自动执行 Schema 校验、全量 270+ 单测与零 Emoji 门禁）：
     ```powershell
     python scripts/jhoc_shougong.py
     ```
   - 必须确认输出 `shougong: SUCCESS` 且退出码为 0，严禁带着失败或跳过状态收工；
2. **第 2 步：Git 状态核查与目录清洁**：
   - 运行 `git status -s`，逐项检查改动清单；
   - 确认无遗留临时调试文件（如未清理的 `test_*.tmp`、临时 scratch 脚本）；
3. **第 3 步：零 Emoji 字符纯度复核**：
   - 确保本次任务产生的文件和提交记录绝无任何 Emoji 表情字符；
4. **第 4 步：未决事项与交接对账**：
   - 明确列出本次交付的内容、剩余已知风险（Residual Risk）以及下一步建议（Next Steps）；
5. **第 5 步：完成声明**：
   - 提供最终可复核的 SHA-256 或命令执行证据，正式交付。
