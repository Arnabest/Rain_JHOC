# Rain — Agent Operating Harness (Rain / JHOC Harness Core)

**Zero-Trust Context Orchestration Framework for LLM Autonomous Workflows**

[English](README.md) | [简体中文](README_CN.md)

```text
[STATUS: EXPERIMENTAL RESEARCH PROTOTYPE / DEMO]  [CHAR-DISCIPLINE: ZERO-EMOJI]
[EXPLORATION RUNTIMES: ANTIGRAVITY IDE (GEMINI) | CLAUDE CODE | OPENAI CODEX | DEEPSEEK]
```

> [!IMPORTANT]
> **PROJECT STATUS: EXPERIMENTAL RESEARCH DEMO (实验性架构演示原型)**  
> Rain (JHOC) is an **experimental research prototype and architectural demo** exploring the design space of zero-trust harness isolation, multi-agent adversarial co-review, and cryptographic audit ledgers for autonomous coding agents.  
> It is provided as an open exploration sandbox for developers, AI engineers, and security researchers to study how external harnesses can enforce boundaries on generative models. It is **not** an off-the-shelf commercial enterprise product; contracts, IPC protocols, and lifecycle gates are subject to experimental evolution and do not make absolute security guarantees.
> 
> **Runtime Environment & Interaction Modality**:  
> - **Recommended Environment**: The primary development and execution environment is **recommended to be an agent-centric IDE (the author actively develops within Antigravity IDE)** or agent CLI terminals;  
> - **No Explicit Frontend Console**: As an operating harness and context orchestration core, **this project does not provide a dedicated visual Web / GUI dashboard**;  
> - **Interaction Paradigm**: It is **designed to be driven primarily via conversational dialogue with the AI models**, which invoke underlying scripts and governance skills under harness supervision.

---

## 1. Overview & Exploration Background

Modern autonomous AI coding agents demonstrate rapid generative capabilities, but in complex software engineering workflows, unconstrained execution often faces notable engineering challenges:
- **Destructive Command Risks**: Agents may attempt high-risk or destructive filesystem/git operations due to hallucinations or misinterpretation;
- **Context Rot & Self-Approval Traps**: Agents might attempt to self-approve elevated permissions or tamper with security configurations within their own context;
- **Multi-Model Write Contention**: Concurrent agents from different providers operating in the same workspace can encounter uncoordinated file overwrites;
- **Audit Gaps**: Without tamper-evident local logging, reconstructing multi-model tool invocations and causal decision chains can be difficult.

**Rain (JHOC / Rain Core)** explores a local-first, zero-trust architectural approach situated between model clients and the host operating system:

> **Core Research Hypothesis**: Security and boundary defense should physically reside in an external harness rather than relying on prompt-level self-restraint.  
> **Design Objective**: To investigate how external gates and deterministic state machines can guide autonomous model behaviors toward bounded, observable, and reproducible boundaries.

### 1.1 Empirical Observations from Local Practice

Through ongoing iteration and red-team testing in real single-machine multi-model setups, the prototype has demonstrated several practical observations and relative advantages:

1. **Host-Level Interception Offers Better Practical Controllability than Prompt Restraint**:
   - Relying on System Prompts hoping models will "refrain from high-risk operations" frequently proves vulnerable to prompt drift or injection during extended reasoning chains;
   - **Empirical Observation**: Moving checks to a host-level PreToolUse hook prior to actual tool execution provides a more consistent, controllable boundary without having to depend solely on prompt self-discipline.

2. **Local-First Design Reduces External Service Dependencies**:
   - Compared with heavier architectures that rely on cloud message brokers, remote heartbeat relays, or distributed coordination clusters, local orchestration is considerably leaner;
   - **Empirical Observation**: Building the coordination hub primarily on Python standard libraries and local SQLite WAL allows the core state machine to function reliably even in offline or air-gapped scenarios, mitigating exposure to network latency and cloud outages.

3. **Exploring Lightweight Mechanisms to Mitigate Multi-Model Write Contention**:
   - Disparate client tools (Gemini, Claude Code, Codex) follow different conventions, and uncoordinated concurrent edits often lead to accidental file overwrites;
   - **Empirical Observation**: Normalizing tool abstractions at the gate and introducing time-bounded exclusive write leases explores an accessible way to minimize concurrent race conditions across diverse models.

4. **Providing Structured Traceability for Forensic Review**:
   - In multi-agent scenarios without structured auditing, pinpointing which model performed what action at what point in time can be challenging;
   - **Empirical Observation**: Recording `(USER, SEEN, THINK, TOOL, BACK)` interactions into an append-only SHA-256 chained log offers a coherent, tamper-evident sequence to assist in debugging and operational review.

