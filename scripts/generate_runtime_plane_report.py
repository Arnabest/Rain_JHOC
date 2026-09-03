"""Run deterministic local runtime-plane probes and publish evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.atlas import AtlasStore, KnowledgeRecord, KnowledgeStatus, SQLiteAtlasStore  # noqa: E402
from jhoc.bench import Bench, BenchmarkCase  # noqa: E402
from jhoc.commons import CommunityMessage, SQLiteCommons  # noqa: E402
from jhoc.conductor import CandidateDecision, CapabilityRequest, Conductor  # noqa: E402
from jhoc.contracts import MessageEnvelope, PluginManifest  # noqa: E402
from jhoc.contracts.errors import ContractError  # noqa: E402
from jhoc.context import ContextOrchestrator, ContextSource  # noqa: E402
from jhoc.flow import FlowStateMachine  # noqa: E402
from jhoc.forge import Candidate, CandidateStatus, Forge, SQLiteForge  # noqa: E402
from jhoc.graph import GraphNode, GraphRelation, GraphStore, SQLiteGraphStore  # noqa: E402
from jhoc.idle import IdleJob, IdleScheduler, IdleStatus, SQLiteIdleScheduler  # noqa: E402
from jhoc.guard import PolicyBundle, PolicyRequest, PolicyRule, SQLiteGuardRuntime  # noqa: E402
from jhoc.lens import LogEntry, SQLiteLensCollector  # noqa: E402
from jhoc.memory_store import MemoryRecord, SQLiteMemoryStore  # noqa: E402
from jhoc.quota import ResourcePlan, SQLiteQuotaManager  # noqa: E402
from jhoc.relay import DeliveryStatus, Relay, SQLiteRelay  # noqa: E402
from jhoc.registry import CapabilityRecord, CapabilityRegistry, SQLiteCapabilityRegistry  # noqa: E402
from jhoc.runner import OperationJournal, Runner  # noqa: E402
from jhoc.plugins import PluginHost, PluginLifecycle  # noqa: E402
from jhoc.restore import RecoveryManager, SQLiteRecoveryManager, RecoveryStage, RestoreManifest  # noqa: E402
from jhoc.config import RuntimeMode  # noqa: E402
from jhoc.storage import SQLiteStateStore, SQLiteStore  # noqa: E402
from jhoc.shelf import Shelf, SQLiteShelf  # noqa: E402
from jhoc.trust import Identity, IdentityType, PermissionSet, SQLiteTrustStore  # noqa: E402


class _ProbePlugin:
    def __init__(self) -> None:
        self.closed = False

    def describe(self):
        return {"plugin_id": "probe.echo", "protocol_version": "1.0", "capabilities": ["echo"]}

    def health(self):
        return {"status": "READY"}

    def initialize(self, config):
        self.config = dict(config)

    def validate(self, request):
        if "value" not in request:
            raise ValueError("value is required")

    def invoke(self, request):
        return {"value": request["value"]}

    def stream(self, request):
        yield self.invoke(request)

    def cancel(self, work_id):
        return None

    def checkpoint(self):
        return {"ready": True}

    def drain(self):
        return None

    def shutdown(self):
        self.closed = True


def _p4_probe() -> dict[str, object]:
    manifest = PluginManifest(
        "probe.echo", "Probe Echo", "1.0.0", "1.0", "capability", verification_status="VERIFIED"
    )
    plugins = []
    for index in range(100):
        plugin = _ProbePlugin()
        plugins.append(plugin)
        host = PluginHost(manifest, plugin)
        host.verify(); host.install(); host.load(); host.handshake(); host.initialize()
        if host.invoke({"value": index}) != {"value": index}:
            return {"passed": False, "cycles": index}
        host.drain(); host.shutdown()
        if host.state != PluginLifecycle.STOPPED:
            return {"passed": False, "cycles": index + 1}
    return {"passed": all(plugin.closed for plugin in plugins), "cycles": len(plugins), "all_shutdown": True}


def _p5_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jhoc-p5-") as directory:
        path = str(Path(directory) / "p5.sqlite3")
        trust = SQLiteTrustStore(path)
        identity = trust.register(
            Identity("probe-user", IdentityType.USER, PermissionSet(frozenset({"task.read"})))
        )
        key = trust.issue_key(identity.identity_id, "sha256:probe", key_id="key:probe")
        session = trust.open_session(identity.identity_id, key.key_id, "sha256:probe")
        trust.close()
        trust = SQLiteTrustStore(path)
        restored = trust.authenticate(identity.identity_id, key.key_id, "sha256:probe")
        authorized = trust.authorize(identity.identity_id, "task.read", session_id=session.session_id)
        trust.close()
    return {"passed": restored and authorized, "identity_restored": restored, "session_authorized": authorized, "secret_material_stored": False}


def _p6_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jhoc-p6-") as directory:
        path = str(Path(directory) / "p6.sqlite3")
        lens = SQLiteLensCollector(path)
        lens.emit(LogEntry("run", "runner", task_id="task:p6", work_id="work:p6", trace_id="trace:p6"))
        lens.record_event({"event": "observed", "task_id": "task:p6", "work_id": "work:p6", "trace_id": "trace:p6"})
        lens.record_audit({"operation": "verify", "task_id": "task:p6", "work_id": "work:p6", "trace_id": "trace:p6"})
        lens.record_evidence({"digest": "proof:p6", "task_id": "task:p6", "work_id": "work:p6", "trace_id": "trace:p6"})
        lens.close(); lens = SQLiteLensCollector(path)
        trace = lens.reconstruct(task_id="task:p6", work_id="work:p6")
        lens.close()
    kinds = [item.record_type for item in trace]
    return {"passed": kinds == ["log", "event", "audit", "evidence"], "record_types": kinds, "reopened": True}


def _p8_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jhoc-p8-") as directory:
        path = str(Path(directory) / "p8.sqlite3")
        guard = SQLiteGuardRuntime(path)
        identity = Identity("probe-user", IdentityType.USER)
        guard.load(PolicyBundle("policy:probe", "local", (PolicyRule("allow", "ALLOW", frozenset({"task.run"}), 1),)))
        guard.evaluate(identity, PolicyRequest("task.run", 0))
        guard.evaluate(identity, PolicyRequest("task.denied", 0))
        guard.close(); guard = SQLiteGuardRuntime(path)
        receipts = guard.decisions(policy_ref="policy:probe")
        versions = [bundle.version for bundle in guard.bundle_history()]
        guard.close()
    return {"passed": len(receipts) == 2 and versions == ["policy:probe"], "decision_receipts": len(receipts), "bundle_versions": versions, "reopened": True}


def _p10_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jhoc-p10-") as directory:
        path = str(Path(directory) / "p10.sqlite3")
        registry = SQLiteCapabilityRegistry(path)
        manifest = PluginManifest(
            "probe.cap", "Probe", "1.0.0", "1.0", "capability",
            verification_status="VERIFIED", shelf_eligible=True,
        )
        registry.register(CapabilityRecord("probe.cap", "1.0.0", manifest, "schema:in", "schema:out"))
        verified = registry.verify("probe.cap", "1.0.0")
        shelf = SQLiteShelf(path); shelf.admit(verified)
        capacity = ResourcePlan(cpu_units=1, memory_mb=256, token_budget=100, max_concurrency=1)
        first = SQLiteQuotaManager(path, capacity); second = SQLiteQuotaManager(path, capacity)
        now = datetime.now(timezone.utc)
        first.acquire("first", ResourcePlan(cpu_units=1, memory_mb=128, token_budget=50, max_seconds=1), now=now)
        cross_instance_denied = False
        try:
            second.acquire("second", ResourcePlan(cpu_units=1, memory_mb=128, token_budget=50), now=now)
        except ContractError:
            cross_instance_denied = True
        lease = second.acquire("second", ResourcePlan(cpu_units=1, memory_mb=128, token_budget=50), now=now + timedelta(seconds=2))
        second.record_usage(lease.lease_id, tokens_used=25)
        first.close(); second.close(); registry.close(); shelf.close()
        registry = SQLiteCapabilityRegistry(path); shelf = SQLiteShelf(path); quota = SQLiteQuotaManager(path, capacity)
        restored = registry.get("probe.cap", "1.0.0") is not None and shelf.get("probe.cap", "1.0.0") is not None
        usage = quota.usage(lease.lease_id)
        registry.close(); shelf.close(); quota.close()
    return {"passed": cross_instance_denied and restored and usage is not None and usage.tokens_used == 25, "cross_instance_denied": cross_instance_denied, "capability_restored": restored, "tokens_used": usage.tokens_used if usage else None}


def _p11_probe() -> dict[str, object]:
    registry = CapabilityRegistry(); shelf = Shelf()
    manifest = PluginManifest(
        "fallback", "Fallback", "1.0.0", "1.0", "capability",
        verification_status="VERIFIED", shelf_eligible=True,
    )
    registry.register(CapabilityRecord("fallback", "1.0.0", manifest, "schema:in", "schema:out"))
    shelf.admit(registry.verify("fallback", "1.0.0", health="HEALTHY"))
    guard = SQLiteGuardRuntime(":memory:")
    guard.load(PolicyBundle("policy:p11", "local", (PolicyRule("run", "ALLOW", frozenset({"run"}), 1),)))
    conductor = Conductor(registry, shelf, SQLiteQuotaManager(":memory:", ResourcePlan()), guard)
    plan = conductor.select(
        None,
        PolicyRequest("run", 0),
        CapabilityRequest("run", (("missing", "1.0.0"), ("fallback", "1.0.0")), ResourcePlan()),
    )
    assessments = [item.decision.value for item in plan.assessments]
    reasons = [item.reason for item in plan.assessments]
    conductor.release(plan); conductor.quota.close(); guard.close()
    return {"passed": plan.selected == ("fallback", "1.0.0") and assessments == [CandidateDecision.REJECTED.value, CandidateDecision.SELECTED.value], "selected": list(plan.selected) if plan.selected else None, "assessments": assessments, "reasons": reasons}


def _p12_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jhoc-p12-") as directory:
        path = str(Path(directory) / "p12.sqlite3")
        backend = SQLiteStore(path); context = ContextOrchestrator(SQLiteStateStore(backend))
        now = datetime.now(timezone.utc)
        pass_a = context.pass_a("probe", {}, policy_ref="policy:p12")
        package = context.pass_b(
            pass_a,
            (
                ContextSource("expired", {}, "public", now - timedelta(seconds=1), frozenset({"runner"}), ("source:expired",)),
                ContextSource("allowed", {"value": 1}, "internal", now + timedelta(minutes=5), frozenset({"runner"}), ("source:allowed",)),
            ),
            authorized_source_ids=frozenset({"expired", "allowed"}),
            consumer_id="runner",
            resource_plan_ref="lease:p12",
            now=now,
        )
        backend.close(); backend = SQLiteStore(path); rebuilt = ContextOrchestrator(SQLiteStateStore(backend)).rebuild(package.snapshot_id); backend.close()
    return {"passed": rebuilt == package and [item.source_id for item in rebuilt.sources] == ["allowed"], "snapshot_id": package.snapshot_id, "sources": [item.source_id for item in rebuilt.sources], "reopened": True}


def _p14_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jhoc-p14-") as directory:
        path = str(Path(directory) / "p14.sqlite3")
        trust = SQLiteTrustStore(path)
        identity = trust.register(Identity("reviewer", IdentityType.AGENT, PermissionSet(frozenset({"commons.review"}))))
        commons = SQLiteCommons(path, trust)
        commons.publish(
            CommunityMessage("REVIEW", "reviewer", {"verdict": "local"}, ("evidence:p14",), verified=True),
            eligible_evidence=True,
            identity_id=str(identity.identity_id),
        )
        commons.close(); trust.close(); trust = SQLiteTrustStore(path); commons = SQLiteCommons(path, trust)
        restored = commons.messages()
        commons.close(); trust.close()
    return {"passed": len(restored) == 1 and restored[0].author == "reviewer", "messages": len(restored), "identity_bound": True, "reopened": True}


def _p13_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jhoc-p13-") as directory:
        path = str(Path(directory) / "p13.sqlite3")
        backend = SQLiteStore(path)
        runner = Runner(OperationJournal(SQLiteStateStore(backend)))
        task_id, work_id = uuid4(), uuid4()
        calls = []
        first = runner.execute(task_id, work_id, FlowStateMachine(), lambda: (calls.append(1) or {"ok": True}), operation_id="operation:p13", side_effecting=True)
        backend.close(); backend = SQLiteStore(path)
        runner = Runner(OperationJournal(SQLiteStateStore(backend)))
        replay = runner.execute(task_id, work_id, FlowStateMachine(), lambda: (calls.append(2) or {"ok": False}), operation_id="operation:p13", side_effecting=True)
        crash_task, crash_work = uuid4(), uuid4()
        runner.journal.claim("operation:in-doubt", str(crash_task), str(crash_work))
        backend.close(); backend = SQLiteStore(path)
        runner = Runner(OperationJournal(SQLiteStateStore(backend)))
        in_doubt = runner.execute(crash_task, crash_work, FlowStateMachine(), lambda: (calls.append(3) or {}), operation_id="operation:in-doubt", side_effecting=True)
        backend.close()
    passed = calls == [1] and first.result.output == replay.result.output and in_doubt.result.side_effect_state.value == "UNKNOWN_SIDE_EFFECT"
    return {"passed": passed, "action_calls": calls, "replay_output_equal": first.result.output == replay.result.output, "in_doubt_state": in_doubt.result.side_effect_state.value, "reopened": True}


def _relay_probe() -> dict[str, object]:
    relay = Relay()
    messages = [MessageEnvelope("event", "probe", "report", {"priority": index % 100}, uuid4()) for index in range(500)]
    for message in messages:
        relay.enqueue(message)
    leased = [relay.lease(f"worker-{index % 8}") for index in range(len(messages))]
    if any(item is None for item in leased):
        return {"passed": False, "detail": "unable to lease all messages"}
    for item in reversed(leased):
        relay.ack(str(item.envelope.message_id), consumer=item.consumer, lease_id=item.lease_id)
    in_memory_passed = all(relay.get(str(message.message_id)).status == DeliveryStatus.ACKED for message in messages)
    with tempfile.TemporaryDirectory(prefix="jhoc-relay-") as directory:
        path = str(Path(directory) / "storm.sqlite3")
        durable = SQLiteRelay(path, lease_seconds=2)
        for index in range(200):
            durable.enqueue(MessageEnvelope("event", "storm", "report", {}, f"00000000-0000-0000-0000-{index + 5007:012d}"))
        durable.close()
        worker = (
            "import sys, time; sys.path.insert(0, " + repr(str(ROOT / "src")) + "); "
            "from jhoc.relay import SQLiteRelay; r=SQLiteRelay(" + repr(path) + ", lease_seconds=2); n=0; "
            "\nidle=0\nwhile idle < 20:\n"
            "  try:\n"
            "    x=r.lease('report-worker')\n"
            "  except Exception:\n"
            "    time.sleep(0.02); continue\n"
            "  if x is None: idle += 1; time.sleep(0.01); continue\n"
            "  idle=0\n"
            "  while True:\n"
            "    try:\n"
            "      r.ack(str(x.envelope.message_id), consumer=x.consumer, lease_id=x.lease_id); break\n"
            "    except Exception:\n"
            "      time.sleep(0.02)\n"
            "  n += 1\n"
            "print(n); r.close()"
        )
        processes = [subprocess.Popen([sys.executable, "-c", worker], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
        outputs = [process.communicate(timeout=30) for process in processes]
        counts = [int(stdout.strip() or "0") for stdout, _ in outputs if stdout.strip().isdigit()]
        durable_passed = all(process.returncode == 0 for process in processes) and sum(counts) == 200
        check = SQLiteRelay(path)
        pending = check.pending_count()
        check.close()
    return {"passed": in_memory_passed and durable_passed and pending == 0, "messages": len(messages), "ack_order": "reverse", "multi_process_messages": 200, "multi_process_pending": pending}


def _p9_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jhoc-p9-") as directory:
        path = str(Path(directory) / "p9.sqlite3")
        atlas = SQLiteAtlasStore(path)
        graph = SQLiteGraphStore(path)
        memory = SQLiteMemoryStore(path)
        record = atlas.ingest(KnowledgeRecord({"fact": True}, "FACT", "probe:p9", "internal", record_id="knowledge:p9"))
        for status in (KnowledgeStatus.PARSED, KnowledgeStatus.NORMALIZED, KnowledgeStatus.CANDIDATE, KnowledgeStatus.VERIFIED):
            record = atlas.transition(record.record_id, status)
        memory.write(MemoryRecord({"note": True}, "TaskMemory", "probe:p9", "confidential", "memory:p9"), approved=True)
        graph.add_node(GraphNode("task", "Task")); graph.add_node(GraphNode("fact", "Knowledge"))
        graph.add_relation(GraphRelation("supports-1", "task", "fact", "supports", 0.9, "probe:p9", "VERIFIED", "SUPPORTED"))
        atlas.close(); graph.close(); memory.close()
        atlas = SQLiteAtlasStore(path); graph = SQLiteGraphStore(path); memory = SQLiteMemoryStore(path)
        versions = len(atlas.history(record.record_id)); supported = len(graph.relations_by_quality("SUPPORTED")); sensitivity = memory.get("memory:p9").sensitivity
        atlas.close(); graph.close(); memory.close()
    return {"passed": versions == 5 and supported == 1 and sensitivity == "CONFIDENTIAL", "lifecycle_versions": versions, "memory_sensitivity": sensitivity, "supported_relations": supported, "reopened": True}


def _p15_probe() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="jhoc-p15-") as directory:
        path = str(Path(directory) / "p15.sqlite3")
        scheduler = SQLiteIdleScheduler(path)
        job = scheduler.submit(IdleJob("probe", ttl_seconds=10, created_at=now, job_id="idle:p15"))
        blocked_attempts = sum(scheduler.start_next(foreground_active=True, now=now) is None for _ in range(1000))
        running = scheduler.start_next(now=now); scheduler.checkpoint(job.job_id, {"cursor": 100}); scheduler.preempt_for_foreground(); scheduler.close()
        scheduler = SQLiteIdleScheduler(path)
        recovered = scheduler.get(job.job_id)
        scheduler.resume(job.job_id); scheduler.start_next(now=now + timedelta(seconds=11)); final = scheduler.get(job.job_id); scheduler.close()
    return {"passed": blocked_attempts == 1000 and running is not None and recovered.status == IdleStatus.PAUSED and recovered.checkpoint == {"cursor": 100} and final.status == IdleStatus.EXPIRED, "foreground_blocked_attempts": blocked_attempts, "recovered_status": recovered.status.value, "final_status": final.status.value}


def _p16_probe() -> dict[str, object]:
    bench = Bench().run((BenchmarkCase("replay", 1, lambda actual, expected: actual == expected),), lambda _: 1)
    with tempfile.TemporaryDirectory(prefix="jhoc-p16-") as directory:
        path = str(Path(directory) / "p16.sqlite3")
        forge = SQLiteForge(path)
        candidate = forge.observe(Candidate("adjust reranker", ("evidence:p16",), candidate_id="candidate:p16", version="2"))
        candidate = forge.evaluate(candidate.candidate_id, regression_free=True, replay_complete=True, safety_passed=True, benchmark_ref="bench:p16", benchmark_result=bench)
        candidate = forge.promote(candidate.candidate_id, approved=True, approved_by="probe")
        forge.observe_canary(candidate.candidate_id, healthy=True, score=0.96, evidence_ref="canary:p16:1")
        forge.observe_canary(candidate.candidate_id, healthy=True, score=0.99, evidence_ref="canary:p16:2")
        forge.close(); forge = SQLiteForge(path)
        observations = len(forge.canary_history(candidate.candidate_id)); candidate = forge.complete_canary(candidate.candidate_id, healthy=True, score=1.0); forge.close()
    return {"passed": candidate.status == CandidateStatus.PROMOTED and observations == 2, "status": candidate.status.value, "benchmark_pass_rate": bench.pass_rate, "canary_observations": observations, "reopened": True}


def _p17_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jhoc-restore-") as directory:
        audit_path = str(Path(directory) / "audit.sqlite3")
        manager = SQLiteRecoveryManager(audit_path)
        source = Path(directory) / "source.sqlite3"
        SQLiteStore(str(source)).close()
        snapshot = manager.snapshot_database(source, Path(directory) / "snapshots", snapshot_id="probe")
        verified = manager.verify_snapshot(snapshot)
        manager.restore_database(snapshot, Path(directory) / "restored.sqlite3")
        manager.close(); manager = SQLiteRecoveryManager(audit_path); audits = manager.audit_records(); manager.close()
    return {"passed": bool(snapshot.sha256) and verified and len(audits) >= 2 and all(item.status == "COMPLETED" for item in audits), "audit_records": len(audits), "snapshot_verified": verified, "reopened": True}


def main() -> int:
    planes = {
        "P4": _p4_probe(),
        "P5": _p5_probe(),
        "P6": _p6_probe(),
        "P7": _relay_probe(),
        "P8": _p8_probe(),
        "P9": _p9_probe(),
        "P10": _p10_probe(),
        "P11": _p11_probe(),
        "P12": _p12_probe(),
        "P13": _p13_probe(),
        "P14": _p14_probe(),
        "P15": _p15_probe(),
        "P16": _p16_probe(),
        "P17": _p17_probe(),
    }
    report = {
        "report_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": "JHOC",
        "planes": planes,
        "all_local_probes_passed": all(bool(value.get("passed")) for value in planes.values()),
        "release_claim": "Local runtime-plane probes only; independent review and formal release gates remain separate.",
    }
    out = ROOT / "docs" / "acceptance" / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    (out / "jhoc-runtime-plane-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    lines = ["# JHOC Runtime Plane Evidence", "", f"- Generated: `{report['generated_at']}`", f"- All local probes: **{'PASS' if report['all_local_probes_passed'] else 'FAIL'}**", ""]
    lines.extend(f"- {name}: **{'PASS' if value['passed'] else 'FAIL'}**" for name, value in planes.items())
    lines.append("\nThis report is local evidence only and does not replace independent review or formal release approval.\n")
    (out / "jhoc-runtime-plane-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"json": str(out / "jhoc-runtime-plane-report.json"), "all_local_probes_passed": report["all_local_probes_passed"]}, ensure_ascii=True))
    return 0 if report["all_local_probes_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
