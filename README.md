# JHOC — Jian Harness Operating Core

**Zero-Trust Multi-Model Agent Operating Harness for Autonomous Software Engineering**

```text
[STATUS: EXPERIMENTAL RESEARCH PROTOTYPE / DEMO]  [TESTS: 344/344 100% PASS]  [CHAR-DISCIPLINE: ZERO-EMOJI]
[SUPPORTED RUNTIMES: ANTIGRAVITY IDE (GEMINI) | CLAUDE CODE | OPENAI CODEX | DEEPSEEK]
```

> [!IMPORTANT]
> **PROJECT STATUS: EXPERIMENTAL RESEARCH DEMO (实验性架构演示原型)**  
> JHOC is an **experimental research prototype and architectural demo** exploring the boundaries of zero-trust harness defense, multi-model adversarial co-review, and cryptographic audit ledgers for autonomous coding agents.  
> It is designed and open-sourced as an exploratory reference implementation for developers, researchers, and agent engineers to study physical boundary enforcement over autonomous models. It is **not** an off-the-shelf commercial enterprise product; contracts, IPC protocols, and lifecycle gates are subject to experimental evolution.

---

## 1. Overview & Philosophy

Modern autonomous AI coding agents possess tremendous generative velocity, but in production software engineering, unconstrained autonomy inevitably leads to:
- **Destructive Command Execution**: Accidental or hallucinated filesystem/git branch destruction;
- **Context Rot & Self-Approval Traps**: Agents silently self-approving elevated permissions or altering guardrail configurations;
- **Multi-Agent Write Conflicts**: Concurrent models blindly overwriting each other's source files without mutex coordination;
- **Audit Amnesia**: Inability to cryptographically prove who invoked what tool, when, and under whose authority.

**JHOC (Jian Harness Operating Core)** is a local-first, zero-trust operating harness designed to sit between autonomous AI models and the host operating system. It enforces a fundamental engineering law:

> **Defense logic must reside in the external harness, never inside the model prompt.**
> **Regardless of how models hallucinate, the system behavior strictly converges to safety and determinism.**

---

## 2. Architectural Pillars

