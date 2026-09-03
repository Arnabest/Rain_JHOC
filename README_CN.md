# JHOC — 剑之智能体运行微内核 (Jian Harness Operating Core)

**面向自主软件工程的零信任多模型外挂操作系统**

[English](README.md) | [简体中文](README_CN.md)

```text
[状态: 实验性科研原型 / DEMO]  [单测: 344/344 100% 满绿]  [字符纯度: 零 EMOJI 铁律]
[支持运行态: ANTIGRAVITY IDE (GEMINI) | CLAUDE CODE | OPENAI CODEX | DEEPSEEK]
```

> [!IMPORTANT]
> **项目定位声明：实验性科研架构原型与 DEMO (EXPERIMENTAL RESEARCH DEMO)**  
> JHOC 是一个**探索大模型物理边界约束、多智能体对抗协审与密码学存证账本的开源实验性科研原型与架构演示 Demo**。  
> 本项目旨在为智能体开发者、安全研究员及 AI 工程技术人员提供一个开箱即用的参考实现与实验沙箱，研究如何通过外挂 Harness 物理门禁终结生成式模型的幻觉失控。本项目**不是**现成的商业化企业 SaaS 产品；所有契约接口、IPC 协议与治理门禁均服务于实验研究与工程探索。

---

## 1. 概述与设计哲学

现代大语言模型（LLM）与自主编程智能体（AI Agent）展现出了惊人的代码生成速率，但在真实的软件工程环境中，若缺乏严密约束，无节制的自主运行必然引发严重危机：
- **毁灭性系统破坏**：模型误触发或幻觉执行破坏性命令（如 `rm -rf`, `git reset --hard`, 目录倒置管道删除）；
- **上下文腐化与自审批陷阱**：模型绕过人类，在内存中直接调用审批函数提权，或擅自篡改自身的安全门禁规则；
- **多模型写冲突与数据踩踏**：多个模型（如 Gemini、Claude、Codex）在同一代码库并发写入，缺乏排他互斥机制引发文件覆盖灾难；
- **审计失忆**：无法通过密码学凭证证明某段破坏性代码到底由哪个模型、在何时、基于谁的授权被调用。

**JHOC (Jian Harness Operating Core)** 是一套基于“本地优先 (Local-First)”与“零信任 (Zero-Trust)”原则构建的微内核治理系统，物理驻留在大模型客户端与宿主操作系统之间。它践行一条颠覆性的工程铁律：

> **防线必须物理驻留在外部 Harness，绝不能寄托在大模型的 Prompt 提示词里。**  
> **无论大模型如何产生幻觉、如何被恶意注入，系统行为在物理层面必须严格收敛至安全与确定。**

---

## 2. 三大核心物理平面架构

JHOC 在物理与逻辑上被划分为三个严格解耦的平面：

```text
+---------------------------------------------------------------------------------------+
|                                    JHOC 核心应用层                                     |
+---------------------------------------------------------------------------------------+
        |                                   |                                   |
        v                                   v                                   v
+-----------------------+   +-------------------------------+   +-----------------------+
|        管控平面        |   |           协同平面            |   |        存证平面       |
|    (Harness & Guard)  |   |       (Multi-Model Hub)       |   |   (Proof & Memory)    |
+-----------------------+   +-------------------------------+   +-----------------------+
| * PreToolUse 物理拦截  |   | * SQLite WAL 本地 IPC 总线    |   | * 五元组 BlackBox     |
| * PathGuard 全源码树  |   | * Presence 活性状态机          |   |   确定性 SHA-256 链   |
|   只读防自变异保护     |   | * Message 信封总线            |   | * L1/L2/L3 分层长程   |
| * 破坏性命令/混淆/    |   | * 排他互斥写租约 (Bearer Token)|   |   记忆持久化治理      |
|   Python 破坏原语矩阵 |   | * 跨 Harness 工具名称归一化   |   | * 3,327 节点知识图谱  |
| * 敏感凭据 Vault 隔离 |   |   (Gemini, Claude, Codex)     |   |   拓扑解耦索引        |
| * StopGuard 熔断闭环  |   | * 死锁与僵尸租约自动回收      |   | * 本地 SQLite 确定性  |
+-----------------------+   +-------------------------------+   +-----------------------+
```

