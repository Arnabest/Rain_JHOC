"""JHOC RF-Mem Shannon Entropy Dynamic Routing Engine.

Computes log-softmax normalized Shannon entropy over retrieval scores:
- C5: Stable log-softmax numerics (max-subtraction, logsumexp), tau > 0 guard,
      NaN/Inf input rejection, deterministic stable-sorting, N=0 NO_MATCH,
      N=1 confidence floor (t_conf >= 0.5), cumulative softmax mass K selection (>= 0.8, min 1, cap 3).
- C6: Deep Path hard bounds: max 2 hops, max 5 frontier/hop, max 15 nodes, max 3 expansion terms,
      max 10 rerank candidates, aggregate byte budget <= 4000 chars, monotonic visited set,
      deterministic local keyword-coverage reranker.

Enforces Rule 7 (Zero-Emoji & Pure ASCII) and Rule 2 (Fail-Closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
import re
from typing import Any, Mapping, Sequence

from jhoc.contracts.errors import ContractError, ErrorCode


DEFAULT_TAU: float = 1.0
LOW_ENTROPY_THRESHOLD: float = 0.35
CONFIDENCE_FLOOR_N1: float = 0.5
MASS_THRESHOLD_FAST_PATH: float = 0.8
MAX_FAST_PATH_K: int = 3
MAX_DEEP_HOPS: int = 2
MAX_FRONTIER_PER_HOP: int = 5
MAX_TOTAL_NODES: int = 15
MAX_EXPANSION_TERMS: int = 3
MAX_RERANK_CANDIDATES: int = 10
MAX_DEEP_EXPANDED_CHARS: int = 4000


class RoutingMode(StrEnum):
    NO_MATCH = "NO_MATCH"
    FAST_PATH = "FAST_PATH"
    DEEP_PATH = "DEEP_PATH"


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    record_id: str
    score: float
    domain: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    mode: RoutingMode
    normalized_entropy: float
    raw_entropy: float
    selected_k: int
    selected_candidates: tuple[CandidateMatch, ...]
    probabilities: tuple[float, ...]
    log_probabilities: tuple[float, ...]
    audit_notes: str


class EntropyRouter:
    """Calculates log-softmax Shannon entropy to gate between Fast Path and Deep Path."""

    def __init__(
        self,
        tau: float = DEFAULT_TAU,
        low_entropy_threshold: float = LOW_ENTROPY_THRESHOLD,
        confidence_floor_n1: float = CONFIDENCE_FLOOR_N1,
    ) -> None:
        if tau <= 0.0:
            raise ContractError(f"Temperature tau must be strictly positive: {tau}", ErrorCode.INVALID_CONTRACT)
        self.tau = tau
        self.low_entropy_threshold = low_entropy_threshold
        self.confidence_floor_n1 = confidence_floor_n1

    def compute_log_softmax_and_entropy(
        self,
        candidates: Sequence[CandidateMatch],
    ) -> tuple[list[float], list[float], float, float]:
        """Returns (probabilities, log_probabilities, raw_entropy, normalized_entropy)."""
        n = len(candidates)
        if n == 0:
            return [], [], 0.0, 0.0

        scores = [c.score for c in candidates]
        # Validate scores fail-closed against NaN/Inf
        for s in scores:
            if math.isnan(s) or math.isinf(s):
                raise ContractError(f"Invalid score encountered: {s}", ErrorCode.POLICY_DENIED)

        if n == 1:
            return [1.0], [0.0], 0.0, 0.0

        max_score = max(scores)
        scaled = [(s - max_score) / self.tau for s in scores]

        # LogSumExp
        sum_exp = sum(math.exp(val) for val in scaled)
        logsumexp = math.log(sum_exp)

        log_probs = [val - logsumexp for val in scaled]
        probs = [math.exp(lp) for lp in log_probs]

        # Shannon entropy H(p) = - sum p_i * log2(p_i)
        # using log_probs directly: log2(p_i) = lp / ln(2)
        ln2 = math.log(2.0)
        raw_entropy = 0.0
        for p, lp in zip(probs, log_probs):
            if p > 1e-15:
                raw_entropy -= p * (lp / ln2)

        max_entropy = math.log2(n)
        normalized_entropy = (raw_entropy / max_entropy) if max_entropy > 0 else 0.0
        # Clamp bounds
        normalized_entropy = max(0.0, min(1.0, normalized_entropy))

        return probs, log_probs, raw_entropy, normalized_entropy

    def route(
        self,
        candidates: Sequence[CandidateMatch],
        query: str = "",
        graph_neighbors_fn: Any = None,
    ) -> RoutingDecision:
        """Dynamically routes candidates based on Shannon entropy distribution."""
        if not candidates:
            return RoutingDecision(
                mode=RoutingMode.NO_MATCH,
                normalized_entropy=0.0,
                raw_entropy=0.0,
                selected_k=0,
                selected_candidates=(),
                probabilities=(),
                log_probabilities=(),
                audit_notes="Empty candidate set; returned NO_MATCH",
            )

        # Stable-sort: score descending, then record_id ascending
        sorted_candidates = sorted(candidates, key=lambda c: (-c.score, c.record_id))

        probs, log_probs, raw_entropy, norm_entropy = self.compute_log_softmax_and_entropy(sorted_candidates)
        n = len(sorted_candidates)

        # Single candidate case
        if n == 1:
            top = sorted_candidates[0]
            if len(top.content) > MAX_DEEP_EXPANDED_CHARS:
                top = CandidateMatch(
                    record_id=top.record_id,
                    score=top.score,
                    domain=top.domain,
                    content=top.content[:MAX_DEEP_EXPANDED_CHARS],
                    metadata=top.metadata,
                )
            if top.score >= self.confidence_floor_n1:
                return RoutingDecision(
                    mode=RoutingMode.FAST_PATH,
                    normalized_entropy=0.0,
                    raw_entropy=0.0,
                    selected_k=1,
                    selected_candidates=(top,),
                    probabilities=tuple(probs),
                    log_probabilities=tuple(log_probs),
                    audit_notes=f"Single match above confidence floor ({top.score:.2f} >= {self.confidence_floor_n1:.2f})",
                )
            else:
                return RoutingDecision(
                    mode=RoutingMode.DEEP_PATH,
                    normalized_entropy=0.0,
                    raw_entropy=0.0,
                    selected_k=1,
                    selected_candidates=(top,),
                    probabilities=tuple(probs),
                    log_probabilities=tuple(log_probs),
                    audit_notes=f"Single match below confidence floor ({top.score:.2f} < {self.confidence_floor_n1:.2f}); routing to DEEP_PATH",
                )

        # C5: Decision on normalized entropy
        if norm_entropy <= self.low_entropy_threshold:
            # FAST_PATH: Determine K by cumulative softmax mass >= 0.8
            cumulative_mass = 0.0
            k = 0
            for i, p in enumerate(probs):
                cumulative_mass += p
                k += 1
                if cumulative_mass >= MASS_THRESHOLD_FAST_PATH or k >= MAX_FAST_PATH_K:
                    break
            k = max(1, min(k, MAX_FAST_PATH_K))
            bounded_selected: list[CandidateMatch] = []
            accum_chars = 0
            for cand in sorted_candidates[:k]:
                if accum_chars + len(cand.content) <= MAX_DEEP_EXPANDED_CHARS:
                    bounded_selected.append(cand)
                    accum_chars += len(cand.content)
                elif not bounded_selected:
                    bounded_selected.append(
                        CandidateMatch(
                            record_id=cand.record_id,
                            score=cand.score,
                            domain=cand.domain,
                            content=cand.content[:MAX_DEEP_EXPANDED_CHARS],
                            metadata=cand.metadata,
                        )
                    )
                    break
                else:
                    break
            selected = tuple(bounded_selected)
            return RoutingDecision(
                mode=RoutingMode.FAST_PATH,
                normalized_entropy=norm_entropy,
                raw_entropy=raw_entropy,
                selected_k=len(selected),
                selected_candidates=selected,
                probabilities=tuple(probs),
                log_probabilities=tuple(log_probs),
                audit_notes=f"Low entropy ({norm_entropy:.3f} <= {self.low_entropy_threshold:.3f}); Fast Path selected top-{len(selected)} (mass {cumulative_mass:.2f})",
            )
        else:
            # DEEP_PATH: Perform bounded multi-hop expansion and deterministic local reranking
            deep_selected = self._expand_and_rerank_deep(
                query=query,
                initial_candidates=sorted_candidates,
                graph_neighbors_fn=graph_neighbors_fn,
            )
            return RoutingDecision(
                mode=RoutingMode.DEEP_PATH,
                normalized_entropy=norm_entropy,
                raw_entropy=raw_entropy,
                selected_k=len(deep_selected),
                selected_candidates=tuple(deep_selected),
                probabilities=tuple(probs),
                log_probabilities=tuple(log_probs),
                audit_notes=f"High entropy ({norm_entropy:.3f} > {self.low_entropy_threshold:.3f}); Deep Path expanded to {len(deep_selected)} nodes",
            )

    def _expand_and_rerank_deep(
        self,
        query: str,
        initial_candidates: list[CandidateMatch],
        graph_neighbors_fn: Any = None,
    ) -> list[CandidateMatch]:
        """C6: Executes bounded graph neighborhood expansion and deterministic local reranking."""
        visited_ids: set[str] = set()
        pool: list[CandidateMatch] = []
        total_chars = 0

        # Add initial candidates up to MAX_RERANK_CANDIDATES with char accounting
        for cand in initial_candidates[:MAX_RERANK_CANDIDATES]:
            if cand.record_id not in visited_ids:
                cand_len = len(cand.content)
                if total_chars + cand_len > MAX_DEEP_EXPANDED_CHARS:
                    if pool:
                        break
                    # If first candidate alone exceeds cap, slice to cap
                    cand = CandidateMatch(
                        record_id=cand.record_id,
                        score=cand.score,
                        domain=cand.domain,
                        content=cand.content[:MAX_DEEP_EXPANDED_CHARS],
                        metadata=cand.metadata,
                    )
                    cand_len = len(cand.content)
                visited_ids.add(cand.record_id)
                pool.append(cand)
                total_chars += cand_len

        # If graph_neighbors_fn is provided, perform bounded 2-hop BFS
        if graph_neighbors_fn and callable(graph_neighbors_fn):
            current_frontier = [c.record_id for c in pool[:MAX_FRONTIER_PER_HOP]]
            for hop in range(MAX_DEEP_HOPS):
                if not current_frontier or len(pool) >= MAX_TOTAL_NODES or total_chars >= MAX_DEEP_EXPANDED_CHARS:
                    break
                next_frontier: list[str] = []
                for node_id in current_frontier:
                    if len(pool) >= MAX_TOTAL_NODES or total_chars >= MAX_DEEP_EXPANDED_CHARS:
                        break
                    try:
                        neighbors = graph_neighbors_fn(node_id) or []
                        for n in neighbors[:MAX_FRONTIER_PER_HOP]:
                            if isinstance(n, CandidateMatch) and n.record_id not in visited_ids:
                                if len(pool) >= MAX_TOTAL_NODES or total_chars + len(n.content) > MAX_DEEP_EXPANDED_CHARS:
                                    break
                                visited_ids.add(n.record_id)
                                pool.append(n)
                                total_chars += len(n.content)
                                next_frontier.append(n.record_id)
                    except Exception:
                        continue
                current_frontier = next_frontier

        # Local deterministic keyword-coverage reranking bounded by MAX_EXPANSION_TERMS
        query_terms = set(re.findall(r"\w+", query.lower())[:MAX_EXPANSION_TERMS]) if query else set()

        def _local_score(cand: CandidateMatch) -> tuple[float, float, str]:
            text = cand.content.lower()
            tokens = set(re.findall(r"\w+", text))
            overlap = len(query_terms.intersection(tokens)) if query_terms else 0
            # Higher overlap, then original score, then record_id
            return (float(overlap), cand.score, cand.record_id)

        reranked = sorted(pool, key=_local_score, reverse=True)
        budgeted_result: list[CandidateMatch] = []
        accum_chars = 0
        for cand in reranked[:MAX_RERANK_CANDIDATES]:
            if accum_chars + len(cand.content) <= MAX_DEEP_EXPANDED_CHARS:
                budgeted_result.append(cand)
                accum_chars += len(cand.content)
            elif not budgeted_result:
                # Sliced to strictly guarantee aggregate <= MAX_DEEP_EXPANDED_CHARS
                sliced_cand = CandidateMatch(
                    record_id=cand.record_id,
                    score=cand.score,
                    domain=cand.domain,
                    content=cand.content[:MAX_DEEP_EXPANDED_CHARS],
                    metadata=cand.metadata,
                )
                budgeted_result.append(sliced_cand)
                break
            else:
                break
        return budgeted_result
