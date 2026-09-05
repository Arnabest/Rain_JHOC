# -*- coding: utf-8 -*-
"""JHOC Multi-Provider API Key Balance & Credit Inspector.

Bridges to Verse Agent API Balance plugin and provides standalone
probing for DeepSeek, SiliconFlow, OpenRouter, and OpenAI-compatible keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
import logging
from pathlib import Path
import ssl
import sys
import time
from typing import Any, Dict, List, Mapping, Optional
import urllib.request

_logger = logging.getLogger("jhoc.quota.api_balance")

DEFAULT_CRITICAL_CNY = 2.0
DEFAULT_CRITICAL_USD = 0.5


@dataclass(frozen=True, slots=True)
class APIKeyBalance:
    provider: str
    currency: str
    total_balance: float
    is_available: bool = True
    status: str = "healthy"  # 'healthy', 'critical', 'unmetered', 'error'
    error_message: str = ""
    updated_at: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "currency": self.currency,
            "total_balance": round(self.total_balance, 4),
            "is_available": self.is_available,
            "status": self.status,
            "error_message": self.error_message,
            "updated_at": self.updated_at,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class APIBalanceAlert:
    is_critical: bool
    alert_level: str  # 'OK', 'CRITICAL', 'UNKNOWN'
    critical_providers: tuple[str, ...]
    warning_message: str
    balances: Mapping[str, APIKeyBalance] = field(default_factory=dict)


def _http_get_json(url: str, headers: Dict[str, str], timeout_sec: float = 2.5) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout_sec) as resp:
            if resp.status == 200:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
    except Exception as e:
        _logger.debug("Balance HTTP GET %s failed: %s", url, e)
        return None
    return None


def probe_deepseek_balance(api_key: str, base_url: str = "https://api.deepseek.com") -> Optional[APIKeyBalance]:
    if not api_key:
        return None
    endpoint = f"{base_url.rstrip('/')}/user/balance"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = _http_get_json(endpoint, headers=headers, timeout_sec=2.5)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if not data or not isinstance(data, dict):
        return None

    is_available = bool(data.get("is_available", True))
    balance_infos = data.get("balance_infos", [])
    total_val = 0.0
    currency = "CNY"

    if balance_infos and isinstance(balance_infos, list):
        primary = balance_infos[0]
        currency = primary.get("currency", "CNY")
        try:
            total_val = float(primary.get("total_balance", 0.0))
        except (ValueError, TypeError):
            pass

    status = "healthy" if (is_available and total_val > DEFAULT_CRITICAL_CNY) else "critical"
    return APIKeyBalance(
        provider="DeepSeek",
        currency=currency,
        total_balance=total_val,
        is_available=is_available,
        status=status,
        updated_at=now_iso,
        details=data,
    )


def probe_siliconflow_balance(api_key: str, base_url: str = "https://api.siliconflow.cn") -> Optional[APIKeyBalance]:
    if not api_key:
        return None
    endpoint = f"{base_url.rstrip('/')}/v1/user/info"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = _http_get_json(endpoint, headers=headers, timeout_sec=2.5)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if not data or not isinstance(data, dict) or data.get("code") != 20000:
        return None

    u_data = data.get("data", {})
    try:
        total_bal = float(u_data.get("totalBalance", u_data.get("balance", 0.0)))
    except (ValueError, TypeError):
        total_bal = 0.0

    status = "healthy" if total_bal > DEFAULT_CRITICAL_CNY else "critical"
    return APIKeyBalance(
        provider="SiliconFlow",
        currency="CNY",
        total_balance=total_bal,
        is_available=True,
        status=status,
        updated_at=now_iso,
        details=u_data,
    )


def probe_openrouter_balance(api_key: str, base_url: str = "https://openrouter.ai") -> Optional[APIKeyBalance]:
    if not api_key:
        return None
    endpoint = f"{base_url.rstrip('/')}/api/v1/credits"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = _http_get_json(endpoint, headers=headers, timeout_sec=2.5)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if not data or not isinstance(data, dict):
        return None

    c_data = data.get("data", {})
    try:
        total_credits = float(c_data.get("total_credits", 0.0))
        total_usage = float(c_data.get("total_usage", 0.0))
        remaining = max(0.0, total_credits - total_usage)
    except (ValueError, TypeError):
        remaining = 0.0

    status = "healthy" if remaining > DEFAULT_CRITICAL_USD else "critical"
    return APIKeyBalance(
        provider="OpenRouter",
        currency="USD",
        total_balance=remaining,
        is_available=True,
        status=status,
        updated_at=now_iso,
        details=c_data,
    )


def get_api_balances_live(cache_age_sec: float = 45.0, cache_dir: Optional[Path] = None) -> Dict[str, APIKeyBalance]:
    """Retrieve all active API key balances with caching."""
    import os
    root = cache_dir or (Path(__file__).resolve().parents[3] / "logs" / "token-stats")
    root.mkdir(parents=True, exist_ok=True)
    cache_file = root / "api_balance_cache.json"
    now = time.time()

    if cache_file.is_file():
        try:
            cached_doc = json.loads(cache_file.read_text(encoding="utf-8"))
            if now - cached_doc.get("timestamp", 0) < cache_age_sec:
                out: Dict[str, APIKeyBalance] = {}
                for k, v in cached_doc.get("data", {}).items():
                    out[k] = APIKeyBalance(**v)
                return out
        except Exception:
            pass

    # 1. First attempt to pull from Verse's cache if available
    verse_cache = Path("F:/verse/data/cache/api_balance_cache.json")
    if verse_cache.is_file():
        try:
            v_doc = json.loads(verse_cache.read_text(encoding="utf-8"))
            if now - v_doc.get("timestamp", 0) < cache_age_sec:
                out_v: Dict[str, APIKeyBalance] = {}
                for k, v in v_doc.get("data", {}).items():
                    out_v[k] = APIKeyBalance(
                        provider=v.get("provider", k),
                        currency=v.get("currency", "CNY"),
                        total_balance=float(v.get("total_balance", 0.0)),
                        is_available=bool(v.get("is_available", True)),
                        status=v.get("status", "healthy"),
                        error_message=v.get("error_message", ""),
                        updated_at=v.get("updated_at", ""),
                        details=v.get("details", {}),
                    )
                if out_v:
                    return out_v
        except Exception:
            pass

    # 2. Standalone discovery from environment and Verse presets
    keys: Dict[str, Dict[str, str]] = {}
    try:
        sys.path.insert(0, "F:/verse")
        from config.presets import PROVIDER_PRESETS
        for pname, pinfo in PROVIDER_PRESETS.items():
            k = pinfo.get("default_key", "")
            u = pinfo.get("base_url", "")
            if k and k.startswith("sk-"):
                keys[pname] = {"api_key": k, "base_url": u}
    except Exception:
        pass

    env_pairs = {
        "DeepSeek": (os.environ.get("DEEPSEEK_API_KEY", ""), os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")),
        "SiliconFlow": (os.environ.get("SILICONFLOW_API_KEY", ""), os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn")),
        "OpenRouter": (os.environ.get("OPENROUTER_API_KEY", ""), os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai")),
        "Grok": (os.environ.get("SUB2API_API_KEY", ""), os.environ.get("SUB2API_BASE_URL", "https://s2a.galiais.com/v1")),
    }
    for pname, (k, u) in env_pairs.items():
        if k:
            keys[pname] = {"api_key": k, "base_url": u}

    balances: Dict[str, APIKeyBalance] = {}
    for pname, pinfo in keys.items():
        k = pinfo["api_key"]
        u = pinfo["base_url"]
        b: Optional[APIKeyBalance] = None
        if pname == "DeepSeek":
            b = probe_deepseek_balance(k, u)
        elif pname == "SiliconFlow":
            b = probe_siliconflow_balance(k, u)
        elif pname == "OpenRouter":
            b = probe_openrouter_balance(k, u)
        else:
            b = APIKeyBalance(
                provider=pname,
                currency="CREDITS",
                total_balance=999.0,
                is_available=True,
                status="unmetered",
                updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )
        if b:
            balances[pname] = b

    try:
        payload = {
            "timestamp": now,
            "data": {k: v.to_dict() for k, v in balances.items()}
        }
        cache_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    return balances


def evaluate_api_balance_alert(
    balances: Mapping[str, APIKeyBalance],
    threshold_cny: float = DEFAULT_CRITICAL_CNY,
    threshold_usd: float = DEFAULT_CRITICAL_USD,
) -> APIBalanceAlert:
    """Evaluate whether any active API key balance is critically low."""
    crit_providers: List[str] = []
    messages: List[str] = []

    for pname, bal in balances.items():
        if not bal.is_available:
            crit_providers.append(pname)
            messages.append(f"{pname} is UNAVAILABLE ({bal.error_message or 'Account blocked or zero balance'})")
            continue

        if bal.status == "unmetered":
            continue

        threshold = threshold_usd if bal.currency == "USD" else threshold_cny
        if bal.total_balance <= threshold:
            crit_providers.append(pname)
            messages.append(f"{pname} balance is CRITICAL at {bal.total_balance:.2f} {bal.currency} (<= {threshold:.2f})")

    is_crit = len(crit_providers) > 0
    if is_crit:
        warn = f"[CRITICAL API KEY BALANCE ALERT] API Key balance near exhaustion: {'; '.join(messages)}. Action required: recharge or switch provider immediately."
        return APIBalanceAlert(
            is_critical=True,
            alert_level="CRITICAL",
            critical_providers=tuple(crit_providers),
            warning_message=warn,
            balances=balances,
        )

    return APIBalanceAlert(
        is_critical=False,
        alert_level="OK",
        critical_providers=(),
        warning_message="All API Key balances within normal operating range.",
        balances=balances,
    )


def format_api_balance_markdown(balances: Mapping[str, APIKeyBalance], alert: Optional[APIBalanceAlert] = None) -> str:
    """Format API balances for console and markdown logs (Zero Emoji compliant)."""
    if not balances:
        return "- API Key 余额: [未检测到外部计费密钥或已离线]"

    tokens: List[str] = []
    for pname, bal in balances.items():
        if bal.status == "unmetered":
            tokens.append(f"[{pname}] 免计费/专线")
        elif bal.status == "critical" or not bal.is_available:
            tokens.append(f"[{pname}] **{bal.total_balance:.2f} {bal.currency} (告急)**")
        else:
            tokens.append(f"[{pname}] {bal.total_balance:.2f} {bal.currency}")

    status_suffix = " · [WARN: 需及时充值]" if (alert and alert.is_critical) else " · (充足)"
    return "- API Key 余额: " + " · ".join(tokens) + status_suffix
