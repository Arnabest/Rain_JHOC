"""Antigravity IDE Connect-RPC Quota & Account Live Inspector.

Provides 1-to-1 session-bound quota extraction and 8% threshold alerting
for Gemini 5-Hour and Weekly limits across multiple accounts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
import os
from pathlib import Path
import sys
import re
import subprocess
import time
from typing import Any, Mapping
import urllib.request
import ssl

CRITICAL_THRESHOLD_PERCENT = 8.0
WARNING_THRESHOLD_PERCENT = 12.0
RESET_THRESHOLD_PERCENT = 10.0


def format_iso_reset(reset_str: str | None) -> str:
    """Format ISO 8601 reset timestamp into readable countdown (e.g., ~4h23m, ~3d11h)."""
    if not reset_str:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(reset_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        diff_sec = int((dt - now).total_seconds())
        if diff_sec <= 0:
            return "refreshing_soon"
        days = diff_sec // 86400
        hours = (diff_sec % 86400) // 3600
        mins = (diff_sec % 3600) // 60
        if days > 0:
            return f"~{days}d{hours}h"
        elif hours > 0:
            return f"~{hours}h{mins}m"
        else:
            return f"~{mins}m"
    except Exception:
        return ""


@dataclass(frozen=True, slots=True)
class QuotaAlert:
    is_critical: bool
    alert_level: str
    critical_buckets: tuple[str, ...]
    account_email: str
    warning_message: str
    handover_recommended: bool
    details: Mapping[str, Any] = field(default_factory=dict)


def evaluate_quota_alert(
    quota_data: Mapping[str, Any] | None,
    threshold_pct: float = CRITICAL_THRESHOLD_PERCENT,
    warning_threshold_pct: float = WARNING_THRESHOLD_PERCENT,
    reset_threshold_pct: float = RESET_THRESHOLD_PERCENT,
    prior_alert_level: str | None = None,
) -> QuotaAlert:
    """Evaluate quota with control-theoretic hysteresis deadband (B-5 / D4 closure)."""
    if not quota_data or not quota_data.get("enabled"):
        return QuotaAlert(
            is_critical=True,
            alert_level="UNKNOWN",
            critical_buckets=(),
            account_email="",
            warning_message="Antigravity quota status unavailable or disabled. Failing closed.",
            handover_recommended=True,
            details={},
        )

    account_email = str(quota_data.get("account_email") or "unknown_account")
    gemini_5h = quota_data.get("gemini_5h_pct")
    gemini_weekly = quota_data.get("gemini_weekly_pct")

    # Control-Theoretic Hysteresis:
    # If currently CRITICAL, latch until quota strictly recovers above reset_threshold_pct (10.0%)
    # If not CRITICAL, trip into CRITICAL when quota falls to or below threshold_pct (8.0%)
    effective_critical_cutoff = reset_threshold_pct if prior_alert_level == "CRITICAL" else threshold_pct

    crit_buckets: list[str] = []
    messages: list[str] = []

    if isinstance(gemini_5h, (int, float)) and gemini_5h <= effective_critical_cutoff:
        reset_hint = quota_data.get("gemini_5h_reset", "")
        crit_buckets.append("5-Hour Limit")
        cutoff_note = f"<= {effective_critical_cutoff}% (latched hysteresis)" if prior_alert_level == "CRITICAL" else f"<= {threshold_pct}%"
        messages.append(f"Gemini 5-Hour quota is CRITICAL at {gemini_5h}% ({cutoff_note}, Reset: {reset_hint or 'pending'})")

    if isinstance(gemini_weekly, (int, float)) and gemini_weekly <= effective_critical_cutoff:
        reset_hint = quota_data.get("gemini_weekly_reset", "")
        crit_buckets.append("Weekly Limit")
        cutoff_note = f"<= {effective_critical_cutoff}% (latched hysteresis)" if prior_alert_level == "CRITICAL" else f"<= {threshold_pct}%"
        messages.append(f"Gemini Weekly quota is CRITICAL at {gemini_weekly}% ({cutoff_note}, Reset: {reset_hint or 'pending'})")

    is_critical = len(crit_buckets) > 0
    if is_critical:
        alert_msg = (
            f"[CRITICAL QUOTA ALERT] Account '{account_email}' quota is near exhaustion (<= {threshold_pct}%): "
            + "; ".join(messages)
            + ". Action required: persist all memory/code immediately and trigger inter-model / account handoff."
        )
        return QuotaAlert(
            is_critical=True,
            alert_level="CRITICAL",
            critical_buckets=tuple(crit_buckets),
            account_email=account_email,
            warning_message=alert_msg,
            handover_recommended=True,
            details=dict(quota_data),
        )

    # Dual-Track Soft Warning Track (8.0% < quota <= 12.0%)
    warn_buckets: list[str] = []
    warn_messages: list[str] = []
    if isinstance(gemini_5h, (int, float)) and gemini_5h <= WARNING_THRESHOLD_PERCENT:
        warn_buckets.append("5-Hour Limit")
        warn_messages.append(f"Gemini 5-Hour quota at {gemini_5h}% (Warning buffer <= {WARNING_THRESHOLD_PERCENT}%)")
    if isinstance(gemini_weekly, (int, float)) and gemini_weekly <= WARNING_THRESHOLD_PERCENT:
        warn_buckets.append("Weekly Limit")
        warn_messages.append(f"Gemini Weekly quota at {gemini_weekly}% (Warning buffer <= {WARNING_THRESHOLD_PERCENT}%)")

    if warn_buckets:
        warn_msg = (
            f"[QUOTA WARNING] Account '{account_email}' entering handover buffer: "
            + "; ".join(warn_messages)
            + ". Prepare handover and checkpoint artifacts before critical threshold."
        )
        return QuotaAlert(
            is_critical=False,
            alert_level="WARNING",
            critical_buckets=tuple(warn_buckets),
            account_email=account_email,
            warning_message=warn_msg,
            handover_recommended=True,
            details=dict(quota_data),
        )

    return QuotaAlert(
        is_critical=False,
        alert_level="OK",
        critical_buckets=(),
        account_email=account_email,
        warning_message="Account quota within normal operating range.",
        handover_recommended=False,
        details=dict(quota_data),
    )


def _http_post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout_sec: float = 1.0) -> dict[str, Any] | None:
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout_sec) as resp:
            if resp.status == 200:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
    except Exception:
        return None
    return None


def _atomic_replace_cache(target_file: Path, payload: dict, max_retries: int = 5, backoff_sec: float = 0.005) -> None:
    """R6-D1: Atomically writes cache file with retry and cleans temp files in finally."""
    target_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = target_file.with_name(f"{target_file.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        temp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        replaced = False
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                os.replace(temp_file, target_file)
                replaced = True
                break
            except Exception as e:
                last_err = e
                time.sleep(backoff_sec * (attempt + 1))
        if not replaced:
            sys.stderr.write(f"FATAL: Atomic cache write failed to replace {target_file} after {max_retries} retries: {last_err}\n")
            raise OSError(f"Atomic cache write failed to replace {target_file} after {max_retries} retries: {last_err}")
    finally:
        if temp_file.is_file():
            try:
                temp_file.unlink()
            except Exception:
                pass

def get_antigravity_quota_live(session_id: str | None = None, max_cache_age_sec: float = 60.0, cache_dir: Path | None = None) -> dict[str, Any] | None:
    """Fetch live Antigravity Models & Usage quota groups through Language Server Connect-RPC."""
    root_dir = cache_dir or (Path(__file__).resolve().parents[3] / "logs" / "token-stats")
    runtime_cache_file = (cache_dir / ".quota_cache.json") if cache_dir else (Path(__file__).resolve().parents[3] / "runtime" / ".quota_cache.json")
    import hashlib
    import unicodedata
    # R6-D6 & R-9: Canonicalize session identity (Unicode NFC, whitespace trim, case fold, strip invisible/control/format chars)
    if session_id:
        norm = unicodedata.normalize("NFC", str(session_id).strip().casefold())
        canon_sid = "".join(ch for ch in norm if not unicodedata.category(ch).startswith("C")).strip() or None
    else:
        canon_sid = None
    safe_sid = hashlib.sha256(canon_sid.encode("utf-8")).hexdigest()[:24] if canon_sid else None
    cache_name = f"antigravity_quota_cache_{safe_sid}.json" if safe_sid else "antigravity_quota_cache.json"
    cache_file = root_dir / cache_name
    now_ts = time.time()


    def _load_cached_quota(c_file: Path, max_age: float | None = None) -> dict[str, Any] | None:
        if c_file.is_file():
            try:
                cached = json.loads(c_file.read_text(encoding="utf-8"))
                age = now_ts - cached.get("timestamp", 0)
                if max_age is None or age < max_age:
                    return cached.get("data")
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                # R6-D7 & R-7: Corrupt/torn cache handling.
                # Must fail conservatively: never fail open or allow fallback to 100% healthy.
                sys.stderr.write(f"WARN: Corrupt cache file detected at {c_file}: {err}\n")
                return {
                    "account_email": "corrupted_cache@jhoc.fault",
                    "account_name": "Corrupted Cache Fail-Closed",
                    "gemini_5h_pct": 0.0,
                    "gemini_weekly_pct": 0.0,
                    "gemini_5h_reset": "UNKNOWN",
                    "gemini_weekly_reset": "UNKNOWN",
                    "claude_gpt_5h_pct": 0.0,
                    "claude_gpt_weekly_pct": 0.0,
                    "enabled": True,
                    "is_critical": True,
                    "alert_level": "CRITICAL",
                    "corrupt_cache": True,
                    "from_fallback_cache": True,
                }
            except Exception:
                pass
        return None

    # Step 0: Check fresh cache (60s for healthy, 15s for critical, strictly session-scoped if session_id is provided)
    cached_data = _load_cached_quota(cache_file)
    if not cached_data and not session_id:
        cached_data = _load_cached_quota(runtime_cache_file)
    if cached_data:
        if cached_data.get("corrupt_cache"):
            return cached_data
        g5 = cached_data.get("gemini_5h_pct", 100)
        gw = cached_data.get("gemini_weekly_pct", 100)
        effective_ttl = 15.0 if (g5 <= 8 or gw <= 8) else max_cache_age_sec
        fresh_data = _load_cached_quota(cache_file, max_age=effective_ttl) if session_id else (_load_cached_quota(cache_file, max_age=effective_ttl) or _load_cached_quota(runtime_cache_file, max_age=effective_ttl))
        if fresh_data:
            return fresh_data

    # Test mode / offline mock check (only if no explicit cache file exists)
    import os
    if os.environ.get("JHOC_SKIP_LIVE_QUOTA_PROBE") == "1" or os.environ.get("JHOC_TESTING") == "1" or "unittest" in sys.modules:
        return {
            "enabled": True,
            "account_email": "mock_operator@example.com",
            "gemini_5h_pct": 100.0,
            "gemini_weekly_pct": 100.0,
            "gemini_5h_reset": "~4h",
            "gemini_weekly_reset": "~6d",
        }

    def _get_stale_fallback(s_file: Path, r_file: Path, s_id: str | None) -> dict[str, Any] | None:
        # R6-D3: Parameter-bound stale fallback ensuring zero module-global leakage
        stale = _load_cached_quota(s_file) if s_id else _load_cached_quota(r_file)
        if stale:
            stale_copy = dict(stale)
            stale_copy["from_fallback_cache"] = True
            return stale_copy
        return None

    # Step 1: Detect language_server_windows_x64.exe processes and CSRF tokens
    ps_cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_Process -Filter \"name='language_server_windows_x64.exe'\" | Select-Object ProcessId, CommandLine | ConvertTo-Json"
    ]
    try:
        proc = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=3)
        if proc.returncode != 0 or not proc.stdout.strip():
            return _get_stale_fallback(cache_file, runtime_cache_file, session_id)
        items = json.loads(proc.stdout)
        if isinstance(items, dict):
            items = [items]
    except Exception:
        return _get_stale_fallback(cache_file, runtime_cache_file, session_id)

    candidates: list[tuple[int, str]] = []
    for it in items:
        pid = it.get("ProcessId")
        cl = it.get("CommandLine", "")
        m_csrf = re.search(r"--csrf_token\s+([0-9a-fA-F\-]+)", cl)
        if pid and m_csrf:
            candidates.append((int(pid), m_csrf.group(1)))

    if not candidates:
        return _get_stale_fallback(cache_file, runtime_cache_file, session_id)

    # Step 2: Query active listening ports
    net_cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-NetTCPConnection -State Listen | Select-Object OwningProcess, LocalPort | ConvertTo-Json"
    ]
    try:
        proc2 = subprocess.run(net_cmd, capture_output=True, text=True, timeout=3)
        conns = json.loads(proc2.stdout) if proc2.returncode == 0 and proc2.stdout.strip() else []
        if isinstance(conns, dict):
            conns = [conns]
    except Exception:
        conns = []

    pid_to_ports: dict[int, list[int]] = {}
    for c in conns:
        p = c.get("OwningProcess")
        port = c.get("LocalPort")
        if p and port:
            pid_to_ports.setdefault(int(p), []).append(int(port))

    matched_target: dict[str, Any] | None = None
    fallback_targets: list[dict[str, Any]] = []

    for pid, csrf in candidates:
        ports = pid_to_ports.get(pid, [])
        for port in ports:
            headers = {
                "Content-Type": "application/json",
                "Connect-Protocol-Version": "1",
                "x-codeium-csrf-token": csrf,
            }
            try:
                u_resp = _http_post_json(
                    f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetUserStatus",
                    headers=headers,
                    payload={},
                    timeout_sec=0.8,
                )
                if not u_resp:
                    continue
                u_st = u_resp.get("userStatus", {})

                traj_resp = _http_post_json(
                    f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetAllCascadeTrajectories",
                    headers=headers,
                    payload={},
                    timeout_sec=0.8,
                )
                trajs = traj_resp.get("trajectorySummaries", {}) if traj_resp else {}

                srv = {
                    "port": port,
                    "headers": headers,
                    "user_status": u_st,
                    "trajectories": trajs,
                }
                fallback_targets.append(srv)

                if session_id and (session_id in trajs or any(session_id == (v.get("trajectoryId") or "") for v in trajs.values())):
                    matched_target = srv
                    break
            except Exception:
                continue
        if matched_target:
            break

    if session_id:
        target_server = matched_target
    else:
        target_server = fallback_targets[0] if fallback_targets else None
    if not target_server:
        return _get_stale_fallback(cache_file, runtime_cache_file, session_id) if not session_id else None

    q_resp = _http_post_json(
        f"https://127.0.0.1:{target_server['port']}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
        headers=target_server["headers"],
        payload={},
        timeout_sec=0.8,
    )
    if not q_resp:
        return _get_stale_fallback(cache_file, runtime_cache_file, session_id)

    u_st = target_server["user_status"]
    account_email = u_st.get("email", "")
    account_name = u_st.get("name", "")
    plan_info = u_st.get("planStatus", {}).get("planInfo", {})
    plan = f"Google AI {plan_info.get('planName')}" if plan_info.get("planName") else "Google AI Pro"

    groups = (q_resp.get("response") or {}).get("groups") or []
    gemini_5h_pct = None
    gemini_5h_reset = ""
    gemini_weekly_pct = None
    gemini_weekly_reset = ""
    claude_gpt_5h_pct = None
    claude_gpt_weekly_pct = None

    for g in groups:
        dname = (g.get("displayName") or "").lower()
        buckets = g.get("buckets") or []
        for b in buckets:
            bid = (b.get("bucketId") or "").lower()
            bname = (b.get("displayName") or "").lower()
            frac = b.get("remainingFraction", 1.0)
            pct = round(frac * 100)
            reset_hint = format_iso_reset(b.get("resetTime"))

            if "gemini" in dname or "gemini" in bid:
                if "5h" in bid or "5-hour" in bname or "five hour" in bname:
                    gemini_5h_pct = pct
                    gemini_5h_reset = reset_hint
                elif "weekly" in bid or "weekly" in bname:
                    gemini_weekly_pct = pct
                    gemini_weekly_reset = reset_hint
            elif "claude" in dname or "gpt" in dname or "3p" in bid:
                if "5h" in bid or "5-hour" in bname or "five hour" in bname:
                    claude_gpt_5h_pct = pct
                elif "weekly" in bid or "weekly" in bname:
                    claude_gpt_weekly_pct = pct

    data = {
        "source": "antigravity-ide",
        "plan": plan,
        "account_email": account_email,
        "account_name": account_name,
        "gemini_5h_pct": gemini_5h_pct if gemini_5h_pct is not None else 100,
        "gemini_5h_reset": gemini_5h_reset,
        "gemini_weekly_pct": gemini_weekly_pct if gemini_weekly_pct is not None else 100,
        "gemini_weekly_reset": gemini_weekly_reset,
        "claude_gpt_5h_pct": claude_gpt_5h_pct if claude_gpt_5h_pct is not None else 100,
        "claude_gpt_weekly_pct": claude_gpt_weekly_pct if claude_gpt_weekly_pct is not None else 100,
        "enabled": True,
        "timestamp": now_ts,
    }

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        _atomic_replace_cache(cache_file, {"timestamp": now_ts, "data": data})
        if not session_id:
            _atomic_replace_cache(runtime_cache_file, {"timestamp": now_ts, "data": data})
    except Exception:
        pass

    return data


def format_quota_markdown(quota_data: Mapping[str, Any] | None, alert: QuotaAlert | None = None) -> str:
    """Render quota status into clean, zero-emoji Markdown line and alert banners."""
    if not quota_data:
        return "- Gemini 配额: 无法连接至 Antigravity 本地 Language Server (离线或无可用实例)"

    plan = quota_data.get("plan", "Google AI Pro")
    email = quota_data.get("account_email", "")
    account_badge = f"[{plan} · {email}]" if email else f"[{plan}]"

    g_5h = quota_data.get("gemini_5h_pct", 100)
    g_5h_r = quota_data.get("gemini_5h_reset", "")
    g_wk = quota_data.get("gemini_weekly_pct", 100)
    g_wk_r = quota_data.get("gemini_weekly_reset", "")
    c_3p = quota_data.get("claude_gpt_5h_pct", 100)

    line = (
        f"- Gemini 配额: 方案 `{account_badge}` · "
        f"Gemini 5小时剩余 **{g_5h}%**"
        + (f" (重置: `{g_5h_r}`)" if g_5h_r else "")
        + f" · 每周剩余 **{g_wk}%**"
        + (f" (重置: `{g_wk_r}`)" if g_wk_r else "")
        + f" · Claude/GPT 剩余 **{c_3p}%**"
    )

    if alert and alert.is_critical:
        banner = (
            f"\n> [!WARNING] **[CRITICAL QUOTA ALERT]** 当前账户 `{alert.account_email}` 配额已低于 8% 临界阈值！\n"
            f"> 告急限额项: {', '.join(alert.critical_buckets)}\n"
            f"> **处置建议**: 请立即物理写入全部已修改代码，固化 implementation_plan.md / session.md 共享记忆，并切换备用账户接力。"
        )
        return banner + "\n" + line

    return line
