"""Antigravity IDE Connect-RPC Quota & Account Live Inspector.

Provides 1-to-1 session-bound quota extraction and 8% threshold alerting
for Gemini 5-Hour and Weekly limits across multiple accounts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping
import urllib.request
import ssl

CRITICAL_THRESHOLD_PERCENT = 8.0


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


def evaluate_quota_alert(quota_data: Mapping[str, Any] | None, threshold_pct: float = CRITICAL_THRESHOLD_PERCENT) -> QuotaAlert:
    """Evaluate whether 5H or Weekly Gemini quota is at or below critical threshold."""
    if not quota_data or not quota_data.get("enabled"):
        return QuotaAlert(
            is_critical=False,
            alert_level="UNKNOWN",
            critical_buckets=(),
            account_email="",
            warning_message="Antigravity quota status unavailable or disabled.",
            handover_recommended=False,
            details={},
        )

    account_email = str(quota_data.get("account_email") or "unknown_account")
    gemini_5h = quota_data.get("gemini_5h_pct")
    gemini_weekly = quota_data.get("gemini_weekly_pct")

    crit_buckets: list[str] = []
    messages: list[str] = []

    if isinstance(gemini_5h, (int, float)) and gemini_5h <= threshold_pct:
        reset_hint = quota_data.get("gemini_5h_reset", "")
        crit_buckets.append("5-Hour Limit")
        messages.append(f"Gemini 5-Hour quota is CRITICAL at {gemini_5h}% (Reset: {reset_hint or 'pending'})")

    if isinstance(gemini_weekly, (int, float)) and gemini_weekly <= threshold_pct:
        reset_hint = quota_data.get("gemini_weekly_reset", "")
        crit_buckets.append("Weekly Limit")
        messages.append(f"Gemini Weekly quota is CRITICAL at {gemini_weekly}% (Reset: {reset_hint or 'pending'})")

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


def get_antigravity_quota_live(session_id: str | None = None, max_cache_age_sec: float = 15.0, cache_dir: Path | None = None) -> dict[str, Any] | None:
    """Fetch live Antigravity Models & Usage quota groups through Language Server Connect-RPC."""
    root_dir = cache_dir or (Path(__file__).resolve().parents[3] / "logs" / "token-stats")
    cache_name = f"antigravity_quota_cache_{session_id}.json" if session_id else "antigravity_quota_cache.json"
    cache_file = root_dir / cache_name
    now_ts = time.time()

    if cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if now_ts - cached.get("timestamp", 0) < max_cache_age_sec:
                return cached.get("data")
        except Exception:
            pass

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
            return None
        items = json.loads(proc.stdout)
        if isinstance(items, dict):
            items = [items]
    except Exception:
        return None

    candidates: list[tuple[int, str]] = []
    for it in items:
        pid = it.get("ProcessId")
        cl = it.get("CommandLine", "")
        m_csrf = re.search(r"--csrf_token\s+([0-9a-fA-F\-]+)", cl)
        if pid and m_csrf:
            candidates.append((int(pid), m_csrf.group(1)))

    if not candidates:
        return None

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

    target_server = matched_target or (fallback_targets[0] if fallback_targets else None)
    if not target_server:
        return None

    q_resp = _http_post_json(
        f"https://127.0.0.1:{target_server['port']}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
        headers=target_server["headers"],
        payload={},
        timeout_sec=0.8,
    )
    if not q_resp:
        return None

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
        cache_file.write_text(json.dumps({"timestamp": now_ts, "data": data}, ensure_ascii=False, indent=2), encoding="utf-8")
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
