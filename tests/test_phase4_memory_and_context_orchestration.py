"""JHOC Phase 4 Comprehensive Acceptance Test Suite.

Verifies:
- C1: Tier naming (GOLDEN_INVARIANT vs L1/L2/L3)
- C2: Canonical distilled schema & <= 500 chars body ceiling
- C3: Exact-kind equivalence key dedup & token overlap tie-breaker
- C4: Contradiction resolution precedence (physical probe > newer UTC > record_id tiebreak; append-only SUPERSEDED)
- C5: RF-Mem entropy numerics (log-softmax, tau > 0, N=0 NO_MATCH, N=1 confidence floor, mass threshold K)
- C6: Deep Path bounds (max hops, max nodes, 4000 chars budget, deterministic reranking)
- C7: Verify-Before-Act 3-state probing & strict redaction of disproven resources
- C8: 4-tier reverse prompt loader layout & prompt cache discipline
- C9: 200-line index budget guard with hysteresis rollover to category sidecars
- C10: Cross-store atomicity & consistency verification
- C11: Rule 7 Zero-Emoji & pure ASCII purity across code and test artifacts

Strictly enforces Rule 7 (Zero-Emoji & Pure ASCII) and Rule 2 (Fail-Closed).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.memory_store.consolidator import (
    MemoryConsolidator,
    ConsolidationRecord,
    MemoryTier,
    KnowledgeKind,
    DistilledInvariantContent,
    MAX_INVARIANT_BODY_CHARS,
)
from jhoc.memory_store.entropy_router import (
    EntropyRouter,
    CandidateMatch,
    RoutingMode,
    DEFAULT_TAU,
)
from jhoc.context.reverse_loader import (
    ReversePromptLoader,
    PhysicalClaimVerifier,
    ProbeStatus,
    PromptTier,
)
from jhoc.memory_store.index_budget import (
    IndexBudgetGuard,
    MAX_INDEX_LINES,
    HYSTERESIS_TARGET_LINES,
)


class TestPhase4MemoryAndContextOrchestration(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()
        self.db_path = self.workspace / "test_memory.sqlite"
        self.catalog_path = self.workspace / "catalog.json"
        self.index_path = self.workspace / "MEMORY.md"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_c1_tier_naming_and_separation(self) -> None:
        """C1: Verifies clear separation between GOLDEN_INVARIANT and taxonomy L1/L2/L3."""
        self.assertEqual(MemoryTier.L1_HOT_CONTEXT.value, "L1_HOT_CONTEXT")
        self.assertEqual(MemoryTier.L2_DISTILLED_DOMAIN.value, "L2_DISTILLED_DOMAIN")
        self.assertEqual(MemoryTier.L3_COLD_ARCHIVE.value, "L3_COLD_ARCHIVE")
        self.assertEqual(MemoryTier.GOLDEN_INVARIANT.value, "GOLDEN_INVARIANT")
        self.assertNotEqual(MemoryTier.GOLDEN_INVARIANT.value, MemoryTier.L3_COLD_ARCHIVE.value)

    def test_c2_golden_invariant_schema_and_ceiling(self) -> None:
        """C2: Verifies shape-stable schema and strict <= 500 chars body constraint."""
        valid = DistilledInvariantContent(
            statement="Strictly use parameterized commands for process execution.",
            rationale="Eliminates shell injection vulnerabilities fail-closed.",
            boundary="All tools in src/jhoc/runner/ must enforce allow_shell=False.",
            evidence_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            source_ref="AGENTS.md:L30-L35",
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        valid.validate()
        d = valid.to_dict()
        self.assertIn("statement", d)
        self.assertIn("rationale", d)
        self.assertIn("boundary", d)

        # Body exceeding 500 chars fails closed
        invalid = DistilledInvariantContent(
            statement="A" * (MAX_INVARIANT_BODY_CHARS + 10),
            rationale="Valid rationale.",
            boundary="Valid boundary.",
            evidence_sha256="1234",
            source_ref="ref",
            recorded_at="2026-09-01T00:00:00Z",
        )
        with self.assertRaises(ContractError) as ctx:
            invalid.validate()
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_CONTRACT)

    def test_c3_dedup_gating_and_cluster_merge(self) -> None:
        """C3: Exact-kind equivalence key dedup and token overlap tie-breaker."""
        consolidator = MemoryConsolidator(self.db_path, self.workspace)
        r1 = ConsolidationRecord(
            record_id="rec-001",
            tier=MemoryTier.L2_DISTILLED_DOMAIN,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="Network & Proxy Routing",
            content={"statement": "Infinite Canvas proxy runs on localhost port 23210 strictly."},
            source_ref="docs/runbooks/proxy.md",
            sensitivity="INTERNAL",
            evidence_sha256="hash1",
            recorded_at="2026-09-01T10:00:00Z",
        )
        # Near duplicate with high token overlap (> 0.85)
        r2 = ConsolidationRecord(
            record_id="rec-002",
            tier=MemoryTier.L2_DISTILLED_DOMAIN,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="Network & Proxy Routing",
            content={"statement": "Infinite Canvas proxy runs on localhost port 23210 strictly."},
            source_ref="scripts/proxy.js",
            sensitivity="INTERNAL",
            evidence_sha256="hash2",
            recorded_at="2026-09-01T12:00:00Z",
        )

        res = consolidator.consolidate([r1, r2], self.catalog_path, self.index_path)
        self.assertEqual(res.total_processed, 2)
        self.assertEqual(res.deduplicated_count, 1)
        self.assertEqual(res.active_count, 1)

        # Ensure survivor inherited merged source refs
        survivor = consolidator._load_existing_records()[0]
        self.assertIn("docs/runbooks/proxy.md", survivor.source_ref)
        self.assertIn("scripts/proxy.js", survivor.source_ref)

    def test_c4_contradiction_resolution_precedence(self) -> None:
        """C4: Contradiction resolution: physical probe > newer UTC > record_id tiebreak."""
        consolidator = MemoryConsolidator(self.db_path, self.workspace)

        # Older setting
        r_old = ConsolidationRecord(
            record_id="rec-old",
            tier=MemoryTier.L2_DISTILLED_DOMAIN,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="Network & Proxy Routing",
            content={"target_key": "canvas_proxy_port", "value": 8080, "statement": "Proxy port is 8080"},
            source_ref="legacy_config.json",
            sensitivity="INTERNAL",
            evidence_sha256="old_sha",
            recorded_at="2026-09-01T10:00:00Z",
            status="ACTIVE",
        )
        # Newer setting
        r_new = ConsolidationRecord(
            record_id="rec-new",
            tier=MemoryTier.L2_DISTILLED_DOMAIN,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="Network & Proxy Routing",
            content={"target_key": "canvas_proxy_port", "value": 23210, "statement": "Proxy port is 23210"},
            source_ref="active_config.json",
            sensitivity="INTERNAL",
            evidence_sha256="new_sha",
            recorded_at="2026-09-02T10:00:00Z",
            status="ACTIVE",
        )

        res = consolidator.consolidate([r_old, r_new], self.catalog_path, self.index_path)
        self.assertEqual(res.contradictions_resolved, 1)
        self.assertEqual(res.superseded_count, 1)

        records = consolidator._load_existing_records()
        active = [r for r in records if r.status == "ACTIVE"][0]
        superseded = [r for r in records if r.status == "SUPERSEDED"][0]

        # Newer wins
        self.assertEqual(active.record_id, "rec-new")
        self.assertEqual(active.content["value"], 23210)
        # Loser marked SUPERSEDED with linkage, not deleted
        self.assertEqual(superseded.record_id, "rec-old")
        self.assertEqual(superseded.superseded_by, "rec-new")

    def test_c5_entropy_router_numerics_and_fast_path(self) -> None:
        """C5: Computes log-softmax, verifies tau > 0 guard, N=0, N=1, and Fast Path."""
        with self.assertRaises(ContractError):
            EntropyRouter(tau=0.0)

        router = EntropyRouter(tau=1.0)

        # N = 0
        d0 = router.route([])
        self.assertEqual(d0.mode, RoutingMode.NO_MATCH)
        self.assertEqual(d0.selected_k, 0)

        # N = 1 with high confidence
        c_high = CandidateMatch(record_id="c1", score=0.9, domain="Test", content="High confidence match")
        d1 = router.route([c_high])
        self.assertEqual(d1.mode, RoutingMode.FAST_PATH)
        self.assertEqual(d1.selected_k, 1)

        # N = 1 with low confidence
        c_low = CandidateMatch(record_id="c1", score=0.2, domain="Test", content="Low confidence match")
        d1_low = router.route([c_low])
        self.assertEqual(d1_low.mode, RoutingMode.DEEP_PATH)

        # Sharp distribution (Clear winner -> Low Entropy -> FAST_PATH)
        c_sharp = [
            CandidateMatch(record_id="c1", score=10.0, domain="Test", content="Clear dominant winner"),
            CandidateMatch(record_id="c2", score=1.0, domain="Test", content="Distant second"),
            CandidateMatch(record_id="c3", score=0.5, domain="Test", content="Distant third"),
        ]
        d_sharp = router.route(c_sharp)
        self.assertEqual(d_sharp.mode, RoutingMode.FAST_PATH)
        self.assertLessEqual(d_sharp.normalized_entropy, router.low_entropy_threshold)
        self.assertGreaterEqual(d_sharp.selected_k, 1)
        self.assertLessEqual(d_sharp.selected_k, 3)

    def test_c6_entropy_router_deep_path_and_bounds(self) -> None:
        """C6: High entropy triggers DEEP_PATH with hard bounds and deterministic reranking."""
        router = EntropyRouter(tau=1.0)

        # Uniform scores -> Maximum entropy
        c_uniform = [
            CandidateMatch(record_id=f"c{i}", score=5.0, domain="Test", content=f"Candidate {i} text")
            for i in range(5)
        ]
        decision = router.route(c_uniform, query="Candidate 3")
        self.assertEqual(decision.mode, RoutingMode.DEEP_PATH)
        self.assertGreater(decision.normalized_entropy, router.low_entropy_threshold)

        # Verify deterministic reranker placed query match first
        self.assertIn("Candidate 3", decision.selected_candidates[0].content)

    def test_c7_verify_before_act_probe_and_redaction(self) -> None:
        """C7: Physical claim verification: real file -> VERIFIED; missing -> STALE_MEMORY_DISPROVEN + REDACTED."""
        real_file = self.workspace / "real_file.py"
        real_file.write_text("# Production code\n", encoding="utf-8")
        missing_file = self.workspace / "phantom_ghost_file.py"

        verifier = PhysicalClaimVerifier(self.workspace)

        probe_real = verifier.probe_resource_claim("FILE", str(real_file))
        self.assertEqual(probe_real.status, ProbeStatus.VERIFIED)

        probe_missing = verifier.probe_resource_claim("FILE", str(missing_file))
        self.assertEqual(probe_missing.status, ProbeStatus.STALE_MEMORY_DISPROVEN)

        # Test text redaction
        input_text = (
            f"Please edit file:///{missing_file.as_posix()} to fix the port bug, "
            f"and check file:///{real_file.as_posix()} for reference."
        )
        redacted_text, probes = verifier.verify_and_redact_memory_text(input_text)

        # Missing path must be REDACTED
        self.assertNotIn(missing_file.as_posix(), redacted_text)
        self.assertIn("[REDACTED_DISPROVEN_RESOURCE:", redacted_text)

        # Real path must remain verbatim
        self.assertIn(real_file.as_posix(), redacted_text)

    def test_c8_reverse_loader_prompt_hierarchy_and_cache(self) -> None:
        """C8: 4-tier reverse hierarchy layout preserving Tier 1 prefix and Tier 4 generation frontier."""
        real_file = self.workspace / "entry.py"
        real_file.write_text("print('entry')", encoding="utf-8")

        loader = ReversePromptLoader(self.workspace)
        managed = "RULE 0: Anti-sycophancy. RULE 7: Zero emoji."
        user = "User is non-programmer; keep explanations plain."
        project = "JHOC microkernel harness with SQLite WAL."
        step_state = "Step 4 in progress: checking adapter."
        obs = "Exit code 0 from compiler."
        memories = [f"Reference architecture in file:///{real_file.as_posix()}"]

        prompt, probes = loader.build_prompt(
            managed_tier_text=managed,
            user_tier_text=user,
            project_tier_text=project,
            local_step_state=step_state,
            local_latest_observation=obs,
            retrieved_memories=memories,
        )

        # Check section ordering
        pos_t1 = prompt.find("=== [TIER-1: MANAGED GOVERNANCE (IMMUTABLE PREFIX)] ===")
        pos_t2 = prompt.find("=== [TIER-2: USER PROFILE & LONG-TERM PREFERENCES] ===")
        pos_t3 = prompt.find("=== [TIER-3: PROJECT TOPOLOGY & ARCHITECTURAL SPECS] ===")
        pos_t4 = prompt.find("=== [TIER-4: LOCAL TASK & ACTIVE GENERATION FRONTIER] ===")

        self.assertGreater(pos_t2, pos_t1)
        self.assertGreater(pos_t3, pos_t2)
        self.assertGreater(pos_t4, pos_t3)

        # Tier 4 contains step state and observation at the tail
        self.assertIn("[ACTIVE STEP STATE]", prompt)
        self.assertIn("[LATEST OBSERVATION]", prompt)
        self.assertIn("[RETRIEVED GROUNDED MEMORIES", prompt)

    def test_c9_index_budget_guard_and_hysteresis_rollover(self) -> None:
        """C9: Index budget guard: > 200 lines triggers rollover to category sidecar with hysteresis to <= 160 lines."""
        index_file = self.workspace / "MEMORY.md"
        archive_dir = self.workspace / "archive"

        # Construct an index with 220 lines across categories
        lines = ["# Root Memory Index", "", "## Active Golden Invariants", ""]
        for i in range(120):
            lines.append(f"- Invariant rule {i}: always verify before action (`inv-{i}`).")
        lines.extend(["", "## Active Domain Knowledge", ""])
        for j in range(100):
            lines.append(f"- Domain knowledge {j}: component routing table (`dom-{j}`).")

        index_file.write_text("\n".join(lines), encoding="utf-8")

        guard = IndexBudgetGuard()
        init_lines, init_bytes, is_over = guard.check_budget(index_file)
        self.assertTrue(is_over)
        self.assertGreater(init_lines, MAX_INDEX_LINES)

        res = guard.enforce_index_budget(index_file, archive_dir)
        self.assertTrue(res.rollover_triggered)
        self.assertGreater(res.archived_entries_count, 0)
        self.assertLessEqual(res.settled_line_count, HYSTERESIS_TARGET_LINES)
        self.assertTrue(res.integrity_verified)

        # Verify archive sidecars exist and root index links to them
        self.assertGreater(len(res.archive_sidecars_created), 0)
        settled_text = index_file.read_text(encoding="utf-8")
        self.assertIn("[Archive", settled_text)
        self.assertTrue(guard._verify_pointer_integrity(index_file))

    def test_c10_cross_store_atomicity_and_verification(self) -> None:
        """C10: Single source of truth in SQLite, derived catalog and index generated atomically."""
        consolidator = MemoryConsolidator(self.db_path, self.workspace)
        records = [
            ConsolidationRecord(
                record_id=f"atom-{i}",
                tier=MemoryTier.L2_DISTILLED_DOMAIN,
                kind=KnowledgeKind.PROPOSITIONAL,
                domain="Architecture & Infrastructure",
                content={"statement": f"Atomic invariant specification number {i} covering distinct subsystem {i}."},
                source_ref=f"test_source_{i}.py",
                sensitivity="INTERNAL",
                evidence_sha256=f"hash_{i}",
                recorded_at=f"2026-09-01T0{i}:00:00Z",
            )
            for i in range(5)
        ]

        res = consolidator.consolidate(records, self.catalog_path, self.index_path)
        self.assertTrue(res.consistency_verified)
        self.assertTrue(self.catalog_path.is_file())
        self.assertTrue(self.index_path.is_file())

        cat_data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(cat_data["total_records"], 5)

    def test_c4_disproven_is_dominant_loser_even_if_newer(self) -> None:
        """C4 probe: Disproven-but-newer memory must lose to unverified older memory."""
        consolidator = MemoryConsolidator(self.db_path, self.workspace)
        r_older_unverified = ConsolidationRecord(
            record_id="rec-old-unverified",
            tier=MemoryTier.L2_DISTILLED_DOMAIN,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="Network & Proxy Routing",
            content={"target_key": "proxy_port", "value": 23210, "statement": "Port is 23210"},
            source_ref="config.json",
            sensitivity="INTERNAL",
            evidence_sha256="sha_old",
            recorded_at="2026-09-01T00:00:00Z",
        )
        r_newer_disproven = ConsolidationRecord(
            record_id="rec-new-disproven",
            tier=MemoryTier.L2_DISTILLED_DOMAIN,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="Network & Proxy Routing",
            content={
                "target_key": "proxy_port",
                "value": 9999,
                "statement": "Port is 9999",
                "probe_status": "STALE_MEMORY_DISPROVEN",
            },
            source_ref="disproven_config.json",
            sensitivity="INTERNAL",
            evidence_sha256="sha_new",
            recorded_at="2026-09-02T00:00:00Z",
        )

        res = consolidator.consolidate([r_older_unverified, r_newer_disproven], self.catalog_path, self.index_path)
        records = consolidator._load_existing_records()
        active = [r for r in records if r.status == "ACTIVE"][0]
        superseded = [r for r in records if r.status == "SUPERSEDED"][0]

        # The unverified older record MUST WIN because the newer one was disproven!
        self.assertEqual(active.record_id, "rec-old-unverified")
        self.assertEqual(superseded.record_id, "rec-new-disproven")

    def test_c6_deep_path_cumulative_char_budget_enforced(self) -> None:
        """C6 probe: Deep Path selection must not exceed 4000 characters aggregate."""
        router = EntropyRouter(tau=1.0)
        # 5 candidates each with 900 chars (total 4500 chars)
        candidates = [
            CandidateMatch(record_id=f"c{i}", score=5.0, domain="Test", content="X" * 900)
            for i in range(5)
        ]
        decision = router.route(candidates, query="X")
        self.assertEqual(decision.mode, RoutingMode.DEEP_PATH)
        total_chars = sum(len(c.content) for c in decision.selected_candidates)
        self.assertLessEqual(total_chars, 4000)

    def test_c7_redaction_does_not_corrupt_verified_prefix_literal(self) -> None:
        """C7 probe: Redacting disproven file must not corrupt verified file that shares prefix."""
        verifier = PhysicalClaimVerifier(self.workspace)
        dir_a = self.workspace / "dirA"
        dir_a.mkdir(parents=True, exist_ok=True)
        file_x = dir_a / "fileX.py"
        file_x.write_text("# verified\n", encoding="utf-8")
        disproven_file = dir_a / "file"  # does not exist

        input_text = f"edit file:///{disproven_file.as_posix()} then read file:///{file_x.as_posix()}"
        redacted_text, probes = verifier.verify_and_redact_memory_text(input_text)

        # Verified literal must remain 100% verbatim and intact
        self.assertIn(file_x.as_posix(), redacted_text)
        # Disproven literal must be replaced by redacted token in the edit statement
        self.assertIn("edit file:///[REDACTED_DISPROVEN_RESOURCE:", redacted_text)
        self.assertNotIn(f"edit file:///{disproven_file.as_posix()} ", redacted_text)

    def test_c9_low_line_high_byte_budget_enforced(self) -> None:
        """C9 probe: Over-budget index with few lines (9 lines, 30KB) must settle <= 20KB."""
        index_file = self.workspace / "OVERSIZED_MEMORY.md"
        # 9 lines, 5 of which are 6000 chars each (~30,000 bytes)
        lines = ["# Root Memory Index", "", "## Active Domain Knowledge", ""]
        for i in range(5):
            lines.append(f"- Domain item {i}: " + ("A" * 6000))

        index_file.write_text("\n".join(lines), encoding="utf-8")
        guard = IndexBudgetGuard()
        res = guard.enforce_index_budget(index_file, self.workspace / "archive")

        self.assertTrue(res.rollover_triggered)
        self.assertLessEqual(res.settled_byte_count, guard.target_bytes)
        self.assertLessEqual(res.settled_line_count, guard.target_lines)

    def test_c6_adversarial_oversized_candidate_sliced(self) -> None:
        """C6 probe: An adversarial 18,000-char candidate must be sliced to <= 4,000 chars."""
        router = EntropyRouter(tau=1.0)
        oversized = CandidateMatch(
            record_id="oversized-1",
            score=10.0,
            domain="Architecture",
            content="Z" * 18000,
        )
        decision = router.route([oversized], query="Z")
        self.assertEqual(len(decision.selected_candidates), 1)
        total_chars = sum(len(c.content) for c in decision.selected_candidates)
        self.assertLessEqual(total_chars, 4000)
        self.assertEqual(len(decision.selected_candidates[0].content), 4000)

    def test_retriever_adaptive_functional_coverage(self) -> None:
        """Functional coverage: Exercises MemoryRetriever.retrieve_adaptive with entropy routing."""
        from jhoc.memory_store.retriever import MemoryRetriever
        catalog_file = self.workspace / "test_catalog.json"
        catalog_payload = {
            "records": [
                {
                    "record_id": "test-net-01",
                    "domain": "Network & Proxy Routing",
                    "title": "Proxy routing architecture",
                    "abstract": "Configures proxy on localhost port 23210",
                    "status": "ACTIVE",
                }
            ]
        }
        catalog_file.write_text(json.dumps(catalog_payload), encoding="utf-8")
        retriever = MemoryRetriever(self.db_path, catalog_file)
        decision = retriever.retrieve_adaptive("proxy network routing")
        self.assertIn(decision.mode, (RoutingMode.FAST_PATH, RoutingMode.DEEP_PATH))
        self.assertEqual(decision.selected_k, 1)
        self.assertEqual(decision.selected_candidates[0].record_id, "test-net-01")

    def test_c11_rule7_pure_ascii_and_zero_emoji(self) -> None:
        """C11: Strict Rule 7 pure ASCII and zero emoji verification across Phase 4 source code."""
        phase4_files = [
            Path("src/jhoc/memory_store/consolidator.py"),
            Path("src/jhoc/memory_store/entropy_router.py"),
            Path("src/jhoc/memory_store/index_budget.py"),
            Path("src/jhoc/memory_store/retriever.py"),
            Path("src/jhoc/context/reverse_loader.py"),
            Path("src/jhoc/context/sanitizer.py"),
            Path(__file__),
        ]

        for rel_path in phase4_files:
            abs_path = (Path(__file__).resolve().parent.parent / rel_path).resolve()
            if not abs_path.is_file():
                continue
            content = abs_path.read_bytes()
            for idx, byte_val in enumerate(content):
                if byte_val > 127:
                    line_num = content[:idx].count(b"\n") + 1
                    self.fail(
                        f"Non-ASCII byte 0x{byte_val:02x} detected in {rel_path} at line {line_num} (Rule 7 violation)"
                    )


    def test_cond1_golden_invariant_total_ceiling_620(self) -> None:
        """COND-1 (C2): Total ceiling <= 620 enforced by DistilledInvariantContent and consolidate()."""
        consolidator = MemoryConsolidator(self.db_path, self.workspace)
        over_content = DistilledInvariantContent(
            statement="B" * 450,
            rationale="C" * 100,
            boundary="D" * 100,
            evidence_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            source_ref="AGENTS.md:L1-L10",
            recorded_at="2026-09-01T00:00:00Z",
        )
        serialized = json.dumps(over_content.to_dict(), ensure_ascii=True)
        self.assertGreater(len(serialized), 620)
        with self.assertRaises(ContractError) as ctx:
            over_content.validate()
        self.assertIn("620", str(ctx.exception))

        r_over = ConsolidationRecord(
            record_id="rec-over-620",
            tier=MemoryTier.GOLDEN_INVARIANT,
            kind=KnowledgeKind.PRESCRIPTIVE,
            domain="Architecture",
            content=over_content.to_dict(),
            source_ref="AGENTS.md",
            sensitivity="INTERNAL",
            evidence_sha256="hash_over",
            recorded_at="2026-09-01T00:00:00Z",
        )
        with self.assertRaises(ContractError) as ctx:
            consolidator.consolidate([r_over], self.catalog_path, self.index_path)
        self.assertIn("620", str(ctx.exception))

    def test_cond2_verified_memory_dominant_over_unverified_newer(self) -> None:
        """COND-2 (C4): Older VERIFIED record must not be displaced by newer UNVERIFIED record."""
        consolidator = MemoryConsolidator(self.db_path, self.workspace)
        r_older_verified = ConsolidationRecord(
            record_id="rec-old-verified",
            tier=MemoryTier.L2_DISTILLED_DOMAIN,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="Network & Proxy Routing",
            content={
                "target_key": "canvas_proxy_port",
                "value": 8080,
                "statement": "Proxy port is 8080",
                "probe_status": "VERIFIED",
            },
            source_ref="verified_config.json",
            sensitivity="INTERNAL",
            evidence_sha256="sha_verified",
            recorded_at="2026-09-01T00:00:00Z",
        )
        r_newer_unverified = ConsolidationRecord(
            record_id="rec-new-unverified",
            tier=MemoryTier.L2_DISTILLED_DOMAIN,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="Network & Proxy Routing",
            content={
                "target_key": "canvas_proxy_port",
                "value": 23210,
                "statement": "Proxy port is 23210",
                "probe_status": "UNVERIFIED",
            },
            source_ref="unverified_config.json",
            sensitivity="INTERNAL",
            evidence_sha256="sha_unverified_distinct",
            recorded_at="2026-09-02T00:00:00Z",
        )
        res = consolidator.consolidate([r_older_verified, r_newer_unverified], self.catalog_path, self.index_path)
        records = consolidator._load_existing_records()
        active = [r for r in records if r.status == "ACTIVE"][0]
        superseded = [r for r in records if r.status == "SUPERSEDED"][0]

        self.assertEqual(active.record_id, "rec-old-verified")
        self.assertEqual(superseded.record_id, "rec-new-unverified")

    def test_cond3_space_in_path_and_extensionless_relative_redaction(self) -> None:
        """COND-3 (C7): Quoted path with spaces, relative extensionless paths, and external file redaction."""
        verifier = PhysicalClaimVerifier(self.workspace)
        external_file = self.workspace.parent / "external_temp_file_c7.txt"
        external_file.write_text("external data\n", encoding="utf-8")
        try:
            input_text = (
                f'Inspect "file:///C:/Users/fake/my folder/ghost file.py" '
                f'and external "file:///{external_file.as_posix()}" '
                f'and refer to "nonexistent/config/settings" for parameters.'
            )
            redacted_text, probes = verifier.verify_and_redact_memory_text(input_text)
            self.assertNotIn("ghost file.py", redacted_text)
            self.assertNotIn("config/settings", redacted_text)
            self.assertNotIn(external_file.as_posix(), redacted_text)
            self.assertIn("[REDACTED_DISPROVEN_RESOURCE:", redacted_text)
            self.assertIn("[REDACTED_CHANGED_OR_EXTERNAL_RESOURCE]", redacted_text)
            self.assertEqual(len(probes), 3)
            statuses = {p.status for p in probes}
            self.assertIn(ProbeStatus.STALE_MEMORY_DISPROVEN, statuses)
            self.assertIn(ProbeStatus.STALE_MEMORY_CHANGED, statuses)
        finally:
            if external_file.is_file():
                external_file.unlink(missing_ok=True)

    def test_cond4_many_moderate_sections_overflow_archived(self) -> None:
        """COND-4 (C9): Over-budget index with many moderate sections archives dropped entries to sidecar."""
        index_file = self.workspace / "MODERATE_SECTIONS_INDEX.md"
        lines = ["# Moderate Sections Index", ""]
        for s in range(12):
            lines.append(f"## Section {s}")
            lines.append("")
            for it in range(18):
                lines.append(f"- Section {s} item {it}: description of entry")
            lines.append("")

        index_file.write_text("\n".join(lines), encoding="utf-8")
        guard = IndexBudgetGuard()
        res = guard.enforce_index_budget(index_file, self.workspace / "archive")

        self.assertTrue(res.rollover_triggered)
        self.assertGreater(len(res.archive_sidecars_created), 0)
        self.assertGreater(res.archived_entries_count, 0)
        self.assertLessEqual(res.settled_line_count, 160)
        self.assertTrue(res.integrity_verified)

    def test_cond4_byte_overflow_archives_dropped_entries(self) -> None:
        """COND-4 (C9): Byte-aware pass archives all dropped entries so zero items are lost."""
        index_file = self.workspace / "BYTE_OVERFLOW_INDEX.md"
        lines = ["# Byte Overflow Test Index", "", "## Section A", ""]
        initial_items = 133
        for i in range(initial_items):
            lines.append(f"- Item {i:03d}: " + ("K" * 180))
        lines.append("")

        index_file.write_text("\n".join(lines), encoding="utf-8")
        guard = IndexBudgetGuard()
        res = guard.enforce_index_budget(index_file, self.workspace / "archive")

        self.assertTrue(res.rollover_triggered)
        self.assertGreater(len(res.archive_sidecars_created), 0)
        self.assertGreater(res.archived_entries_count, 0)
        self.assertLessEqual(res.settled_byte_count, 20000)

        settled_lines = index_file.read_text(encoding="utf-8").splitlines()
        remaining_items = len([l for l in settled_lines if l.strip().startswith("- Item")])
        self.assertEqual(res.archived_entries_count + remaining_items, initial_items)
        self.assertTrue(res.integrity_verified)

    def test_cond5_rollback_on_artifact_failure_and_consistency(self) -> None:
        """COND-5 (C10): Rollback on catalog/index failure restores SQLite and derived artifacts."""
        from unittest.mock import patch
        consolidator = MemoryConsolidator(self.db_path, self.workspace)

        r0 = ConsolidationRecord(
            record_id="rec-initial-0",
            tier=MemoryTier.L1_HOT_CONTEXT,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="Baseline",
            content={"statement": "Initial baseline entry"},
            source_ref="baseline.md",
            sensitivity="INTERNAL",
            evidence_sha256="sha_base",
            recorded_at="2026-09-01T00:00:00Z",
        )
        consolidator.consolidate([r0], self.catalog_path, self.index_path)
        initial_catalog_bytes = self.catalog_path.read_bytes()

        r1 = ConsolidationRecord(
            record_id="rec-atomicity-fail-1",
            tier=MemoryTier.L1_HOT_CONTEXT,
            kind=KnowledgeKind.PROPOSITIONAL,
            domain="State",
            content={"statement": "Must not remain in SQLite if index write fails"},
            source_ref="state.md",
            sensitivity="INTERNAL",
            evidence_sha256="sha_atomic",
            recorded_at="2026-09-01T00:00:00Z",
        )

        with patch.object(consolidator, "_regenerate_index", side_effect=OSError("Index write failed")):
            with self.assertRaises(OSError):
                consolidator.consolidate([r0, r1], self.catalog_path, self.index_path)

        records = consolidator._load_existing_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_id, "rec-initial-0")

        self.assertEqual(self.catalog_path.read_bytes(), initial_catalog_bytes)
        cat_data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        cat_ids = [r["record_id"] for r in cat_data["records"]]
        self.assertEqual(cat_ids, ["rec-initial-0"])

    def test_c6_deep_path_graph_neighbors_fn_branch(self) -> None:
        """C6: Exercises BFS graph_neighbors_fn expansion with hops and frontier bounds."""
        router = EntropyRouter(tau=1.0)
        candidates = [
            CandidateMatch(record_id=f"node_{i}", score=1.0, domain="Test", content=f"Root node {i}")
            for i in range(3)
        ]

        def mock_graph_neighbors(node_id: str) -> list[CandidateMatch]:
            return [
                CandidateMatch(
                    record_id=f"{node_id}_child_{i}",
                    score=0.8,
                    domain="Test",
                    content=f"Child {i} of {node_id}",
                )
                for i in range(3)
            ]

        decision = router.route(candidates, query="Root", graph_neighbors_fn=mock_graph_neighbors)
        self.assertEqual(decision.mode, RoutingMode.DEEP_PATH)
        self.assertGreater(len(decision.selected_candidates), 3)
        self.assertLessEqual(len(decision.selected_candidates), 15)
        ids = [c.record_id for c in decision.selected_candidates]
        self.assertEqual(len(ids), len(set(ids)))


    def test_warn2_port_redaction_non_revealing(self) -> None:
        """WARN-2 (C7): Closed port probe must not leak raw port number into prompt."""
        verifier = PhysicalClaimVerifier(self.workspace)
        input_text = "Ensure connection to port 59999 is established."
        redacted_text, probes = verifier.verify_and_redact_memory_text(input_text)
        self.assertNotIn("59999", redacted_text)
        self.assertIn("[REDACTED_DISPROVEN_RESOURCE: Port is closed or not listening]", redacted_text)
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0].status, ProbeStatus.STALE_MEMORY_DISPROVEN)

    def test_warn3_json_catalog_guard(self) -> None:
        """WARN-3 (C9): enforce_index_budget refuses to mangle JSON files over 500KB cap."""
        json_file = self.workspace / "oversized_catalog.json"
        # Create valid JSON file > 500KB
        payload = {"records": [{"id": f"rec_{i}", "data": "X" * 1000} for i in range(550)]}
        json_file.write_text(json.dumps(payload), encoding="utf-8")
        self.assertGreater(json_file.stat().st_size, 500000)

        guard = IndexBudgetGuard()
        with self.assertRaises(ContractError) as ctx:
            guard.enforce_index_budget(json_file)
        self.assertIn("JSON", str(ctx.exception))
        # Ensure file was not destroyed and is still valid JSON
        re_read = json.loads(json_file.read_text(encoding="utf-8"))
        self.assertEqual(len(re_read["records"]), 550)


if __name__ == "__main__":
    unittest.main()
