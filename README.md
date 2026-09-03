# Rain — Agent Operating Harness (JHOC / Rain Core)

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
git clone https://github.com/your-username/JHOC.git
cd JHOC
python -m pip install -r requirements.txt
python -m pip install -e .
```

---

## 5. Standard Lifecycle Workflow Exploration

JHOC proposes a structured, gated lifecycle for human-agent collaboration:

```text
[Step 1: Kaigong] -> [Step 2: Execution & Gating] -> [Step 3: Shougong Closure]
```

### 5.1 Step 1: Pre-Flight Gate (`Kaigong`)
Before initiating changes, the agent or operator runs a pre-flight probe to verify path boundaries, character purity, and the active Git commit baseline:

```powershell
python scripts/jhoc_kaigong.py "Exploration: Evaluate SQLite lease expiry behavior"
```

### 5.2 Step 2: Runtime Execution & Approvals
During task execution:
- File write operations are checked against `PathGuard` policies and registered under mutex leases;
- Commands matching high-risk signatures produce approval tickets for operator review.

#### Human Approval Flow (`scripts/jhoc_approve.py`)
When high-risk operations are identified:
1. The gate halts unprompted execution and creates a ticket in `runtime/inbox.db`;
2. A human operator reviews and approves the ticket via the CLI:
   ```powershell
   python scripts/jhoc_approve.py list
   python scripts/jhoc_approve.py approve <ticket_id> --note "Operator approved single-use execution"
   ```
3. The ticket is consumed as an ephemeral single-use token (300s TTL) to reduce unauthorized re-use.

### 5.3 Step 3: Post-Flight Closure (`Shougong`)
Upon task completion, the closure script executes the verification pipeline:

```powershell
python scripts/jhoc_shougong.py
```

The script runs:
1. JSON Schema contract format validation;
2. Automated test suite regression;
3. Diff character purity audit for non-ASCII emoji characters;
4. Handoff artifact generation and lease cleanup.

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

## 9. License & Community

Licensed under the **Apache License 2.0**. Contributions, feedback, and architectural discussions from researchers and agent engineers are welcome.