5. **Guiding Early Convergence to Temper Codebase Bloat**:
   - Unconstrained autonomous agents often exhibit a tendency to generate redundant scaffolding, speculative abstractions, and unnecessary complexity;
   - **Empirical Observation**: Coupling pre-flight gates with anti-sycophantic critical questions and dimensional impact analysis helps prompt models to clarify boundaries early, reducing speculative code proliferation.

---

## 2. Three Architectural Planes: Design Objectives

JHOC structures its experimental exploration into three decoupled planes:

```text
+---------------------------------------------------------------------------------------+
|                                    JHOC APPLICATION                                   |
+---------------------------------------------------------------------------------------+
        |                                   |                                   |
        v                                   v                                   v
+-----------------------+   +-------------------------------+   +-----------------------+
|     CONTROL PLANE     |   |      COORDINATION PLANE       |   |     AUDIT PLANE       |
|    (Harness & Guard)  |   |       (Multi-Model Hub)       |   |   (Proof & Memory)    |
+-----------------------+   +-------------------------------+   +-----------------------+
| * Goal: PreToolUse    |   | * Goal: Local SQLite WAL      |   | * Goal: 5-Tuple       |
|   intercept gate      |   |   lightweight IPC bus         |   |   BlackBox hash chain |
| * Goal: Source tree   |   | * Goal: Presence state machine|   | * Goal: Hierarchical  |
|   read-only mutation  |   | * Goal: Bearer-token mutex    |   |   memory (L1/L2/L3)   |
|   prevention concept  |   |   leases to mitigate write    |   | * Goal: Knowledge     |
| * Goal: Destructive   |   |   contention                  |   |   graph context index |
|   command & obfuscated|   | * Goal: Cross-client tool     |   | * Goal: Single-node   |
|   pattern interception|   |   normalization abstraction   |   |   determinism         |
+-----------------------+   +-------------------------------+   +-----------------------+
```

### 2.1 The Control Plane Design Intents (Harness & Guard)
- **PreToolUse Interception Exploration (`scripts/jhoc_hook_gate.py`)**: Explores intercepting IDE and CLI tool calls prior to OS-level execution;
- **Whole-Tree Read-Only Design (`mutable_by_agent: false`)**: Explores treating core source files and governance rules as immutable by agents to study self-mutation resistance;
- **High-Risk Operation Pattern Matching**: Investigates pattern-matching rules against recursive deletions, git hard resets, inverted pipeline deletions, and dynamic Python code execution混淆;
- **Reverse Isolation Sandbox**: Investigates boundary guards preventing external agents in sub-projects from inadvertently modifying core harness logic;
- **Credential Masking Model (`src/jhoc/guard/vault.py`)**: Explores in-memory secret masking and late egress dereferencing to reduce the likelihood of raw credentials entering model prompts.

### 2.2 The Coordination Plane Design Intents (Multi-Model Hub)
> For detailed client configuration, file mutex leases, and IPC setup, see: [Multi-Model Collaboration Guide](docs/runbooks/MULTI_MODEL_COLLABORATION_GUIDE.md)

- **Zero-Network Local IPC (`src/jhoc/hub/store.py`)**: Explores using local SQLite with Write-Ahead Logging (WAL) as an authoritative state store without remote cloud dependencies;
- **Presence State Machine**: Explores unified liveness and state tracking for multi-agent workflows;
- **Exclusive Mutex Leases (Bearer Token)**: Investigates using ephemeral random lease tokens to mitigate concurrent file overwrite collisions;
- **Cross-Harness Tool Normalization**: Explores abstracting heterogeneous agent interfaces (Claude Code, Gemini, Codex) into a unified security evaluation model.

### 2.3 The Cryptographic Audit Plane Design Intents (Proof & Memory)
- **Five-Tuple BlackBox Ledger (`logs/p19-blackbox.jsonl`)**: Explores capturing `(USER, SEEN, THINK, TOOL, BACK)` interactions chained via deterministic SHA-256 hashes for post-hoc forensic review;
- **Hierarchical Memory Architecture (L1/L2/L3)**: Explores organizing agent memory across active constitutional invariants, task-specific skill shelves, and archival stores;
- **Knowledge Graph Projection**: Explores topological relationship extraction to evaluate decoupled context retrieval.

---

## 3. Directory Layout