JHOC is structured into three strictly decoupled physical planes:

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
| * PreToolUse Gate     |   | * SQLite WAL IPC Hub          |   | * 5-Tuple BlackBox    |
| * PathGuard (Read-Only|   | * Presence State Machine      |   |   Canonical SHA-256   |
|   Core Tree Protection|   | * Message Envelope Bus        |   | * L1/L2/L3 Memory     |
| * Destructive Command |   | * Exclusive Mutex Leases      |   |   Hierarchical Store  |
|   & Obfuscation Matrix|   |   (Bearer Tokenized)          |   | * 3,327 Node Knowledge|
| * Sensitive Cred Vault|   | * Cross-Harness Tool Normalizer|   Graph Projection    |
| * StopGuard Fail-Close|   |   (Gemini, Claude, Codex)     |   | * Local SQLite State  |
+-----------------------+   +-------------------------------+   +-----------------------+
```

### 2.1 The Control Plane (Harness & Guard)
- **PreToolUse Physical Hook Gate (`scripts/jhoc_hook_gate.py`)**: Intercepts all IDE and CLI tool calls before execution.
- **Whole-Tree Source Protection**: Enforces `mutable_by_agent: false`. The entire `src/jhoc/**` tree, governance scripts, and rule definitions are strictly read-only for models.
- **Destructive Command Matrix**: Proactively intercepts git hard resets, recursive file/directory deletions (`rd /s`, `rm -rf`, PowerShell `Remove-Item -Recurse`), inverted pipeline destruction (`Get-ChildItem | Remove-Item`), and Python destructive primitives (`shutil.rmtree`, `os.unlink`).
- **Command Obfuscation Defense**: Blocks PowerShell Base64 `-EncodedCommand` execution and Python `base64.b64decode` dynamic `exec`/`eval` laundering.
- **Reverse Isolation**: Protects central mother core code from tampering when external sub-projects are managed.
- **Sensitive Credential Vault (`src/jhoc/guard/vault.py`)**: Hardware/memory isolation of tokens and API credentials. Models only see opaque handles.

### 2.2 The Coordination Plane (Multi-Model Hub)
- **Zero-Network Local IPC (`src/jhoc/hub/store.py`)**: Uses local SQLite with Write-Ahead Logging (WAL) as the authoritative ground truth for all inter-model messaging and state synchronization.
- **Presence State Machine**: Tracks model liveness (`IDLE`, `BUSY`, `CO_REVIEWING`, `CODING`, `WAITING_INPUT`, `TERMINATED`) with dead-agent expiration and automatic recovery.
- **Bearer-Tokenized Mutex Leases**: When a model edits a file, it acquires an exclusive lease. Leases are authenticated with unforgeable random `lease_id` tokens, preventing other models from spoofing identities or stealing locks.
- **Cross-Harness Tool Normalization**: Normalizes disparate tool interfaces (e.g., `run_command`, `Bash`, `terminal`, `write_to_file`, `edit`, `str_replace_editor`) into unified security checks.

### 2.3 The Cryptographic Audit Plane (Proof & Memory)
- **Five-Tuple BlackBox Ledger (`logs/p19-blackbox.jsonl`)**: Records `(USER, SEEN, THINK, TOOL, BACK)` interactions chained via deterministic SHA-256 hashes (`sort_keys=True`). File-locking contention fails-closed, mathematically preventing ledger forks.
- **L1/L2/L3 Memory Governance**: Organizes project knowledge into three tiers:
  - **L1 Core (Always Active)**: Constitutional rules and non-negotiable boundaries.
  - **L2 Dynamic Shelf (Just-In-Time)**: Specialised task skills mounted on demand.
  - **L3 Cold Archive (Searchable)**: Historical sessions and legacy knowledge.
- **Knowledge Graph Projection**: 3,327 nodes and 4,712 edges mapping dependencies, symbols, and architectural decisions.

---

## 3. Directory Layout

```text
JHOC/
├── .agents/                    # IDE agent customizations, hooks, rules, and skills
│   ├── hooks.json              # Physical lifecycle gate hook declarations
│   ├── rules/                  # Constitutional protocols (Rule 0 to Rule 7)
│   └── skills/                 # Mountable engineering skill packages
├── AGENTS.md                   # Multi-model constitutional framework (ASCII only)
├── CLAUDE.md                   # Native bootstrap instruction for Claude Code
├── docs/                       # Architecture specifications, runbooks, and lesson archives
│   ├── runbooks/               # Operator and model onboarding manuals
│   ├── lessons/                # Permanent institutional memory & failure casebook
│   └── acceptance/             # Formal cutover and acceptance verification artifacts
├── memory/                     # Active task timelines and inter-model handoff packages
├── runtime/                    # Transient local execution databases and locks (excluded in git)
├── logs/                       # Blackbox traces, audit trails, and review logs (excluded in git)
├── schemas/                    # JSON Schemas governing all contracts and payloads
├── scripts/                    # Operational CLI tools, gates, and lifecycle scripts
│   ├── jhoc_kaigong.py         # Pre-flight gate and task registration
│   ├── jhoc_shougong.py        # Post-flight closure, verification, and handoff
│   ├── jhoc_hook_gate.py       # PreToolUse interception engine
│   ├── jhoc_approve.py         # Human-in-the-loop approval ticket manager
│   ├── jhoc_run_co_review.py   # Multi-model adversarial review dispatcher
│   └── jhoc_log_stats.py       # Multi-model operational and token audit dashboard
├── src/jhoc/                   # Core Python packages
│   ├── conductor/              # Task orchestration and approval inbox
│   ├── context/                # Context orchestration and token sanitizers
│   ├── graph/                  # Knowledge graph projection and indexing
│   ├── guard/                  # Path, rate limit, and vault security guards
│   ├── hub/                    # Multi-model SQLite WAL IPC coordinator
│   └── proof/                  # Five-tuple blackbox hash chain engine
└── tests/                      # 344 comprehensive unit and boundary regression tests
```

---

## 4. Quick Start

### 4.1 Prerequisites
- **Python**: 3.10 or higher
- **SQLite**: 3.35+ (standard library built-in)
- **Git**: 2.30+
- **OS**: Windows, macOS, or Linux (cross-platform path and shell support)

### 4.2 Installation
Clone the repository and install in development mode (or run directly with Python):

```bash
git clone https://github.com/your-username/JHOC.git
cd JHOC
python -m pip install -e .
```

---

## 5. Standard Lifecycle Workflow

JHOC strictly prohibits unstructured, unmonitored development. All work follows the standardized lifecycle:

```text
[Step 1: Kaigong] -> [Step 2: Execution & Defense] -> [Step 3: Shougong Closure]
```

### 5.1 Step 1: Pre-Flight Gate (`Kaigong`)
Before modifying any code, the agent or developer must run the pre-flight gate to lock working directory boundaries, verify character purity, and bind the current Git commit baseline:

```powershell
python scripts/jhoc_kaigong.py "Feature: Implement SQLite lease expiry"
```

Output:
```text
=== [JHOC KAIGONG PRE-FLIGHT GATE] ===
[PASS] Workspace verified: G:\JHOC
[PASS] Git tracking active in JHOC
[PASS] Zero-Emoji Discipline verified across active governance files
[INFO] Git Baseline Commit: 225d3f7791
[INFO] Task registered: 20260904T030000Z-feature_implement_sqlite_lease
[INFO] Title: Feature: Implement SQLite lease expiry
gate: ALLOW
```

### 5.2 Step 2: Runtime Execution & Interception
During task execution:
- Any file mutation automatically queries `PathGuard` and multi-model file leases.
- Any attempt to run destructive commands, tamper with approval ledgers, or access vault credentials without authorization is halted with a ticket.

#### Handling Human Approvals (`scripts/jhoc_approve.py`)
When a high-risk operation (e.g. `git reset --hard`) is legitimately required:
1. The gate denies direct execution and creates an approval ticket in `runtime/inbox.db`.
2. A human operator reviews and approves the ticket using the operator secret:
   ```powershell
   python scripts/jhoc_approve.py list
   python scripts/jhoc_approve.py approve <ticket_id> --note "Operator verified clean tree"
   ```
3. The gate consumes the ticket as a single-use token (300s TTL) and permits execution exactly once. Replay attempts are rejected.

### 5.3 Step 3: Post-Flight Closure (`Shougong`)
When work is complete, execute the closure pipeline:

```powershell
python scripts/jhoc_shougong.py
```

`Shougong` automatically performs:
1. Static contract Schema validation (`scripts/validate_schemas.py`).
2. Full repository unit test execution (all 344 tests must pass).
3. Physical acceptance probe verification (`scripts/validate_acceptance_artifacts.py`).
4. Git diff character purity audit (Rule 7 Zero-Emoji scan).
5. Global `write_freeze.lock` state freeze.
6. Machine-readable Inter-Model Handoff package generation (`memory/handoff-latest.json`).
7. Multi-Model Hub lease cleanup and presence reset to `IDLE`.

---

## 6. Multi-Model Operational Audit Dashboard

Run `jhoc_log_stats.py` at any time to inspect operational metrics, tool call attributions, and gate denials across all participating models:

```powershell
python scripts/jhoc_log_stats.py
```

Example report:
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

## 7. Verification & Testing

JHOC is backed by 344 comprehensive automated tests covering zero-trust security boundaries, concurrency races, protocol contracts, and red-team penetration blind spots:

```powershell
# 1. Validate contract Schemas
python scripts/validate_schemas.py

# 2. Run all 344 unit and integration tests
python -m unittest discover -s tests -p "test_*.py"

# 3. Verify acceptance artifacts and runtime probes
python scripts/validate_acceptance_artifacts.py
```

Result:
```text
Ran 344 tests in 24.9s
OK
{"validated": true, "checks": {"runtime_probes": true, "local_independence": true, ...}}
```

---

## 8. Constitutional Rules for Collaborating Agents

All AI models operating within a JHOC-governed workspace are bound by [`AGENTS.md`](AGENTS.md):

- **Rule 0: Metacognitive Distillation & Anti-Sycophancy**: Never flatter or uncritically agree with user premises or external papers. Point out critical flaws before benefits. Perform `[Facts -> Principles -> Deductions -> Critical Questions]` before major changes.
- **Rule 1: Physical Reality & Conservation of Measurement**: No academic jargon inflation. Every architectural proposal must have a single-machine minimal reproducible test.
- **Rule 2: Zero-Trust Model Boundary**: Security resides in external harness gates, never in prompt promises.
- **Rule 3: Dual-Plane Physical Isolation**: Data plane (sanitized literal text) is separated from operation plane (strongly-typed parameter structures).
- **Rule 4: Static Capability Closure**: Models cannot self-modify security rules or grant themselves new tools.
- **Rule 5: Local-First Determinism**: No reliance on remote heartbeats. Pure Python, SQLite WAL, deterministic execution.
- **Rule 6: Five-Tuple Hash Chaining**: Every action is immutably signed into the BlackBox ledger.
- **Rule 7: Zero-Emoji Discipline**: Absolute zero emojis across all code, comments, documentation, and agent outputs. Use clean ASCII markers (`[PASS]`, `[WARN]`, `[FAIL]`, `[INFO]`, `->`).

---

## 9. License & Contributing

Licensed under the Apache License 2.0. Contributions must adhere to the 344-test green baseline and pass all post-flight `jhoc_shougong.py` checks.
