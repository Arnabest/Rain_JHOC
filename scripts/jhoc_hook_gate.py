"""JHOC PreToolUse Hook Gate - Physical interceptor for IDE tool execution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]")
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


_LITTER_RE = re.compile(
    r"^(test_|tmp_|temp_|dump_|debug_|scratch_|out_).*\.(py|json|txt|log|sh|bat)$|^(test|tmp|temp|dump|debug|scratch|out)\.(py|json|txt|log|sh|bat)$",
    re.IGNORECASE,
)


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
            # Under lock contention, fail-closed to prevent hash chain forking
            return

        try:
            prev_hash = "0" * 64
            seq = 1
            if blackbox_file.is_file():
                lines = [l for l in blackbox_file.read_text(encoding="utf-8").splitlines() if l.strip()]
                if lines:
                    try:
                        last_obj = json.loads(lines[-1])
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
    tool_call = payload.get("toolCall", {})
    raw_tool = tool_call.get("name") or payload.get("toolName") or payload.get("tool") or ""
    tool_lower = raw_tool.lower()
    args = dict(tool_call.get("args", {}))

    # Cross-harness tool alias normalization
    if tool_lower in ("run_command", "bash", "terminal", "execute_command", "shell"):
        tool_name = "run_command"
        if "command" in args and "CommandLine" not in args:
            args["CommandLine"] = args["command"]
    elif tool_lower in ("write_to_file", "replace_file_content", "multi_replace_file_content", "edit", "write", "str_replace_editor", "create_file"):
        tool_name = "write_to_file" if tool_lower not in ("replace_file_content", "multi_replace_file_content") else raw_tool
        if "path" in args and "TargetFile" not in args:
            args["TargetFile"] = args["path"]
        if "file" in args and "TargetFile" not in args:
            args["TargetFile"] = args["file"]
        if "content" in args and "CodeContent" not in args:
            args["CodeContent"] = args["content"]
    else:
        tool_name = raw_tool

    # Check 0: Concurrency write freeze during shougong post-flight verification
    write_freeze_file = WORKSPACE_ROOT / "runtime" / "write_freeze.lock"
    if write_freeze_file.is_file():
        if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
            return {
                "decision": "deny",
                "reason": "Concurrency Conflict: System write freeze is active during shougong verification. Code mutation is blocked.",
            }

    # Check 0.5: Multi-Model File Mutex Lease Check
    if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
        target_file = args.get("TargetFile", "")
        if target_file:
            try:
                hub_db = WORKSPACE_ROOT / "logs" / "p19-hub.sqlite"
                if hub_db.is_file():
                    from jhoc.hub import JHOCMultiModelHub
                    hub = JHOCMultiModelHub(hub_db)
                    allowed, active_lease = hub.check_file_lease(target_file, requesting_model_id=actor)
                    if not allowed and active_lease:
                        return {
                            "decision": "deny",
                            "reason": (
                                f"File Mutex Conflict: '{target_file}' is actively locked by model "
                                f"'{active_lease.locked_by_model}' (Task: {active_lease.task_id or 'none'}). "
                                f"Lease expires at {active_lease.expires_at}."
                            ),
                        }
                    # Automatically acquire/renew lease for current calling model
                    hub.acquire_file_lease(actor, target_file, task_id=task_id, ttl_seconds=120)
            except Exception:
                pass

    # Check 1: Emoji Inspection on file write/edit
    if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
        content_to_check = args.get("CodeContent", "") or args.get("ReplacementContent", "")
        if isinstance(content_to_check, str) and _EMOJI_RE.search(content_to_check):
            return {
                "decision": "deny",
                "reason": "Rule 7 Violation: Zero-Emoji Discipline breached. Emoji detected in code/content payload.",
            }

        # Check 2: Physical workspace boundary check
        target_file = args.get("TargetFile", "")
        if target_file:
            try:
                resolved_target = Path(target_file).resolve()
                allowed_roots = [WORKSPACE_ROOT]
                for ws in payload.get("workspacePaths", []):
                    try:
                        allowed_roots.append(Path(ws).resolve())
                    except Exception:
                        pass

                is_contained = any(
                    str(resolved_target).lower().startswith(str(root).lower())
                    for root in allowed_roots
                ) or (".gemini\\antigravity-ide\\brain" in str(resolved_target).lower())

                if not is_contained:
                    return {
                        "decision": "deny",
                        "reason": f"Rule 5 Violation: TargetFile ({target_file}) outside allowed workspace boundaries.",
                    }

                # Check 2.7: Reverse Isolation (External Project Protection)
                is_external_workspace = False
                ws_paths = payload.get("workspacePaths", [])
                if ws_paths:
                    for wp in ws_paths:
                        try:
                            Path(wp).resolve().relative_to(WORKSPACE_ROOT)
                        except ValueError:
                            is_external_workspace = True
                            break
                if is_external_workspace:
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

                # Check 2.8: Governance Root and Core Engine Protection
                try:
                    sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
                    from jhoc.guard.path import PathGuard
                    if PathGuard.is_governance_asset(resolved_target):
                        return _check_or_create_ticket(
                            operation="modify_governance_root",
                            target=str(resolved_target),
                            reason=f"Governance Root Violation: Direct modification of core governance asset '{resolved_target.name}' is strictly protected.",
                            payload=args,
                            actor=actor,
                        )
                except Exception:
                    pass

                # Check 3: Sensitive Asset Protection
                try:
                    sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
                    from jhoc.guard.path import PathGuard
                    if PathGuard.is_sensitive(resolved_target):
                        return _check_or_create_ticket(
                            operation="write_sensitive_asset",
                            target=str(resolved_target),
                            reason=f"Sensitive Asset Violation: TargetFile ({resolved_target.name}) matches sensitive asset blacklist.",
                            payload=args,
                            actor=actor,
                        )
                except Exception:
                    pass

                # Check 4: Anti-Root-Littering Protocol (Zone 3 enforcement)
                for root in allowed_roots:
                    if resolved_target.parent == root:
                        if _LITTER_RE.match(resolved_target.name):
                            return _check_or_create_ticket(
                                operation="root_script_write",
                                target=resolved_target.name,
                                reason=(
                                    f"File Persistence Routing Violation: Creating ad-hoc test/dump script ({resolved_target.name}) "
                                    "directly in project root is forbidden. Please route to scratch/ directory."
                                ),
                                payload=args,
                                actor=actor,
                            )
            except Exception as e:
                return {
                    "decision": "deny",
                    "reason": f"Path validation error: {e}",
                }

    # Check for run_command tool execution
    if tool_name == "run_command":
        cmd_line = args.get("CommandLine", "")
        if isinstance(cmd_line, str):
            # Check 0.8: Privilege Escalation & Self-Approval Prevention
            if re.search(r"(?:python(?:\d+)?|py)\s+.*jhoc_approve\.py\b.*(?:approve|reject)", cmd_line, re.IGNORECASE):
                return {
                    "decision": "deny",
                    "reason": (
                        "Privilege Escalation Violation: Autonomous model is strictly forbidden from executing "
                        "jhoc_approve.py (self-approval attempt blocked). Operator intervention is required."
                    ),
                }

            # Check 0.8.1: Ledger Tampering & Token Spoofing Prevention
            if re.search(r"\b(?:sqlite3|python(?:\d+)?|py)\b.*(?:\.open|\.connect|attach|update|delete|insert).*['\"]?.*(?:inbox\.db|p19-hub\.sqlite)", cmd_line, re.IGNORECASE) or \
               re.search(r"(?:UPDATE|DELETE|INSERT\s+INTO)\s+jhoc_approval_inbox", cmd_line, re.IGNORECASE) or \
               re.search(r"(?:set\s+|export\s+|\$env:)?JHOC_OPERATOR_TOKEN\s*=", cmd_line, re.IGNORECASE):
                return {
                    "decision": "deny",
                    "reason": "Ledger Tampering Violation: Direct commandline manipulation of governance database or token spoofing is strictly prohibited.",
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
                (r"\bdel\b\s+(?:/[sqfSQF]+\s+)?[\w\.\*\\]+", "unrestricted file deletion command targeting filesystem contents"),
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
                r"\b(?:Set-Content|Out-File|Add-Content|sc)\b.*-(?:Path\s+)?['\"]?.*(?:\.env|\.agents[\\/]hooks\.json|id_rsa)",
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

    return {"decision": "allow"}


def evaluate_payload(payload: dict) -> dict:
    actor, task_id = _resolve_caller_identity(payload)
    result = _evaluate_inner(payload, actor=actor, task_id=task_id)
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


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print(json.dumps({"decision": "allow"}))
            return
        payload = json.loads(raw_input)
        result = evaluate_payload(payload)
        print(json.dumps(result))
    except Exception as e:
        # Fail closed on malformed input or internal crash
        print(json.dumps({"decision": "deny", "reason": f"Hook exception: {e}"}))


if __name__ == "__main__":
    main()
