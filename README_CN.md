# Rain — 智能体运行微内核 (Rain / JHOC Harness Core)

**面向大语言模型自主工作流的零信任上下文编排框架**

[English](README.md) | [简体中文](README_CN.md)

```text
[状态: 实验性科研原型 / DEMO]
[探索目标运行时: ANTIGRAVITY IDE (GEMINI) | CLAUDE CODE | OPENAI CODEX | DEEPSEEK]
```

> [!IMPORTANT]
> **项目定位声明：实验性科研架构原型与 DEMO (EXPERIMENTAL RESEARCH DEMO)**  
> Rain (JHOC) 是一个**探索大模型物理边界约束、多智能体协同对抗与密码学存证账本的开源实验性科研原型与架构演示 Demo**。  
> 本项目旨在为智能体开发者、安全研究员及 AI 工程技术人员提供一个参考架构与探索沙箱，研究如何通过外挂 Harness 物理门禁探索对生成式模型不可预测行为的约束途径。本项目**不是**开箱即用的商用产品；所有契约接口、IPC 协议与治理策略均属于实验性设计，并不提供任何绝对安全的担保。
>
> **运行环境与交互范式说明**：  
>
> - **推荐环境**：本项目的主要开发与使用环境**推荐为智能体 IDE（作者日常深度使用 Antigravity IDE）**或命令行智能体终端；  
> - **无显式前端控制台**：本项目作为外挂微内核与上下文编排框架，**不提供显式的 Web / GUI 前端控制台**；  
> - **交互范式**：**推荐直接与大语言模型进行自然语言对话**，由模型在 Harness 门禁的物理约束下自主调用内置脚本与工具完成任务闭环。

---

## 1. 概述与探索背景

现代大语言模型（LLM）与自主编程智能体（AI Agent）展现出了快速的代码生成能力，但在复杂的代码工程中，无约束的自主执行往往面临以下工程挑战：

- **潜在命令风险**：模型可能因幻觉或误判尝试调用高危或破坏性命令；
- **自审批与提权隐患**：模型可能绕过外部授权，在同一进程或上下文中自我授权或修改自身安全设定；
- **多模型并发冲突**：多个不同厂商的智能体在同一代码库并行协作时，容易发生无互斥的文件覆盖与冲突；
- **缺乏可溯源存证**：缺乏防篡改的本地审计机制，难以精准复盘各模型的工具调用过程。

**Rain (JHOC)** 尝试从“本地优先 (Local-First)”与“零信任架构 (Zero-Trust)”出发，探索在模型客户端与宿主操作系统之间构筑外挂微内核治理体系的可能路径：

> **核心探索命题**：安全防线是否应物理驻留在外部 Harness，而非寄托在大模型的 Prompt 提示词中。  
> **设计目标**：探索如何借助外部门禁与单机确定性状态机，为自主模型的生成行为提供可度量、可复盘、可约束的工程边界。

### 1.1 本地实践中探索出的相对优势 (Empirical Observations from Local Practice)

通过在真实的单机多模型开发环境中持续迭代与测试，该架构在工程实践中探索出以下几点有价值的经验与相对优势：

1. **前置门禁拦截比纯提示词引导更具工程可控性**：
   - 依赖 System Prompt 引导模型“不要执行危险命令”，在复杂推理或上下文诱导下往往容易出现理解偏差或失效；
   - **实践体会**：尝试将防线移至宿主机 PreToolUse 钩子层，在工具调用实际发生前对写入路径、高危指令模式进行参数级检查与工单暂留，能够在很大程度上弥补模型仅靠自律可能带来的不确定性。

2. **本地轻量自持减少外部网络链路依赖 (Local-First Design)**：
   - 相比依赖云端消息队列、远程心跳中继或复杂分布式共识的方案，本地架构更加轻量；
   - **实践体会**：协同中枢主要基于 Python 3.10+ 标准库与本地 SQLite WAL 模式构建，在离线或弱网环境下仍可维持核心状态机运转，降低了外部服务抖动带来的影响。

3. **探索缓解异构模型协同写冲突的可行路径 (Multi-Model Mutex)**：
   - 不同厂商模型客户端（Gemini、Claude Code、Codex 等）工具命名与调用格式存在差异，并行工作时易发生无序写入与代码覆盖；
   - **实践体会**：通过在门禁层对常见工具语义进行规范化抽象，并配合带有生命周期（TTL）的排他写租约机制，为多模型在同一工作区协同工作探索出一种相对平滑、低开销的互斥机制。