### 2.1 管控平面 (Harness & Guard)
- **PreToolUse 前置物理门禁 (`scripts/jhoc_hook_gate.py`)**：在任何 IDE 或 CLI 工具执行前实施参数级深层拦截。
- **全源码树防自变异 (`mutable_by_agent: false`)**：`src/jhoc/**` 核心源码树、治理规则与门禁脚本对模型完全只读，模型无权自修改防御机制。
- **破坏性命令与混淆拦截矩阵**：全面封堵 `git reset --hard`、递归文件删除（`rd /s`, `rm -rf`, `Remove-Item -Recurse`）、管道倒置批量删除（`Get-ChildItem | Remove-Item`）、Python 底层破坏原语（`shutil.rmtree`, `os.unlink/remove`）以及 Base64 编码动态执行混淆。
- **逆向隔离沙箱**：当协助开发外部子项目时，严格阻止外部 Agent 跨越边界反向篡改中央母核源码。
- **敏感凭据隔离保险库 (`src/jhoc/guard/vault.py`)**：硬件与内存级凭据脱敏，模型仅能接触不透明句柄，密钥永不暴露于上下文中。

### 2.2 协同平面 (Multi-Model Hub)
- **零网络纯本地 IPC (`src/jhoc/hub/store.py`)**：基于本地 SQLite WAL（预写式日志）构建各模型通信的唯一权威状态源。
- **Presence 活性状态机**：追踪多模型在线状态（`IDLE`, `BUSY`, `CO_REVIEWING`, `CODING`, `WAITING_INPUT`, `TERMINATED`），具备租约超时自动收回机制。
- **Bearer Token 排他写互斥租约**：模型修改文件前必须申请租约，由系统派发防伪随机构造的 `lease_id`，杜绝其他模型伪造身份越权解开文件互斥锁。
- **跨 Harness 工具别名规范化**：自动将 Claude Code 的 `Bash`、Gemini 的 `run_command`、Codex 的 `terminal` 与各编辑工具规范化映射为统一门禁策略。

### 2.3 存证与记忆平面 (Proof & Memory)
- **五元组 BlackBox 确定性存证链 (`logs/p19-blackbox.jsonl`)**：按 `(USER, SEEN, THINK, TOOL, BACK)` 结构只追加记录，通过严格排序的 SHA-256 哈希构成防篡改链表。
- **L1/L2/L3 记忆分层治理体系**：
  - **L1 核心层 (常驻上下文)**：宪法法则与不可逾越红线；
  - **L2 货架层 (按需挂载)**：针对复杂任务的标准化技能包；
  - **L3 归档层 (离线检索)**：历史会话沉淀与通用错题本。
- **知识图谱投影**：基于 3,327 节点与 4,712 条拓扑关系提供解耦实体召回服务。

---

## 3. 仓库代码目录布局

```text
JHOC/
├── .agents/                    # Agent 运行时定制配置、Hook 声明、规则与技能
│   ├── hooks.json              # PreToolUse 物理生命周期门禁声明
│   ├── rules/                  # 11 项纯粹治理宪法协议 (Rule 0 至 Rule 7)
│   └── skills/                 # 7 大经静态 AST 与 YAML 审计准入的核心工程技能
├── AGENTS.md                   # 跨模型总宪法 (纯 ASCII 规范)
├── CLAUDE.md                   # Claude Code 原生快速启动规约
├── docs/                       # 架构设计、操作手册与错题沉淀
│   ├── runbooks/               # 模型接入手册与操作员指引
│   ├── lessons/                # 永久机制化错题本 (LESSON #01 - #402)
│   └── architecture/           # 系统架构设计与规范说明
├── memory/                     # 任务运行态时间线与交接包 (零数据副本中保持纯净)
├── runtime/                    # 本地运行态临时数据库与文件锁 (不入 Git)
├── logs/                       # 运行时黑盒日志与审计事件 (不入 Git)
├── schemas/                    # 约束所有数据契约与载荷的 JSON Schema
├── scripts/                    # 生产运维 CLI、门禁及生命周期脚本
│   ├── jhoc_kaigong.py         # 开工前置门禁与基准锁定
│   ├── jhoc_shougong.py        # 收工闭环复核、单测全跑与交接生成
│   ├── jhoc_hook_gate.py       # PreToolUse 物理拦截引擎
│   ├── jhoc_approve.py         # 人工审批工单管理 CLI
│   ├── jhoc_run_co_review.py   # 多模型对抗协审分发器
│   └── jhoc_log_stats.py       # 多模型操作、调用与 Token 审计大屏
├── src/jhoc/                   # 核心微内核 Python 包
│   ├── conductor/              # 任务编排与审批信箱
│   ├── context/                # 上下文脱敏编排与 Token 截断控制
│   ├── graph/                  # 知识图谱拓扑投影与索引
│   ├── guard/                  # 路径、频控与凭据安全守卫
│   ├── hub/                    # 多模型 SQLite WAL 协同中枢
│   └── proof/                  # 五元组黑盒哈希链引擎
└── tests/                      # 344 项高覆盖端到端单元测试与攻防边界用例
```

