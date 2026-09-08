"""JHOC PreToolUse Hook Gate - Physical interceptor for IDE tool execution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b00-\u2bff]|[\ufe00-\ufe0f]|[\u200b-\u200d]|[\u2060]|[\ufeff]")
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


_LITTER_RE = re.compile(
    r"^(test_|tmp_|temp_|dump_|debug_|scratch_|out_).*\.(py|json|txt|log|sh|bat)$|^(test|tmp|temp|dump|debug|scratch|out)\.(py|json|txt|log|sh|bat)$",
    re.IGNORECASE,
)

import sqlite3
import time

_TOOL_ALIASES = {
    "bash": "run_command",
    "terminal": "run_command",
    "shell": "run_command",
    "execute_command": "run_command",
    "create_file": "write_to_file",
    "write": "write_to_file",
    "edit": "replace_file_content",
    "str_replace_editor": "replace_file_content",
}


def _resolve_caller_identity(payload: dict) -> tuple[str, str | None]:
    """Resolves the calling model identity and active task_id."""
    import os
    actor = "antigravity-ide"
    task_id = None

    # 1. Direct explicit environment variable
    if env_model := os.environ.get("JHOC_MODEL_ID"):
        actor = env_model.strip()
    # 2. Explicit caller / model_id in payload
    elif payload.get("caller"):
        actor = str(payload["caller"]).strip()
    elif payload.get("model_id"):
        actor = str(payload["model_id"]).strip()

    # 3. Explicit task_id in payload
    if payload.get("task_id"):
        task_id = str(payload["task_id"]).strip()

    # 4. Resolve from Hub or local state
    try:
        hub_db = WORKSPACE_ROOT / "logs" / "p19-hub.sqlite"
        if hub_db.is_file():
            sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
            from jhoc.hub import JHOCMultiModelHub
            hub = JHOCMultiModelHub(hub_db)
            if not task_id:
                slot = hub.get_active_task_slot(actor)
                if slot:
                    task_id = slot.task_id
    except Exception:
        pass

    if not task_id:
        try:
            state_file = WORKSPACE_ROOT / "memory" / "v3_task_state.json"
            if state_file.is_file():
                st_data = json.loads(state_file.read_text(encoding="utf-8"))
                task_id = st_data.get("task_id")
        except Exception:
            pass

    return actor, task_id


def _record_blackbox_trace(
    tool_name: str,
    args: dict,
    decision: str,
    reason: str,
    actor: str = "antigravity-ide",
    task_id: str | None = None,
) -> None:
    """Appends an immutable five-element proof trace into p19-blackbox.jsonl."""
    try:
        import hashlib
        import os
        import time
        from datetime import datetime, timezone

        blackbox_dir = WORKSPACE_ROOT / "logs"
        blackbox_dir.mkdir(parents=True, exist_ok=True)
        blackbox_file = blackbox_dir / "p19-blackbox.jsonl"
        runtime_dir = WORKSPACE_ROOT / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        lock_path = runtime_dir / "blackbox_write.lock"

        # Stale lock recovery (e.g. process crashed while holding lock)
        if lock_path.is_file():
            try:
                if time.time() - lock_path.stat().st_mtime > 5.0:
                    lock_path.unlink()
            except Exception:
                pass

        # Inter-process atomic lock
        acquired = False
        for _ in range(500):
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                acquired = True
                break
            except FileExistsError:
                time.sleep(0.01)
            except Exception:
                break

        if not acquired:
            # Under lock contention, append to emergency spool to prevent hash chain interruption
            try:
                spool_file = blackbox_dir / "p19-blackbox-spool.jsonl"
                spool_payload = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "actor": actor,
                    "tool": tool_name,
                    "decision": decision,
                    "reason": reason[:200],
                }
                with spool_file.open("a", encoding="utf-8") as sf:
                    sf.write(json.dumps(spool_payload, sort_keys=True, ensure_ascii=True) + "\n")
            except Exception:
                pass
            return

        try:
            prev_hash = "0" * 64
            seq = 1
            if blackbox_file.is_file() and blackbox_file.stat().st_size > 0:
                try:
                    f_size = blackbox_file.stat().st_size
                    with blackbox_file.open("rb") as bf:
                        seek_pos = max(0, f_size - 8192)
                        bf.seek(seek_pos)
                        tail_lines = bf.read().decode("utf-8", errors="replace").splitlines()
                        valid_lines = [l.strip() for l in tail_lines if l.strip()]
                        if valid_lines:
                            last_obj = json.loads(valid_lines[-1])
                            prev_hash = last_obj.get("entry_hash", prev_hash)
                            seq = last_obj.get("sequence", 0) + 1
                except Exception:
                    pass
            now_str = datetime.now(timezone.utc).isoformat()
            content = {
                "tool": tool_name,
                "args_keys": list(args.keys()),
                "decision": decision,
                "reason": reason[:200],
                "actor": actor,
            }
            if task_id:
                content["task_id"] = task_id

            hash_payload = {
                "sequence": seq,
                "timestamp": now_str,
                "step_type": "TOOL",
                "actor": actor,
                "content": content,
                "previous_hash": prev_hash,
            }
            raw = json.dumps(hash_payload, sort_keys=True, default=str).encode("utf-8")
            entry_hash = hashlib.sha256(raw).hexdigest()
            hash_payload["entry_hash"] = entry_hash
            if task_id:
                hash_payload["task_id"] = task_id
            with blackbox_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(hash_payload, sort_keys=True, ensure_ascii=True) + "\n")
        finally:
            try:
                lock_path.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _check_or_create_ticket(operation: str, target: str, reason: str, payload: dict, actor: str = "ide_agent") -> dict:
    """Checks if operation was approved. If so, consumes ticket and returns allow; else creates ticket and returns deny."""
    try:
        sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
        from jhoc.conductor.inbox import SQLiteApprovalInbox
        inbox_db = WORKSPACE_ROOT / "runtime" / "inbox.db"
        inbox = SQLiteApprovalInbox(inbox_db)

        # Check if already approved (TTL 300s)
        approved = inbox.find_active_approval(operation, target, max_age_seconds=300)
        if approved:
            inbox.consume_approval(approved.ticket_id, consumer=actor)
            inbox.close()
            return {
                "decision": "allow",
                "reason": (
                    f"Approval Override: Permitted under ticket {approved.ticket_id} "
                    f"(approved by {approved.approver}, consumed for one-shot execution)."
                ),
            }

        # Check if already pending or create new ticket
        pending = inbox.find_pending_ticket(operation, target)
        if pending:
            t_id = pending.ticket_id
        else:
            ticket = inbox.create_ticket(
                operation=operation,
                requester="ide_agent",
                reason=reason,
                payload={"target": target, "command": target, "details": payload},
            )
            t_id = ticket.ticket_id
        inbox.close()

        return {
            "decision": "deny",
            "reason": (
                f"{reason} [Approval Required: Ticket {t_id} created. Run 'python scripts/jhoc_approve.py approve {t_id}' to permit]."
            ),
        }
    except Exception:
        return {"decision": "deny", "reason": reason}


def _evaluate_inner(payload: dict, actor: str = "antigravity-ide", task_id: str | None = None) -> dict:
    is_external_workspace = False
    ws_paths = payload.get("workspacePaths", [])
    if ws_paths:
        for wp in ws_paths:
            try:
                Path(wp).resolve().relative_to(WORKSPACE_ROOT)
            except ValueError:
                is_external_workspace = True
                break

    # Cross-harness tool alias and argument normalization
    tool_call = payload.get("toolCall", {})
    raw_tool_name = (
        tool_call.get("name")
        or payload.get("toolName")
        or payload.get("tool")
        or "unknown"
    ).lower()
    tool_name = _TOOL_ALIASES.get(raw_tool_name, raw_tool_name)
    args = tool_call.get("args") or payload.get("args") or {}

    # Check 0.05: Operator Secret Protection (Hard deny on operator assets)
    if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
        target_candidate = str(args.get("TargetFile", "") or args.get("path", "") or args.get("file", ""))
        if target_candidate:
            t_cand_name = Path(target_candidate).name.lower()
            if t_cand_name.startswith(".operator_") or t_cand_name.startswith("operator_"):
                return {
                    "decision": "deny",
                    "reason": "Operator Security Violation: Agents are strictly prohibited from creating or modifying operator secrets.",
                }

    # Check 0: Concurrency write freeze during shougong post-flight verification
    write_freeze_file = WORKSPACE_ROOT / "runtime" / "write_freeze.lock"
    if write_freeze_file.is_file():
        if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
            return {
                "decision": "deny",
                "reason": "Concurrency Conflict: System write freeze is active during shougong verification. Code mutation is blocked.",
            }

    # Check 0.5: Multi-Model File Mutex Lease Check (Evaluated before tenant/quota circuit breakers)
    if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
        target_file = args.get("TargetFile", "") or args.get("path", "") or args.get("file", "")
        if target_file:
            hub_db = WORKSPACE_ROOT / "logs" / "p19-hub.sqlite"
            if hub_db.is_file():
                try:
                    conn = sqlite3.connect(str(hub_db), timeout=1.0)
                    from datetime import datetime, timezone
                    now_iso = datetime.now(timezone.utc).isoformat()
                    now_ts = time.time()
                    try:
                        posix_path = Path(target_file).resolve().as_posix()
                    except Exception:
                        posix_path = str(target_file).replace("\\", "/")

                    row = None
                    try:
                        row = conn.execute(
                            "SELECT locked_by_model, expires_at FROM hub_file_leases WHERE (file_path = ? OR LOWER(file_path) = LOWER(?)) AND status = 'ACTIVE' AND expires_at > ?",
                            (posix_path, posix_path, now_iso),
                        ).fetchone()
                    except Exception:
                        pass
                    if not row:
                        try:
                            row = conn.execute(
                                "SELECT owner_model, expires_at FROM jhoc_model_file_leases WHERE (file_path = ? OR LOWER(file_path) = LOWER(?)) AND expires_at > ?",
                                (posix_path, posix_path, now_ts),
                            ).fetchone()
                        except Exception:
                            pass
                    conn.close()
                    if row:
                        lease_owner = row[0]
                        if lease_owner != actor:
                            return {
                                "decision": "deny",
                                "reason": (
                                    f"File Mutex Conflict: File '{target_file}' is exclusively leased by model '{lease_owner}'. "
                                    f"Current caller '{actor}' cannot modify it until lease expires."
                                ),
                            }
                except Exception:
                    pass

    # Priority 1: High-risk command inspection (Privilege Escalation, Ledger Tampering, Destructive Commands)
    if tool_name == "run_command":
        cmd_line = args.get("CommandLine", "") or args.get("command", "")
        if cmd_line:
            # Check 0.8.1: Ledger Tampering & Governance Variable Spoofing (C4)
            tamper_match = re.search(
                r'(?:setx\s+|export\s+|set\s+|\$env:)\s*["\']?(JHOC_[A-Z0-9_]+)',
                cmd_line,
                re.IGNORECASE,
            )
            if tamper_match:
                var_name = tamper_match.group(1).upper()
                return {
                    "decision": "deny",
                    "reason": f"Ledger Tampering Violation: Attempted modification of governance environment variable '{var_name}'.",
                }

            if re.search(r"inbox\.db", cmd_line, re.IGNORECASE) or re.search(r"\bjhoc_approval_inbox\b", cmd_line, re.IGNORECASE):
                return {
                    "decision": "deny",
                    "reason": "Ledger Tampering Violation: Direct tampering with approval ledger database or table is forbidden.",
                }

            # Check 0.8: Privilege Escalation & Self-Approval Prevention
            if re.search(r"\bjhoc_approve\.py\b", cmd_line, re.IGNORECASE) or re.search(r"\binbox\.approve\b", cmd_line, re.IGNORECASE):
                return {
                    "decision": "deny",
                    "reason": (
                        "Privilege Escalation Violation: Autonomous self-approval is forbidden. "
                        "Only operator shell / verified supervisor can execute jhoc_approve.py."
                    ),
                }

            # Check 1: Emoji in command payload
            if _EMOJI_RE.search(cmd_line):
                return {
                    "decision": "deny",
                    "reason": "Rule 7 Violation: Zero-Emoji Discipline breached. Emoji detected in CommandLine payload.",
                }

            # Check 2: High-risk destructive system commands
            destructive_patterns = [
                (r"\bgit\s+reset\s+--hard\b", "git reset --hard is destructive and bypasses commit rollback"),
                (r"\bgit\s+clean\s+-[a-zA-Z]*f", "git clean with force flag destroys untracked files"),
                (r"\bgit\s+push\b.*(--force|-f\b)", "force-pushing git branches destroys remote history"),
                (r"\b(?:rd|rmdir)\s+.*(?:/[sqSQ]|-[sqSQ])", "recursive directory removal via rd/rmdir"),
                (r"\b(?:Remove-Item|ri|rmdir)\b.*-(?:Recurse|r\b)", "recursive deletion via PowerShell Remove-Item destroys filesystem contents"),
                (r"\b(?:Get-ChildItem|gci|dir|ls)\b.*\|.*\b(?:Remove-Item|ri|del|rm)\b", "pipeline destruction via Get-ChildItem | Remove-Item"),
                (r"\brm\s+-[a-zA-Z]*r", "recursive directory removal via rm -r"),
                (r"\bdel\b\s+(?:/[sqfSQF]+\s+)?\w+", "unrestricted file deletion command targeting filesystem contents"),
                (r"\bformat\s+[a-zA-Z]:", "disk formatting command is strictly forbidden"),
                (r"\brm\s+-rf\s+[/~]", "recursive root/home deletion is strictly forbidden"),
                (r"\b(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\b.*-(?:EncodedCommand|encodedcommand|enc|e)\b", "Base64 encoded PowerShell commands conceal destructive payloads"),
                (r"\bshutil\.rmtree\b", "destructive directory tree removal via shutil.rmtree"),
                (r"\bos\.(?:remove|unlink|rmdir)\b", "destructive filesystem removal via os module"),
                (r"\bbase64\.b64decode\b.*(?:\bexec\b|\beval\b)", "obfuscated code execution via base64.b64decode"),
                (r"(?:\bexec\b|\beval\b)\s*\(\s*.*b64decode", "obfuscated code execution via exec(b64decode)"),
            ]
            for pattern, desc in destructive_patterns:
                if re.search(pattern, cmd_line, re.IGNORECASE):
                    return _check_or_create_ticket(
                        operation="destructive_command",
                        target=cmd_line,
                        reason=f"Destructive Command Violation: {desc} (Command: '{cmd_line}').",
                        payload=args,
                        actor=actor,
                    )

            # Check 3: Redirection or writing into sensitive credentials
            sensitive_patterns = [
                r">\s*.*\.env\b",
                r">\s*.*\.ssh[\\/]",
                r">\s*.*id_rsa\b",
                r">\s*.*id_ed25519\b",
                r">\s*.*\.agents[\\/]hooks\.json\b",
                r">\s*.*\.operator_",
                r">\s*.*operator_secret",
                r'\b(?:Set-Content|Out-File|Add-Content|sc|echo)\b.*-(?:Path\s+)?["\']?.*(?:\.env|\.agents[\\/]hooks\.json|id_rsa|\.operator_|operator_secret)',
            ]
            for sp in sensitive_patterns:
                if re.search(sp, cmd_line, re.IGNORECASE):
                    return _check_or_create_ticket(
                        operation="sensitive_redirect",
                        target=cmd_line,
                        reason=f"Sensitive Asset Violation: Command attempts to redirect or write into sensitive credential targets.",
                        payload=args,
                        actor=actor,
                    )

    # Priority 2: Reverse isolation for file modification from external workspace
    if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
        raw_target = args.get("TargetFile") or args.get("path") or args.get("file")
        if raw_target and is_external_workspace:
            resolved_target = Path(raw_target).resolve()
            try:
                resolved_target.relative_to(WORKSPACE_ROOT)
                return _check_or_create_ticket(
                    operation="modify_mother_core",
                    target=str(resolved_target),
                    reason=(
                        f"Reverse Isolation Violation: External project cannot write to mother core "
                        f"asset '{resolved_target.name}' without explicit approval ticket."
                    ),
                    payload=args,
                    actor=actor,
                )
            except ValueError:
                pass

    # Priority 3: Quota & Tenant Session Circuit Breaker (Fail-Closed)
    if not is_external_workspace and not payload.get("skip_quota_check") and not os.environ.get("JHOC_SKIP_QUOTA_CHECK"):
        if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content", "run_command"):
            try:
                if str(WORKSPACE_ROOT / "src") not in sys.path:
                    sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
                from jhoc.quota.antigravity_quota import evaluate_quota_alert, get_antigravity_quota_live
                from jhoc.quota.api_balance import evaluate_api_balance_alert, get_api_balances_live

                cid = (
                    payload.get("conversationId")
                    or payload.get("session_id")
                    or payload.get("task_id")
                    or payload.get("caller")
                    or payload.get("actor")
                    or (payload.get("quota_data") and "quota_test_session")
                    or os.environ.get("JHOC_SESSION_ID")
                )
                # OR-3: Canonicalize session identity (casefold, strip, remove category C chars) before sentinel check
                if cid:
                    import unicodedata
                    norm_cid = unicodedata.normalize("NFC", str(cid).strip().casefold())
                    clean_cid = "".join(ch for ch in norm_cid if not unicodedata.category(ch).startswith("C")).strip()
                else:
                    clean_cid = ""

                if not clean_cid or clean_cid == "unresolved_session":
                    # R6-D4 & OR-3: Short-circuit anonymous deny immediately before quota or cache persistence
                    # Completely prevents communal bucket aliasing and disk write amplification across all variants
                    return {
                        "decision": "deny",
                        "reason": "Anonymous tool use rejected: missing conversationId/session_id in tenant context (Fail-Closed).",
                    }

                if "quota_data" in payload:
                    quota_data = payload["quota_data"]
                else:
                    quota_data = get_antigravity_quota_live(session_id=clean_cid)
                alert = evaluate_quota_alert(quota_data, threshold_pct=8.0)

                api_balances = get_api_balances_live()
                api_alert = evaluate_api_balance_alert(api_balances)

                if alert.is_critical or api_alert.is_critical:
                    is_whitelisted = False
                    if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
                        raw_tf = str(args.get("TargetFile", "") or args.get("path", "") or args.get("file", ""))
                        tf = os.path.normpath(raw_tf).replace("\\", "/").lower()
                        whitelist_targets = (
                            "implementation_plan.md",
                            "walkthrough.md",
                            "memory/",
                            "docs/lessons/",
                            "docs/worklogs/",
                            "logs/token-stats/",
                            "logs/archive_payloads/",
                            "logs/op-log/",
                            "logs/co-review/",
                        )
                        if any(w in tf for w in whitelist_targets) and not Path(raw_tf).name.lower().startswith(".operator_"):
                            content_to_check = str(args.get("CodeContent", "") or args.get("ReplacementContent", "") or args.get("content", ""))
                            sec_file = WORKSPACE_ROOT / "runtime" / ".operator_secret"
                            if sec_file.is_file():
                                try:
                                    sec_val = sec_file.read_text(encoding="utf-8").strip()
                                    if sec_val and len(sec_val) >= 8 and sec_val in content_to_check:
                                        return {
                                            "decision": "deny",
                                            "reason": "Security Laundering Block: Whitelisted persistence file contains active operator secret.",
                                        }
                                except Exception:
                                    pass
                            is_whitelisted = True
                    elif tool_name == "run_command":
                        raw_cmd = str(args.get("CommandLine", "") or args.get("command", "")).strip()
                        cmd_norm = raw_cmd.replace("\\", "/").lower()
                        whitelist_scripts = (
                            "jhoc_shougong.py",
                            "jhoc_token_stats.py",
                            "jhoc_worklog.py",
                            "jhoc_co_review.py",
                            "jhoc_state.py",
                        )
                        git_cmds = (
                            "git status",
                            "git add",
                            "git commit",
                            "git diff",
                            "git log",
                            "git branch",
                            "git checkout",
                            "git rev-parse",
                        )
                        if any(ws in cmd_norm for ws in whitelist_scripts) or any(gc in cmd_norm for gc in git_cmds):
                            is_whitelisted = True

                    if not is_whitelisted:
                        reasons: list[str] = []
                        if alert.is_critical:
                            if alert.account_email:
                                reasons.append(f"IDE account '{alert.account_email}' quota <= 8% ({', '.join(alert.critical_buckets)})")
                            else:
                                reasons.append(f"Antigravity quota critical / unavailable ({alert.warning_message})")
                        if api_alert.is_critical:
                            reasons.append(f"API balance critical: {api_alert.warning_message}")
                        return {
                            "decision": "deny",
                            "reason": (
                                f"[CRITICAL QUOTA & BALANCE FUSE] {'; '.join(reasons)}. "
                                "All non-essential mutations blocked. Please execute handoff or recharge."
                            ),
                        }
            except Exception as exc:
                _record_blackbox_trace(
                    tool_name,
                    args,
                    "warn",
                    f"Quota probe non-fatal exception: {exc}",
                    actor=actor,
                    task_id=task_id,
                )
                return {
                    "decision": "deny",
                    "reason": f"Quota Gate Exception: Quota check failed with exception ({exc}). Failing closed.",
                }

    # Priority 4: Detailed file mutation governance checks
    if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
        # Check 1: Emoji Inspection on file write/edit
        content_to_check = args.get("CodeContent", "") or args.get("ReplacementContent", "") or args.get("content", "")
        if content_to_check and _EMOJI_RE.search(content_to_check):
            return {
                "decision": "deny",
                "reason": "Rule 7 Violation: Zero-Emoji Discipline breached. Emoji detected in file content.",
            }

        # Physical file boundary and governance checks
        raw_target = args.get("TargetFile") or args.get("path") or args.get("file")
        if raw_target:
            resolved_target = Path(raw_target).resolve()

            # Check 2: Physical workspace boundary check
            is_in_active_ws = False
            active_workspaces = [WORKSPACE_ROOT]
            for wp in ws_paths:
                active_workspaces.append(Path(wp).resolve())

            for ws in active_workspaces:
                try:
                    resolved_target.relative_to(ws)
                    is_in_active_ws = True
                    break
                except ValueError:
                    pass

            if not is_in_active_ws:
                return {
                    "decision": "deny",
                    "reason": f"Rule 5 Violation: Physical Boundary Violation: Target path '{resolved_target}' is outside all registered active workspace paths.",
                }

            # Check 2.8: Governance Root and Core Engine Protection
            try:
                rel = resolved_target.relative_to(WORKSPACE_ROOT)
                is_core = False
                if rel.parts:
                    if rel.parts[0] in (".agents", "scripts"):
                        is_core = True
                    elif rel.parts[0] == "runtime" and len(rel.parts) > 1 and rel.parts[1] == "inbox.db":
                        is_core = True
                    elif len(rel.parts) >= 2 and rel.parts[0] == "src" and rel.parts[1] == "jhoc":
                        is_core = True
                if is_core and not is_external_workspace:
                    return _check_or_create_ticket(
                        operation="modify_governance_core",
                        target=str(resolved_target),
                        reason=f"Governance Root Violation: Direct modification of core governance asset '{resolved_target.name}' is strictly protected.",
                        payload=args,
                        actor=actor,
                    )
            except ValueError:
                pass

            # Check 3: Sensitive Asset Protection
            sensitive_basenames = {".env", "inbox.db", "p19-blackbox.jsonl", "task_timeline.jsonl"}
            if resolved_target.name.lower() in sensitive_basenames:
                return _check_or_create_ticket(
                    operation="modify_sensitive_asset",
                    target=str(resolved_target),
                    reason=f"Sensitive Asset Violation: Direct modification of sensitive state asset '{resolved_target.name}' is strictly restricted.",
                    payload=args,
                    actor=actor,
                )

            # Check 4: Anti-Root-Littering Protocol (Zone 3 enforcement)
            try:
                rel_to_ws = resolved_target.relative_to(WORKSPACE_ROOT)
                if len(rel_to_ws.parts) == 1 and _LITTER_RE.match(rel_to_ws.name) and not is_external_workspace:
                    return _check_or_create_ticket(
                        operation="create_root_file",
                        target=str(resolved_target),
                        reason=f"File Persistence Routing Violation: Root Littering Violation: File '{rel_to_ws.name}' cannot be created in root directory (Rule 8: Zone 3 Enforcement).",
                        payload=args,
                        actor=actor,
                    )
            except ValueError:
                pass

            # Check 4.5: Pre-flight Inquiry Alignment Gate
            state_file = WORKSPACE_ROOT / "memory" / "v3_task_state.json"
            if state_file.is_file() and not is_external_workspace:
                try:
                    sdata = json.loads(state_file.read_text(encoding="utf-8"))
                    status = sdata.get("status") or sdata.get("task_state")
                    inq_status = sdata.get("inquiry_status")
                    inq_probe = sdata.get("inquiry_probe", {})
                    is_pending = False
                    if status == "ARMED":
                        if inq_status == "PENDING":
                            is_pending = True
                        elif inq_probe.get("required") and not inq_probe.get("confirmed"):
                            is_pending = True

                    if is_pending:
                        raw_tf = str(args.get("TargetFile", "") or args.get("path", "") or args.get("file", ""))
                        tf_norm = raw_tf.replace("\\", "/").lower()
                        allowed_pending = (
                            "implementation_plan.md",
                            "walkthrough.md",
                            "memory/",
                            "docs/",
                            "tests/",
                        )
                        if not any(ap in tf_norm for ap in allowed_pending):
                            return {
                                "decision": "deny",
                                "reason": (
                                    "[INQUIRY PENDING GATE] Inquiry Gate Violation: Pre-flight counter-questioning probe is PENDING. "
                                    "Model cannot write production code before user explicitly aligns on 4 dimensions."
                                ),
                            }
                except Exception:
                    pass

    return {"decision": "allow"}

def evaluate_payload(payload: dict) -> dict:
    actor, task_id = _resolve_caller_identity(payload)
    try:
        result = _evaluate_inner(payload, actor=actor, task_id=task_id)
    except Exception as e:
        # R6-D7: Explicit fault envelope distinguishable from policy deny
        result = {
            "decision": "deny",
            "reason": f"Hook execution internal fault: {type(e).__name__} (Fail-Closed).",
            "is_fault": True,
            "fault_type": type(e).__name__,
        }
    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "unknown")
    args = tool_call.get("args", {})
    _record_blackbox_trace(
        tool_name,
        args,
        result.get("decision", "allow"),
        result.get("reason", ""),
        actor=actor,
        task_id=task_id,
    )
    return result


def main() -> int:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            # Fail closed: Empty stdin in hook context is a plumbing failure (F-1 closure)
            print(json.dumps({"decision": "deny", "reason": "Empty payload received on stdin (Fail-Closed)."}))
            sys.stdout.flush()
            return 0
        payload = json.loads(raw_input)
        result = evaluate_payload(payload)
        print(json.dumps(result))
        sys.stdout.flush()
        return 0
    except Exception as e:
        # Fail closed on malformed input or internal crash with stderr recovery (F-2, A-1 & R6-D5 closure)
        try:
            # R6-D7: Generic sanitized fault envelope on stdout (B-7 closure)
            print(json.dumps({
                "decision": "deny",
                "reason": "Hook execution exception encountered (Fail-Closed).",
                "is_fault": True,
                "fault_type": type(e).__name__,
            }))
            sys.stdout.flush()
            return 0
        except Exception as inner_e:
            # Double fault: stdout broken or unprintable -> must exit non-zero 2 (A-1 & R6-D5 closure)
            sys.stderr.write(f"FATAL: Hook crash and stdout write failed: {e}; inner: {inner_e}\n")
            sys.exit(2)


if __name__ == "__main__":
    sys.exit(main())