4. **为调用行为提供可供复盘的结构化审计记录 (Forensic Audit Trail)**：
   - 在多智能体协作中，如果缺乏系统性日志，排查故障时往往难以理清不同模型在具体时序下的操作轨迹；
   - **实践体会**：通过将 `(USER, SEEN, THINK, TOOL, BACK)` 规范写入只追加的 SHA-256 哈希链中，为后续复盘与故障追溯提供了较好的一致性参考线索。

5. **引导模型在开工前收敛目标以缓解代码通胀 (Cognitive Gating)**：
   - 自主代理在缺乏前置审查时，容易出现盲目铺开代码量、频繁引入多余包装的倾向；
   - **实践体会**：在开工阶段引入批判性审视与影响路径推演，有助于促使模型在动手前先梳理核心边界，在一定程度上减轻了工程资产不必要的冗余膨胀。

---

## 2. 三大核心物理平面设计目标

JHOC 在架构设计上尝试探索三个解耦层面的治理模型：

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
| * 目标: PreToolUse    |   | * 目标: 基于本地 SQLite WAL   |   | * 目标: 五元组 BlackBox|
|   前置工具调用拦截    |   |   实现轻量化 IPC 进程通信     |   |   确定性哈希存证账本  |
| * 目标: 核心源码树    |   | * 目标: Presence 活性检测     |   | * 目标: 分层记忆治理  |
|   只读防自变异设想    |   | * 目标: 探索 Bearer Token 机制|   |   (L1/L2/L3)          |
| * 目标: 高危命令与混淆|   |   缓解文件写踩踏与竞态冲突    |   | * 目标: 知识图谱拓扑  |
|   模式特征拦截矩阵    |   | * 目标: 跨厂商工具名称抽象    |   |   解耦上下文召回      |
| * 目标: 凭据内存脱敏  |   | * 目标: 僵尸租约自动回收      |   | * 目标: 极简单机自持  |
+-----------------------+   +-------------------------------+   +-----------------------+
```

### 2.1 管控平面设计目的 (Control Plane Intents)

- **PreToolUse 前置拦截探索 (`scripts/jhoc_hook_gate.py`)**：旨在探索在 IDE 或 CLI 工具执行前实施参数级前置校验的途径；
- **核心源码防自修改设计 (`mutable_by_agent: false`)**：探索将 `src/jhoc/**` 核心源码树、治理规则与门禁脚本对模型设为只读，以抑制智能体自行修改防御规则的倾向；
- **高危破坏性操作防御模式**：尝试针对常见的误操作命令（如 `git reset --hard`、递归删除指令、批量管道删除）、底层文件系统原语（`shutil.rmtree`, `os.unlink`）以及脚本编码混淆设计模式匹配规则；
- **跨项目逆向隔离探索**：当协助开发外部子项目时，探索建立保护屏障以防止外部智能体意外修改母核体系；
- **凭据脱敏与隔离模型 (`src/jhoc/guard/vault.py`)**：探索内存级凭据隔离与出口解引用机制，以减少密钥直接暴露在模型上下文中的风险。

### 2.2 协同平面设计目的 (Multi-Model Hub Intents)
>
> 详细客户端接入配置、互斥租约与信封通信手册请参阅：[多模型协同配置与操作指南](docs/runbooks/MULTI_MODEL_COLLABORATION_GUIDE.md)

- **无网络本地 IPC 探索 (`src/jhoc/hub/store.py`)**：探索利用本地 SQLite WAL（预写式日志）作为多模型协同通信的权威状态源，避免对中心化云服务的依赖；
- **Presence 活跃状态机**：设计统一的心跳与状态追踪机制，探索多模型多任务协作时的生命周期管理；
- **排他写租约设计 (Bearer Token Mutex)**：尝试通过动态派发随机 `lease_id` 令牌，探索缓解多模型并发修改同一文件时的写入覆盖与竞态冲突；
- **跨 Harness 协议抽象**：探索对不同厂商模型客户端（Claude Code、Gemini、Codex 等）的工具调用接口进行归一化映射。

### 2.3 存证与记忆平面设计目的 (Proof & Memory Intents)

- **五元组 BlackBox 确定性存证原型 (`logs/p19-blackbox.jsonl`)**：探索以 `(USER, SEEN, THINK, TOOL, BACK)` 结构与确定性 SHA-256 哈希链，为工具调用行为提供可供复盘的审计记录；
- **分层记忆治理设想 (L1/L2/L3)**：探索将智能体记忆划分为常驻规则层、按需货架层与离线归档层的组织范式；
- **知识拓扑索引探索**：探索通过图谱拓扑关系在解耦环境下为智能体提供上下文召回能力。

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
├── schemas/                    # 约束数据契约与载荷的 JSON Schema
├── scripts/                    # 生产运维 CLI、门禁及生命周期脚本
│   ├── jhoc_kaigong.py         # 开工前置门禁与基准锁定
│   ├── jhoc_shougong.py        # 收工闭环复核、自检与交接生成
│   ├── jhoc_hook_gate.py       # PreToolUse 物理拦截引擎
│   ├── jhoc_approve.py         # 人工审批工单管理 CLI
│   ├── jhoc_run_co_review.py   # 多模型对抗协审分发器
│   └── jhoc_log_stats.py       # 多模型操作与审计大屏
├── src/jhoc/                   # 核心微内核 Python 包
│   ├── conductor/              # 任务编排与审批信箱
│   ├── context/                # 上下文脱敏编排与 Token 截断控制
│   ├── graph/                  # 知识图谱拓扑投影与索引
│   ├── guard/                  # 路径、频控与凭据安全守卫
│   ├── hub/                    # 多模型 SQLite WAL 协同中枢
│   └── proof/                  # 五元组黑盒哈希链引擎
└── tests/                      # 自动化测试与边界评估用例
```

---

## 4. 本地安装与环境部署

### 4.1 环境准备
- **Python**: 3.10 或更高版本
- **SQLite**: 3.35+ (Python 标准库内置，支持 WAL 模式)
- **Git**: 2.30+
- **操作系统**: Windows 10/11, macOS, Linux

### 4.2 本地克隆与安装步骤

打开终端（PowerShell 或 Bash），依次执行：

```bash
# 1. 克隆开源仓库到本地
git clone https://github.com/Arnabest/Rain_JHOC.git
cd Rain_JHOC

# 2. 创建并激活 Python 虚拟环境 (推荐)
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

# 3. 安装核心依赖并以可编辑模式安装
pip install -r requirements.txt
pip install -e .
```

### 4.3 两种本地使用场景说明
- **场景 A：作为主工程直接开发与探索**：  
  直接在智能体 IDE（推荐使用 Antigravity IDE）中打开 `Rain_JHOC` 根目录即可。
- **场景 B：作为外挂微内核装配至外部新项目**：  
  如果需要将 Rain 的治理规则与技能一键外挂赋能给外部其他代码仓库，可在本仓库根目录下运行装配脚本：
  ```powershell
  python scripts/jhoc_provision.py --target-dir <你的目标项目绝对路径>
  ```
  该脚本会自动在目标项目中建立 `.agents/rules/` 软链接与 `AGENTS.md` 索引，实现零拷贝外挂治理。

---

## 5. 模型开箱自适应与激活步骤 (Model Out-of-the-Box Onboarding)

Rain (JHOC) 针对自主智能体设计了**全自动自适应与自检机制**。当您在 IDE 中打开本工程后，无需人类逐步调教，模型即可自主完成环境对齐与治理接入。

### 5.1 第一步：向模型发送开箱激活指令 (Bootstrap Prompt)

在 IDE 或终端（Antigravity IDE、Claude Code、Codex、DeepSeek）开启与大模型的首次对话时，发送以下标准引导语：

> **开箱自适应激活提示词 (可直接复制)**：  
> ```text
> 你正在 Rain (JHOC) 治理环境中工作。请立即阅读根目录下的 AGENTS.md 与 docs/runbooks/JHOC_LLM_ONBOARDING_MANUAL.md，执行一分钟自检，核验你的运行环境、工具能力与开工门禁。
> ```

### 5.2 第二步：模型自主执行的自适应四步闭环

收到激活指令后，模型会在后台自主依次执行以下动作：

```text
[1. 宪法内化] -> [2. 物理探针自检] -> [3. 客户端身份绑定] -> [4. 输出就绪报告]
```

1. **宪法内化 (Constitution Ingestion)**：  
   模型自主检索并阅读 [`AGENTS.md`](AGENTS.md)，建立八大治理准则（包括 Rule 0 反顺从批判性思考、Rule 5 极简单机自持、Rule 7 零 Emoji 纯净字符纪律）；
2. **物理探针自检 (Readiness Probe)**：  
   模型在终端自主运行环境探针脚本，核验 Python 运行时、SQLite WAL 状态机、PathGuard 保护规则与写租约存储连通性：
   ```powershell
   python scripts/jhoc_readiness.py
   ```
3. **客户端身份自绑定 (Runtime Binding)**：  
   模型识别当前所处的客户端环境（Antigravity IDE / Claude Code / Codex / DeepSeek），自动声明对应的模型句柄，并装配 `.agents/skills/` 目录下的 7 大标准化工程技能（`kaigong`, `shougong` 等）；
4. **输出就绪报告并等待任务 (Ready Signal)**：  
   模型在对话中向人类输出环境就绪自检报告，确认当前 Git Commit 基准，随后处于受管待命状态。

> 详细的模型自动化自检机制与各客户端专属适配规范，请参阅：[模型自动化接入注册手册 (docs/runbooks/JHOC_LLM_ONBOARDING_MANUAL.md)](docs/runbooks/JHOC_LLM_ONBOARDING_MANUAL.md)。

---

## 6. 人工工单审批与常用命令速查 (Human Ticket Approval & Cheat-Sheet)

当模型在执行复杂任务过程中触升高危命令（如目录清理、`git reset`、管道批量删除）时，系统门禁会物理拦截并生成审批工单，人类可在终端进行单次授权：

```powershell
# 1. 查看当前待审批的高危操作申请
python scripts/jhoc_approve.py list

# 2. 确认安全后批准执行（单次有效，300 秒自动失效）
python scripts/jhoc_approve.py approve <工单ID> --note "确认允许清理临时缓存"
```

### 常用命令速查表

| 操作需求 | 执行命令 | 说明 |
| :--- | :--- | :--- |
| **模型开工自检** | `python scripts/jhoc_kaigong.py "<任务描述>"` | 模型通常会自动调用，人类也可手动运行 |
| **查看待审工单** | `python scripts/jhoc_approve.py list` | 查看被门禁拦截的高危操作申请 |
| **审批放行工单** | `python scripts/jhoc_approve.py approve <工单ID>` | 人类单次授权高危指令执行（300秒内有效） |
| **模型收工闭环** | `python scripts/jhoc_shougong.py` | 全量自检、单测回归与释放租约 |
| **查看审计大屏** | `python scripts/jhoc_log_stats.py` | 统计各模型的调用频次、拦截次数与耗时 |
| **运行全量单测** | `python -m unittest discover -s tests` | 330 项全量自持单测回归验证 |


---

## 7. 运维审计大屏示例

通过 `jhoc_log_stats.py` 可以查看本地记录的模型调用分布与门禁拦截统计数据：

```powershell
python scripts/jhoc_log_stats.py
```

---

## 8. 自动化测试与验证工具

开发者与研究人员可以使用内置的测试套件对原型的各模块逻辑进行回归测试与验证：

```powershell
# 1. 契约 Schema 静态格式校验
python scripts/validate_schemas.py

# 2. 运行自动化测试套件
python -m unittest discover -s tests -p "test_*.py"
```

---

## 9. 智能体治理规范探索 (AGENTS.md)

在实验中，JHOC 尝试向协同模型提出以下行为规范与设计考量：

- **Rule 0: 元认知蒸馏与批判性思考 (Anti-Sycophancy)**：鼓励客观指出技术方案中的缺陷与权衡，避免盲目迎合。
- **Rule 1: 物理真实与单机可复现原则**：避免不可验证的名词包装，方案应尽量基于最小可复现验证。
- **Rule 2: 零信任外挂防线理念**：探索将安全约束置于模型上下文之外，而非仅依赖 Prompt 引导。
- **Rule 3: 双平面物理隔离设计**：探索数据清洗字面量化与操作层参数化的解耦结构。
- **Rule 4: 静态能力封闭设想**：探讨约束模型在运行时为自己现场创建未授权工具的控制方式。
- **Rule 5: 极简自持与单机确定性**：降低对复杂外部微服务集群的依赖，优先单机自闭环。
- **Rule 6: 结构化链式存证**：探索记录完整的上下文与工具调用链路以供事后审计。
- **Rule 7: 纯净字符纪律 (Zero-Emoji Discipline)**：在工程输出与代码中坚持纯文本标记，避免非标准字符引发的编码故障。

---

## 10. 贡献者与共创致谢 (Contributors & Acknowledgements)

本项目是人类开发者与多个前沿大语言模型智能体进行结对编程、红蓝对抗与架构共创的实验性成果：

- **项目发起人与总体架构师 (Lead Architect & Maintainer)**：
  - **[@Arnabest](https://github.com/Arnabest)** — 课题发起人，主导工程方案落地、多模型异构接入架构设计与真实单机工程实践。
- **AI 协作者与共创智能体团队 (AI Co-Developers & Advisory Models)**：
  - **Antigravity (Google Gemini)**：微内核物理门禁实现、零数据自持重构、多模型 IPC WAL 总线设计与全生命周期文档工程。
  - **OpenAI Codex**：架构规划与风险评审
  - **DeepSeek**：本地意图分类门禁仲裁、核心逻辑实现、对抗协审与跨模型通信解耦验证。
  - **Grok (xAI)**：逻辑缺陷渗透挖掘与深度批判性审查。

感谢各开源社区与前沿模型探索者为本项目带来的架构灵感！

---

## 11. 开源许可证与参与讨论

本项目采用 **Apache License 2.0** 开源许可证。欢迎对自主智能体治理、外部 Harness 防御架构感兴趣的研究人员和工程师参与技术交流与探索。