---

## 4. 快速开始

### 4.1 环境要求
- **Python**: 3.10 或更高版本
- **SQLite**: 3.35+ (标准库内置)
- **Git**: 2.30+
- **操作系统**: Windows / Linux / macOS 全平台兼容

### 4.2 安装与初始化
克隆纯净副本仓库并安装运行依赖：

```bash
git clone https://github.com/your-username/JHOC.git
cd JHOC
python -m pip install -e .
```

---

## 5. 标准化工程生命周期

在 JHOC 体系下，严禁无序、无记录、无门禁的盲跑开发。所有任务严格遵循三步走生命周期：

```text
[第一步: 开工 Kaigong] -> [第二步: 运行时执行与拦截] -> [第三步: 收工 Shougong 闭环]
```

### 5.1 第一步：开工前置门禁 (`Kaigong`)
在修改任何代码前，必须执行开工前置门禁，锁定工作区物理路径、核验字符纯度并绑定当前的 Git Commit 基准：

```powershell
python scripts/jhoc_kaigong.py "功能: 实现 SQLite 租约超时自动回收机制"
```

控制台输出：
```text
=== [JHOC KAIGONG PRE-FLIGHT GATE] ===
[PASS] Workspace verified: G:\JHOC
[PASS] Git tracking active in JHOC
[PASS] Zero-Emoji Discipline verified across active governance files
[INFO] Git Baseline Commit: 4cd01d1d37
[INFO] Task registered: 20260904T030000Z-feature_implement_sqlite_lease
[INFO] Title: 功能: 实现 SQLite 租约超时自动回收机制
gate: ALLOW
```

### 5.2 第二步：运行时执行与门禁拦截
在任务执行期间：
- 模型进行的任何写操作自动受 `PathGuard` 约束，且需先申请文件排他写租约；
- 模型尝试执行破坏性命令或越权读取凭据将被直接拦截，并自动生成审批工单。

#### 人工工单审批流 (`scripts/jhoc_approve.py`)
当必须执行高危操作时：
1. 门禁阻断直接执行，在 `runtime/inbox.db` 中生成工单并打印工单 ID；
2. 人类操作员在独立终端利用操作员私钥核验并单次批准：
   ```powershell
   python scripts/jhoc_approve.py list
   python scripts/jhoc_approve.py approve <工单ID> --note "操作员确认允许单次执行"
   ```
3. 门禁消耗该工单（300 秒单次有效 Token），仅允许执行一次，重放攻击被彻底阻断。

### 5.3 第三步：出厂收工硬闭环 (`Shougong`)
工作就绪后，执行收工闭环复核流水线：

```powershell
python scripts/jhoc_shougong.py
```

`Shougong` 自动按序执行物理复核：
1. JSON Schema 契约静态校验 (`scripts/validate_schemas.py`)；
2. 全库 **344 项单元测试** 全量回归；
3. 物理验收探针复核 (`scripts/validate_acceptance_artifacts.py`)；
4. Git 变更逐行扫描，终审杜绝 Emoji 违规 (Rule 7)；
5. 全局写冻结锁 (`runtime/write_freeze.lock`)；
6. 生成跨模型机器可读交接包 (`memory/handoff-latest.json`)；
7. 自动清空 Multi-Model Hub 中已占用的文件租约，并将 Presence 状态恢复为 `IDLE`。