```text
JHOC/
├── .agents/                    # Agent runtime customizations, hooks, rules, and skills
│   ├── hooks.json              # Physical lifecycle gate hook declarations
│   ├── rules/                  # 11 constitutional protocols (Rule 0 to Rule 7)
│   └── skills/                 # 7 audited engineering skill packages
├── AGENTS.md                   # Multi-model constitutional framework (ASCII only)
├── CLAUDE.md                   # Native bootstrap instruction for Claude Code
├── docs/                       # Architecture specifications, runbooks, and lesson archives
│   ├── runbooks/               # Operator and model onboarding manuals
│   ├── lessons/                # Permanent institutional memory casebook
│   └── architecture/           # System architecture design documentation
├── memory/                     # Transient task state placeholder (clean in zero-data repo)
├── runtime/                    # Transient local execution databases and locks (excluded in git)
├── logs/                       # Audit trails and traces (excluded in git)
├── schemas/                    # JSON Schemas governing contracts and payloads
├── scripts/                    # Operational CLI tools, gates, and lifecycle scripts
│   ├── jhoc_kaigong.py         # Pre-flight gate and task registration
│   ├── jhoc_shougong.py        # Post-flight closure and verification
│   ├── jhoc_hook_gate.py       # PreToolUse interception engine
│   ├── jhoc_approve.py         # Human approval ticket manager
│   ├── jhoc_run_co_review.py   # Multi-model adversarial review dispatcher
│   └── jhoc_log_stats.py       # Operational audit dashboard
├── src/jhoc/                   # Core Python packages
│   ├── conductor/              # Task orchestration and approval inbox
│   ├── context/                # Context orchestration and token sanitizers
│   ├── graph/                  # Knowledge graph projection and indexing
│   ├── guard/                  # Path, rate limit, and vault security guards
│   ├── hub/                    # Multi-model SQLite WAL IPC coordinator
│   └── proof/                  # Five-tuple blackbox hash chain engine
└── tests/                      # Automated test suite and boundary evaluation cases
```

---

## 4. Local Installation & Setup

### 4.1 Prerequisites
- **Python**: 3.10 or higher
- **SQLite**: 3.35+ (standard library built-in with WAL support)
- **Git**: 2.30+
- **OS**: Windows 10/11, macOS, Linux

### 4.2 Clone & Installation Steps

Run in your terminal (PowerShell or Bash):

```bash
# 1. Clone repository locally
git clone https://github.com/Arnabest/Rain_JHOC.git
cd Rain_JHOC

# 2. Create and activate Python virtual environment (recommended)
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

# 3. Install dependencies in editable mode
pip install -r requirements.txt
pip install -e .
```

### 4.3 Two Local Usage Scenarios
- **Scenario A: Direct exploration and development inside Rain**:  
  Open the `Rain_JHOC` root directory directly in your agent IDE (Antigravity IDE recommended).
- **Scenario B: Provisioning Rain as an external harness onto another project**:  
  To mount Rain's governance rules and shelf skills onto an existing project codebase, run the automated provisioner:
  ```powershell
  python scripts/jhoc_provision.py --target-dir <absolute-path-to-target-project>
  ```
  This provisions `.agents/rules/` symlinks and `AGENTS.md` index into the target project without duplicating core files.

---

## 5. Model Out-of-the-Box Onboarding (模型开箱自适应与激活步骤)

Rain (JHOC) is architected with an **autonomous self-adaptation and alignment loop**. Once you open the workspace in your IDE, the AI model self-onboards without requiring step-by-step human tutoring.

### 5.1 Step 1: Send the Bootstrap Prompt to the Agent

Upon opening your first conversation with the LLM in your IDE or CLI (Antigravity IDE, Claude Code, Codex, DeepSeek), send the following standard activation directive:

> **Bootstrap Prompt (Copy & Paste)**:  
> ```text
> You are working within the Rain (JHOC) governance harness. Please immediately read AGENTS.md and docs/runbooks/JHOC_LLM_ONBOARDING_MANUAL.md, run the fast self-test probe, and verify your runtime environment, tool capabilities, and pre-flight gates.
> ```

### 5.2 Step 2: Autonomous Model Onboarding Loop

Upon receiving the prompt, the agent independently executes a four-phase onboarding sequence behind the scenes:

```text
[1. Constitution Ingestion] -> [2. Readiness Probe] -> [3. Runtime Binding] -> [4. Ready Signal]
```

1. **Constitution Ingestion (宪法内化)**:  
   The model reads [`AGENTS.md`](AGENTS.md) and internalizes the eight core invariants (including Rule 0 Anti-Sycophancy, Rule 5 Local-First Determinism, and Rule 7 Zero-Emoji Discipline);
2. **Readiness Probe (物理探针自检)**:  
   The model autonomously runs the environment probe to verify Python runtime, SQLite WAL state machine, PathGuard confinement, and lease storage connectivity:
   ```powershell
   python scripts/jhoc_readiness.py
   ```
3. **Runtime Binding (客户端身份自绑定)**:  
   The model detects its client host (Antigravity IDE / Claude Code / Codex / DeepSeek), registers its model handle, and mounts the 7 standardized shelf skills under `.agents/skills/` (`kaigong`, `shougong`, etc.);
