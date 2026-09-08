import sys
import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.independence import IndependenceReport, check_source  # noqa: E402
from jhoc.ingest import (  # noqa: E402
    ApprovedMigrationImporter,
    Disposition,
    IngestScanner,
    MigrationApproval,
    MigrationStatus,
    OfflineMigration,
)
from jhoc.atlas import AtlasStore  # noqa: E402
from jhoc.memory_store import MemoryStore  # noqa: E402
from jhoc.ops import (  # noqa: E402
    ArchiveManifest,
    CutoverValidator,
    EntrypointProof,
    UserCutoverApproval,
)
from jhoc.restore import RecoveryManager  # noqa: E402
from jhoc.storage import SQLiteStore, StateStore  # noqa: E402
from jhoc.trust import Identity, IdentityType, PermissionSet, TrustStore  # noqa: E402


class AcceptanceToolTests(unittest.TestCase):
    @staticmethod
    def migration_approval(run, item):
        trust = TrustStore()
        identity = trust.register(
            Identity("operator:1", IdentityType.USER, PermissionSet(frozenset({"migration.import"})))
        )
        key = trust.issue_key(identity.identity_id, "fixture-fingerprint")
        session = trust.open_session(identity.identity_id, key.key_id, "fixture-fingerprint")
        approval = MigrationApproval(
            item.relative_path,
            run.manifest_hash,
            item.prepared_sha256,
            item.target_type,
            "memory" if item.target_type.endswith("Memory") else "atlas",
            identity.identity_id,
            session.session_id,
        )
        return trust, approval

    def test_ingest_is_read_only_manifest_with_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.txt").write_text("hello", encoding="utf-8")
            manifest = IngestScanner().scan(root)
            self.assertEqual(len(manifest.entries), 1)
            self.assertEqual(manifest.entries[0].disposition, Disposition.QUARANTINE)
            self.assertEqual(len(manifest.entries[0].sha256), 64)
            self.assertTrue(IngestScanner().verify(manifest))
            reviewed = manifest.with_dispositions({"a.txt": Disposition.REFERENCE_ONLY})
            self.assertTrue(reviewed.dispositions_complete())
            self.assertEqual(reviewed.entries[0].disposition, Disposition.REFERENCE_ONLY)
            with self.assertRaises(ValueError):
                manifest.with_dispositions({"missing.txt": Disposition.REJECT})
            (root / "a.txt").write_text("changed", encoding="utf-8")
            self.assertFalse(IngestScanner().verify(manifest))

    def test_independence_scan_fails_on_forbidden_runtime_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.py").write_text("import legacy_agent_bus\n", encoding="utf-8")
            report = check_source(root)
            self.assertFalse(report.passed)
            self.assertTrue(report.violations)

    def test_offline_migration_validates_and_quarantines_selected_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            quarantine = root / "quarantine"
            source.mkdir()
            (source / "valid.json").write_text(json.dumps({
                "type": "FACT", "sensitivity": "public", "source_ref": "legacy:1", "content": {"ok": True}
            }), encoding="utf-8")
            (source / "bad.json").write_text("{\"type\": \"UNKNOWN\"}", encoding="utf-8")
            manifest = IngestScanner().scan(source).with_dispositions({
                "valid.json": Disposition.MIGRATE, "bad.json": Disposition.TRANSFORM,
            })
            run = OfflineMigration().run(manifest, quarantine)
            self.assertFalse(run.complete)
            by_path = {item.relative_path: item for item in run.items}
            self.assertEqual(by_path["valid.json"].status, MigrationStatus.MIGRATED)
            self.assertEqual(by_path["bad.json"].status, MigrationStatus.QUARANTINED)
            self.assertTrue((quarantine / "valid.json").exists())

    def test_offline_migration_rejects_source_drift_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text("{}", encoding="utf-8")
            manifest = IngestScanner().scan(root).with_dispositions({"a.json": Disposition.ARCHIVE})
            (root / "a.json").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source changed"):
                OfflineMigration().run(manifest, root / "quarantine")

    def test_offline_migration_requires_explicit_disposition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.txt").write_text("data", encoding="utf-8")
            manifest = IngestScanner().scan(root)
            self.assertFalse(manifest.dispositions_complete())
            with self.assertRaisesRegex(ValueError, "disposition"):
                OfflineMigration().run(manifest, root / "quarantine")

    def test_offline_migration_rejects_symlinked_source_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "link.json"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            manifest = IngestScanner().scan(root).with_dispositions({
                "target.json": Disposition.REJECT,
                "link.json": Disposition.ARCHIVE,
            })
            with self.assertRaisesRegex(ValueError, "symlink"):
                OfflineMigration().run(manifest, root / "quarantine")

    def test_offline_migration_requires_approval_and_imports_to_owner_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "knowledge.json").write_text(json.dumps({
                "type": "FACT", "sensitivity": "public", "source_ref": "legacy:fact", "content": {"answer": 42}
            }), encoding="utf-8")
            manifest = IngestScanner().scan(root).with_dispositions({"knowledge.json": Disposition.TRANSFORM})
            run = OfflineMigration().run(manifest, root / "quarantine")
            item = run.items[0]
            trust, approval = self.migration_approval(run, item)
            importer = ApprovedMigrationImporter(trust, StateStore())
            with self.assertRaisesRegex(ValueError, "approval"):
                importer.import_approved(run, {}, atlas=AtlasStore())
            imported = importer.import_approved(
                run, {"knowledge.json": approval}, atlas=AtlasStore()
            )
            self.assertEqual(imported[0].target_store, "atlas")

    def test_offline_migration_rejects_quarantine_tampering_after_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "knowledge.json").write_text(json.dumps({
                "type": "FACT", "sensitivity": "public", "source_ref": "legacy:fact",
                "content": {"answer": 42},
            }), encoding="utf-8")
            manifest = IngestScanner().scan(source).with_dispositions(
                {"knowledge.json": Disposition.TRANSFORM}
            )
            quarantine = root / "quarantine"
            run = OfflineMigration().run(manifest, quarantine)
            trust, approval = self.migration_approval(run, run.items[0])
            (quarantine / "knowledge.json").write_text(json.dumps({
                "type": "FACT", "sensitivity": "public", "source_ref": "legacy:fact",
                "content": {"answer": "replaced"},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                ApprovedMigrationImporter(trust, StateStore()).import_approved(
                    run, {"knowledge.json": approval}, atlas=AtlasStore()
                )

    def test_migration_import_resumes_after_partial_owner_store_failure(self):
        class FailSecondAtlas(AtlasStore):
            def __init__(self):
                super().__init__()
                self.calls = []
                self.fail_once = True

            def ingest(self, record):
                self.calls.append(record.record_id)
                if record.content["answer"] == 2 and self.fail_once:
                    self.fail_once = False
                    raise RuntimeError("target unavailable")
                return super().ingest(record)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            for index in (1, 2):
                (source / f"knowledge-{index}.json").write_text(json.dumps({
                    "type": "FACT", "sensitivity": "public", "source_ref": f"legacy:{index}",
                    "content": {"answer": index},
                }), encoding="utf-8")
            manifest = IngestScanner().scan(source).with_dispositions({
                "knowledge-1.json": Disposition.TRANSFORM,
                "knowledge-2.json": Disposition.TRANSFORM,
            })
            run = OfflineMigration().run(manifest, root / "quarantine")
            trust = TrustStore()
            identity = trust.register(Identity(
                "operator:resume", IdentityType.USER,
                PermissionSet(frozenset({"migration.import"})),
            ))
            key = trust.issue_key(identity.identity_id, "resume-fingerprint")
            session = trust.open_session(identity.identity_id, key.key_id, "resume-fingerprint")
            approvals = {
                item.relative_path: MigrationApproval(
                    item.relative_path,
                    run.manifest_hash,
                    item.prepared_sha256,
                    item.target_type,
                    "atlas",
                    identity.identity_id,
                    session.session_id,
                )
                for item in run.items
            }
            atlas = FailSecondAtlas()
            importer = ApprovedMigrationImporter(trust, StateStore())
            with self.assertRaisesRegex(RuntimeError, "target unavailable"):
                importer.import_approved(run, approvals, atlas=atlas)
            imported = importer.import_approved(run, approvals, atlas=atlas)
            self.assertEqual(len(imported), 2)
            first_record_id = imported[0].record_id
            self.assertEqual(atlas.calls.count(first_record_id), 1)

    def test_fresh_process_starts_with_legacy_environment_removed(self):
        environment = {key: value for key, value in os.environ.items() if all(token not in key.upper() for token in ("AIBOX", "VERS", "AGENT_BUS"))}
        code = f"import sys; sys.path.insert(0, {str(ROOT / 'src')!r}); from jhoc.entrypoint import create_application; app=create_application(); print(app.start().running); app.stop()"
        completed = subprocess.run([sys.executable, "-c", code], env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "True")

    def test_fresh_process_starts_with_legacy_paths_and_network_denied(self):
        environment = {key: value for key, value in os.environ.items() if all(token not in key.upper() for token in ("AIBOX", "VERS", "AGENT_BUS"))}
        forbidden = tuple(str(path).lower() for path in (Path(r"D:\AI Box"), Path(r"D:\VERS-rule"), Path(r"D:\AI Desktop Agent")))
        code = (
            f"import sys; sys.path.insert(0, {str(ROOT / 'src')!r}); forbidden={forbidden!r}\n"
            "def audit(event,args):\n"
            "  if event == 'open' and args and any(str(args[0]).lower().startswith(item) for item in forbidden): raise PermissionError('legacy path denied')\n"
            "  if event.startswith('socket.'): raise PermissionError('network denied')\n"
            "sys.addaudithook(audit)\n"
            "from jhoc.entrypoint import create_application\n"
            "app=create_application(); print(app.start().running); app.stop()"
        )
        completed = subprocess.run([sys.executable, "-c", code], env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "True")

    def test_cutover_is_fail_closed(self):
        trust = TrustStore()
        identity = trust.register(
            Identity("cutover-owner", IdentityType.USER, PermissionSet(frozenset({"ops.cutover"})))
        )
        key = trust.issue_key(identity.identity_id, "cutover-fingerprint")
        session = trust.open_session(identity.identity_id, key.key_id, "cutover-fingerprint")
        validator = CutoverValidator(trust)
        blocked = validator.validate({"G0": True, "G1": False}, IndependenceReport(True, ()), migration_complete=True)
        self.assertFalse(blocked.ready)
        ready = validator.validate({"G0": True, "G1": True}, IndependenceReport(True, ()), migration_complete=True)
        self.assertTrue(ready.ready)
        archive = ArchiveManifest("archive-1", "manifest-hash", ("legacy/source.txt",), migration_manifest_hash="migration-hash")
        entrypoint = EntrypointProof.from_file(
            "jhoc.entrypoint:create_application", ROOT / "src" / "jhoc" / "entrypoint.py"
        )
        prerequisites = validator.validate_prerequisites(
            {"G0": True, "G1": True}, IndependenceReport(True, ()), migration_complete=True,
            archive=archive, migration_manifest_hash="migration-hash", entrypoint_proof=entrypoint,
        )
        self.assertTrue(prerequisites.ready)
        missing_archive = validator.validate_prerequisites(
            {"G0": True, "G1": True}, IndependenceReport(True, ()), migration_complete=True,
            archive=None, migration_manifest_hash="migration-hash", entrypoint_proof=entrypoint,
        )
        self.assertFalse(missing_archive.ready)
        self.assertIn("ARCHIVE_MANIFEST", missing_archive.failed_gates)
        mismatched = validator.validate_prerequisites(
            {"G0": True, "G1": True}, IndependenceReport(True, ()), migration_complete=True,
            archive=archive, migration_manifest_hash="different", entrypoint_proof=entrypoint,
        )
        self.assertFalse(mismatched.ready)
        self.assertIn("ARCHIVE_MANIFEST_HASH", mismatched.failed_gates)
        missing_entrypoint = validator.validate_prerequisites(
            {"G0": True, "G1": True}, IndependenceReport(True, ()), migration_complete=True,
            archive=archive, migration_manifest_hash="migration-hash",
        )
        self.assertFalse(missing_entrypoint.ready)
        self.assertIn("UNIQUE_ENTRYPOINT", missing_entrypoint.failed_gates)
        no_user_approval = validator.validate_final(
            {"G0": True, "G1": True}, IndependenceReport(True, ()), migration_complete=True,
            archive=archive, migration_manifest_hash="migration-hash", entrypoint_proof=entrypoint,
        )
        self.assertFalse(no_user_approval.ready)
        self.assertIn("USER_CUTOVER_APPROVAL", no_user_approval.failed_gates)
        matched = validator.validate_final(
            {"G0": True, "G1": True}, IndependenceReport(True, ()), migration_complete=True,
            archive=archive, migration_manifest_hash="migration-hash", entrypoint_proof=entrypoint,
            user_approval=UserCutoverApproval(
                identity.identity_id,
                session.session_id,
                "Approve JHOC Cutover",
                archive.archive_id,
                archive.digest,
                "migration-hash",
                entrypoint.source_sha256,
            ),
        )
        self.assertTrue(matched.ready)

        replaced_archive = ArchiveManifest(
            archive.archive_id,
            archive.source_manifest_hash,
            ("legacy/replaced.txt",),
            archive.created_at,
            archive.migration_manifest_hash,
        )
        reused_approval = UserCutoverApproval(
            identity.identity_id,
            session.session_id,
            "Approve JHOC Cutover",
            archive.archive_id,
            archive.digest,
            "migration-hash",
            entrypoint.source_sha256,
        )
        replaced = validator.validate_final(
            {"G0": True, "G1": True}, IndependenceReport(True, ()), migration_complete=True,
            archive=replaced_archive, migration_manifest_hash="migration-hash",
            entrypoint_proof=entrypoint, user_approval=reused_approval,
        )
        self.assertFalse(replaced.ready)
        self.assertIn("USER_CUTOVER_APPROVAL", replaced.failed_gates)

    def test_cutover_rejects_stale_entrypoint_proof_and_unbound_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entrypoint.py"
            path.write_text("def create_application(): pass\n", encoding="utf-8")
            proof = EntrypointProof.from_file("jhoc.entrypoint:create_application", path)
            path.write_text("def create_application(): raise RuntimeError\n", encoding="utf-8")
            archive = ArchiveManifest(
                "archive-1", "source-hash", ("legacy/source.txt",),
                migration_manifest_hash="migration-hash",
            )
            decision = CutoverValidator(required_source_path=path).validate_prerequisites(
                {"G0": True}, IndependenceReport(True, ()), migration_complete=True,
                archive=archive, migration_manifest_hash="migration-hash", entrypoint_proof=proof,
            )
            self.assertFalse(decision.ready)
            self.assertIn("UNIQUE_ENTRYPOINT", decision.failed_gates)

        archive = ArchiveManifest(
            "archive-1", "source-hash", ("legacy/source.txt",),
            migration_manifest_hash="migration-hash",
        )
        entrypoint = EntrypointProof.from_file(
            "jhoc.entrypoint:create_application", ROOT / "src" / "jhoc" / "entrypoint.py"
        )
        missing_hash = CutoverValidator().validate_prerequisites(
            {"G0": True}, IndependenceReport(True, ()), migration_complete=True,
            archive=archive, entrypoint_proof=entrypoint,
        )
        self.assertFalse(missing_hash.ready)
        self.assertIn("MIGRATION_MANIFEST_HASH", missing_hash.failed_gates)

    def test_database_snapshot_is_verified_and_restored_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            store = SQLiteStore(str(source))
            store.state_put("core", "restore", {"ok": True})
            store.close()
            manager = RecoveryManager()
            snapshot = manager.snapshot_database(source, root / "snapshots", snapshot_id="snap-001")
            self.assertTrue(manager.verify_snapshot(snapshot))
            target = manager.restore_database(snapshot, root / "restored.db")
            restored = SQLiteStore(str(target))
            self.assertEqual(restored.state_get("core", "restore").value, {"ok": True})
            restored.close()
            with self.assertRaises(FileExistsError):
                manager.restore_database(snapshot, target)


if __name__ == "__main__":
    unittest.main()