---

## 6. 多模型运维审计大屏

在任何时候运行 `jhoc_log_stats.py`，即可一览全系统多模型调用频次、门禁阻断归因与工单流转：

```powershell
python scripts/jhoc_log_stats.py
```

大屏报表示例：
```text
======================================================================
                     JHOC OPERATIONAL AUDIT DASHBOARD                  
======================================================================
1. Task Execution Stream: Total Events: 113 | Armed: 104 | Closed: 1
2. Tool Gate & BlackBox  : Total Calls : 1055 | Allow: 388 | Deny: 667
3. Human Approval Inbox  : Total Tickets: 45 | Pending: 21 | Approved: 0
4. Vault Egress          : Total Egress Resolutions: 153
5. Top Denials           : Destructive Cmd (213), Mutex Conflict (80), Root Asset (78)
6. Model Attribution     :
   -> [antigravity-ide] Calls: 721 (Allow: 210, Deny: 511) | Leases: 0
   -> [claude-code]     Calls: 57  (Allow: 33,  Deny: 24)  | Leases: 0
   -> [codex-cli]       Calls: 33  (Allow: 33,  Deny: 0)   | Leases: 0
======================================================================
```

---

## 7. 自动化测试与验证

JHOC 配备了 344 项端到端全量自动化单测，全面覆盖零信任防御边界、并发竞态、契约兼容性与渗透攻防测试：

```powershell
# 1. 契约 Schema 静态校验
python scripts/validate_schemas.py

# 2. 运行全量 344 项单元与集成测试
python -m unittest discover -s tests -p "test_*.py"

# 3. 执行物理探针验收
python scripts/validate_acceptance_artifacts.py
```

单测执行结果：
```text
Ran 344 tests in 25.5s
OK
{"validated": true}
```

---

## 8. 智能体必须恪守的核心宪法 (AGENTS.md)

所有在 JHOC 治理体系下工作的 AI 智能体必须无条件遵守 [`AGENTS.md`](AGENTS.md) 规定的八大法则：

- **Rule 0: 元认知蒸馏与反顺从契约 (Anti-Sycophancy)**：坚决摒弃虚伪赞美与顺从偏误。面对复杂方案强制执行【素材统计 -> 抽象原则 -> 可证伪结论 + 批判性反问】；指出致命缺陷必须先于肯定。
- **Rule 1: 物理真实与度量守恒法则**：坚决摒弃学术玄学名词包装。严禁自指断言，严禁未证伪的假 Mock，严禁输出空哈希。
- **Rule 2: 零信任模型边界法则**：安全防线物理驻留在外部 Harness，模型无权自修改安全策略，违规一律 Fail-Closed 熔断。
- **Rule 3: 双平面物理隔离法则**：数据层经脱毒字面量化，操作层强类型参数化，凭据层内存脱敏隔离。
- **Rule 4: 静态能力封闭法则**：严禁模型在运行时为自己现场编写或赋予新工具（`mutable_by_agent: false`）。
- **Rule 5: 极简自持与单机确定性法则**：拒绝外部心跳依赖。依赖本地 SQLite WAL、纯 Python AST 与单机确定性。
- **Rule 6: 五元组链式证据法则**：以只追加哈希链表记录 `USER / SEEN / THINK / TOOL / BACK`，无凭证不结案。
- **Rule 7: 零 Emoji 表情与字符纯度铁律 (Zero-Emoji Discipline)**：坚决杜绝在任何代码、文档、报告、思考过程与对话输出中使用 Emoji 表情符号。状态一律使用 `[PASS]`, `[WARN]`, `[FAIL]`, `[INFO]`, `->` 纯净文本替代。

---

## 9. 开源许可证与社区贡献

本项目采用 **Apache License 2.0** 开源许可证。任何 Pull Request 必须保持 344 项单测全绿，并通过 `jhoc_shougong.py` 的全部静态与动态闭环审查。