4. **Ready Signal (输出就绪报告)**:  
   The model returns an onboarding readiness summary in chat, confirms the active Git commit baseline, and stands by in a governed operational state.

> For the comprehensive machine-readable onboarding protocol, refer to: [LLM Automated Onboarding Manual (docs/runbooks/JHOC_LLM_ONBOARDING_MANUAL.md)](docs/runbooks/JHOC_LLM_ONBOARDING_MANUAL.md).

---

## 6. Human Approval & Command Cheat-Sheet (人工工单审批与速查表)

When an agent triggers high-risk operations (e.g. directory purges, `git reset`, piped deletions), the gate physically intercepts execution and logs an approval ticket. Human operators can review and authorize it in a separate CLI terminal:

```powershell
# 1. Inspect pending high-risk approval tickets
python scripts/jhoc_approve.py list

# 2. Authorize single-use execution (ephemeral 300s TTL)
python scripts/jhoc_approve.py approve <ticket_id> --note "Approved single-use cache purge"
```

### Operator Command Cheat-Sheet

| Task | Command | Description |
| :--- | :--- | :--- |
| **Model Pre-Flight** | `python scripts/jhoc_kaigong.py "<Task Description>"` | Model invokes automatically; can also run manually |
| **List Pending Tickets** | `python scripts/jhoc_approve.py list` | View gated high-risk command requests |
| **Approve Ticket** | `python scripts/jhoc_approve.py approve <ticket_id>` | Grant single-use authorization (300s TTL) |
| **Model Closure** | `python scripts/jhoc_shougong.py` | Full regression, purity audit, and lease cleanup |
| **Inspect Audit Metrics** | `python scripts/jhoc_log_stats.py` | View tool invocation stats and gate interception logs |
| **Run Full Unit Tests** | `python -m unittest discover -s tests` | Execute all 330 standalone test cases |

---

## 7. Operational Dashboard Example

Run `jhoc_log_stats.py` to inspect local activity metrics, tool call attributions, and gate interactions:

```powershell
python scripts/jhoc_log_stats.py
```

---

## 8. Verification & Diagnostics

Developers and researchers can evaluate prototype behavior and boundary conditions using the bundled test suite:

```powershell
# 1. Validate contract Schemas
python scripts/validate_schemas.py

# 2. Run automated test suite
python -m unittest discover -s tests -p "test_*.py"
```

---

## 9. Agent Governance Principles Under Exploration (AGENTS.md)

JHOC studies the application of the following behavioral invariants across collaborating agents:

- **Rule 0: Metacognitive Distillation & Anti-Sycophancy**: Encouraging agents to highlight flaws and technical trade-offs before agreement;
- **Rule 1: Physical Reality & Reproducibility**: Favoring minimal reproducible tests over unverified architectural assertions;
- **Rule 2: Zero-Trust Model Boundary**: Exploring harness-level physical constraints over prompt-based instructions;
- **Rule 3: Dual-Plane Physical Isolation**: Exploring separation of sanitized data planes from strongly-typed operational calls;
- **Rule 4: Static Capability Closure**: Exploring constraints on agents dynamically generating unreviewed runtime tools;
- **Rule 5: Local-First Determinism**: Prioritizing single-machine determinism over distributed complexity;
- **Rule 6: Chained Evidence Logging**: Exploring structured audit trails for tool invocation review;
- **Rule 7: Zero-Emoji Discipline**: Enforcing pure ASCII markers to prevent encoding anomalies in diverse CLI environments.

---

## 10. Contributors & Acknowledgements

Rain (JHOC) is the collaborative outcome of human-AI pair programming, architectural co-design, and red-team review across multiple frontier model families:

- **Lead Architect & Maintainer**:
  - **[@Arnabest](https://github.com/Arnabest)** — Project initiator, leading architectural design, heterogeneous model integration, and local engineering practice.
- **AI Co-Developers & Advisory Models**:
  - **Antigravity (Google Gemini)**: Microkernel physical gating implementation, zero-data self-sufficiency refactoring, IPC WAL bus design, and lifecycle documentation engineering.
  - **OpenAI Codex**: Architectural planning and risk review.
  - **DeepSeek**: Local intent classification gate, core logic implementation, adversarial co-review, and cross-model communication decoupling.
  - **Grok (xAI)**: Logical vulnerability penetration review and critical adversarial inspection.

Special thanks to the broader open-source community and generative AI researchers for architectural inspiration!

---

## 11. License & Community

Licensed under the **Apache License 2.0**. Contributions, feedback, and architectural discussions from researchers and agent engineers are welcome.


