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

## 4. Quick Start

### 4.1 Prerequisites
- **Python**: 3.10 or higher
- **SQLite**: 3.35+ (standard library built-in)
- **Git**: 2.30+
- **OS**: Windows, macOS, or Linux

### 4.2 Installation
Clone the repository and set up the development environment:

```bash
git clone https://github.com/Arnabest/Rain_JHOC.git
cd Rain_JHOC
python -m pip install -r requirements.txt
python -m pip install -e .
```

---

## 5. Human Operator Guide (面向人类操作者的使用指南)

Rain is designed as an operating harness for autonomous LLMs. In daily development, **humans act as architectural decision-makers and safety gatekeepers, while AI models act as governed execution workers**. Operators do not need to manually configure low-level defenses; the interaction is primarily **conversational and intent-driven**, supplemented by human approval tickets when necessary:

### 5.1 Three-Step Human-Agent Workflow

```text
[Human specifies goal] -> [Model runs Kaigong pre-flight gate]
          |
          v
[Model writes code & tests] -> (If high-risk command triggered) -> [Human approves ticket in CLI] -> [Model proceeds]
          |
          v
[Human marks task complete] -> [Model runs Shougong closure gate] -> [Commit & Handoff]
```

#### Step 1: Launch Task (Pre-Flight)
In your agent IDE (e.g. Antigravity IDE) chat window, state your development goal in natural language:
> **Example Human Prompt**:  
> *"Let's begin today's task: optimize SQLite lease expiry logic. Please run the pre-flight check (`kaigong`) first to inspect the workspace baseline."*

- **What Happens Behind the Scenes**:  
  The agent reads `.agents/rules/` and triggers the `kaigong` skill, locking the Git baseline commit, validating path boundaries, and proactively clarifying scope and edge cases with the human before touching code.

#### Step 2: Governed Execution & Human Approval (Development)
The model autonomously reads code, writes tests, and edits files under harness oversight.
- **Normal Operations**: File edits are protected by `PathGuard` and mutex leases, preventing accidental cross-model overwrites.
- **High-Risk Command Gating**: If the model needs to run potentially destructive commands (e.g., directory purges, piping deletions, `git reset`), the gate halts execution and alerts the human: `[BLOCK] High-risk gate triggered; created approval ticket <ticket_id>`.
- **Human Approval**:
  The human operator verifies the command in a separate CLI terminal and authorizes it:
  ```powershell
  # 1. Inspect pending high-risk approval tickets
  python scripts/jhoc_approve.py list

  # 2. Grant single-use approval (ephemeral 300s TTL)
  python scripts/jhoc_approve.py approve <ticket_id> --note "Approved single-use cache purge"
  ```
  Once approved, reply to the agent: *"Ticket approved, please proceed"*, and the model continues.

#### Step 3: Closure & Handoff (Post-Flight)
When the task is complete, prompt the model to finalize:
> **Example Human Prompt**:  
> *"Development complete. Please run the post-flight closure gate (`shougong`)."*

- **What Happens Behind the Scenes**:  
  The agent runs `jhoc_shougong.py`, executing the full test suite, auditing character purity (zero emoji), releasing active mutex leases, and outputting a clean handoff summary.

---

### 5.2 Multi-Model Collaboration (Human Perspective)

When utilizing multiple model providers (e.g., Gemini, Claude Code, Codex, DeepSeek) for adversarial co-review or pair programming:
1. **Trigger Co-Review**: Run the red-team review pipeline in your terminal:
   ```powershell
   python scripts/jhoc_run_co_review.py --target src/jhoc/hub/store.py
   ```
2. **Concurrent Multi-Agent Workspaces**: You can edit code with Antigravity IDE in one window while running Claude Code CLI or Codex in another. The SQLite WAL mutex engine automatically arbitrates write leases, preventing silent file corruption.

---

### 5.3 Human Operator Cheat-Sheet

| Task | Command | Description |
| :--- | :--- | :--- |
| **Pre-Flight Check** | `python scripts/jhoc_kaigong.py "<Task Description>"` | Run manually or triggered automatically by agent |
| **List Pending Tickets** | `python scripts/jhoc_approve.py list` | View gated high-risk command requests |
| **Approve Ticket** | `python scripts/jhoc_approve.py approve <ticket_id>` | Grant single-use authorization (300s TTL) |
| **Post-Flight Closure** | `python scripts/jhoc_shougong.py` | Full regression, purity audit, and lease cleanup |
| **Inspect Audit Metrics** | `python scripts/jhoc_log_stats.py` | View tool invocation stats and gate interception logs |
| **Run Full Unit Tests** | `python -m unittest discover -s tests` | Execute all 330 standalone test cases |

---

## 6. Operational Dashboard Example

Run `jhoc_log_stats.py` to inspect local activity metrics, tool call attributions, and gate interactions:

```powershell
python scripts/jhoc_log_stats.py
```

---

## 7. Verification & Diagnostics

Developers and researchers can evaluate prototype behavior and boundary conditions using the bundled test suite:

```powershell
# 1. Validate contract Schemas
python scripts/validate_schemas.py

# 2. Run automated test suite
python -m unittest discover -s tests -p "test_*.py"
```

---

## 8. Agent Governance Principles Under Exploration (AGENTS.md)

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

## 9. Contributors & Acknowledgements

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

## 10. License & Community

Licensed under the **Apache License 2.0**. Contributions, feedback, and architectural discussions from researchers and agent engineers are welcome.

