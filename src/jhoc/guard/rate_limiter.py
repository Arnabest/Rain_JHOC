"""JHOC Egress Domain Rate Limiter - Protects external APIs from concurrency quota exhaustion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import time
from typing import Mapping


@dataclass
class DomainBucket:
    rate_limit_per_sec: float
    min_interval: float
    last_request_time: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def acquire(self, timeout: float = 5.0) -> bool:
        start = time.monotonic()
        with self.lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_request_time
                if elapsed >= self.min_interval:
                    self.last_request_time = now
                    return True
                wait_time = self.min_interval - elapsed
                if (time.monotonic() - start) + wait_time > timeout:
                    return False
                time.sleep(min(wait_time, 0.05))


class GlobalEgressRateLimiter:
    """Centralized rate limiter coordinating outbound requests across all skills/subagents."""

    # Default rate limits (requests per second) for major public data providers
    DEFAULT_DOMAIN_LIMITS: Mapping[str, float] = {
        "ncbi.nlm.nih.gov": 3.0,
        "api.ncbi.nlm.nih.gov": 3.0,
        "pubchem.ncbi.nlm.nih.gov": 3.0,
        "ebi.ac.uk": 5.0,
        "www.ebi.ac.uk": 5.0,
        "arxiv.org": 2.0,
        "export.arxiv.org": 2.0,
        "europepmc.org": 5.0,
        "uniprot.org": 5.0,
        "default": 10.0,
    }

    def __init__(self, custom_limits: Mapping[str, float] | None = None) -> None:
        self._limits: dict[str, float] = dict(self.DEFAULT_DOMAIN_LIMITS)
        if custom_limits:
            self._limits.update(custom_limits)
        self._buckets: dict[str, DomainBucket] = {}
        self._lock = threading.Lock()

    def _get_bucket(self, domain: str) -> DomainBucket:
        norm_domain = domain.lower().strip()
        with self._lock:
            if norm_domain not in self._buckets:
                rate = self._limits.get(norm_domain, self._limits.get("default", 10.0))
                min_interval = 1.0 / max(rate, 0.1)
                self._buckets[norm_domain] = DomainBucket(rate_limit_per_sec=rate, min_interval=min_interval)
            return self._buckets[norm_domain]

    def acquire(self, domain: str, timeout: float = 5.0) -> bool:
        """Acquires a transmission slot for the given domain. Returns True if granted, False if timed out."""
        bucket = self._get_bucket(domain)
        return bucket.acquire(timeout=timeout)


# Global singleton instance for system-wide reuse
egress_limiter = GlobalEgressRateLimiter()
