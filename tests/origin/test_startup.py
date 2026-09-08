import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.config import ConfigSnapshot, RuntimeMode  # noqa: E402
from jhoc.contracts import ContractError, ErrorCode  # noqa: E402
from jhoc.origin import OriginRuntime, StartupState  # noqa: E402
from jhoc.trust import Identity, IdentityType, KeyStatus, PermissionSet, SQLiteTrustStore, TrustStore  # noqa: E402


class P5StartupTests(unittest.TestCase):
    def test_empty_system_starts_offline_without_providers(self):
        origin = OriginRuntime()
        health = origin.start()
        self.assertEqual(health.state, StartupState.RUNNING)
        self.assertEqual(health.mode, RuntimeMode.OFFLINE)
        self.assertEqual(health.providers, 0)
        self.assertTrue(origin.can_execute(risk_level=0))
        self.assertFalse(origin.can_execute(risk_level=3))

    def test_safe_mode_blocks_risky_or_external_work(self):
        origin = OriginRuntime()
        origin.start(ConfigSnapshot({"mode": RuntimeMode.EMERGENCY_SAFE_MODE.value}))
        self.assertEqual(origin.state, StartupState.SAFE_MODE)
        self.assertTrue(origin.can_execute(risk_level=0))
        self.assertFalse(origin.can_execute(risk_level=1))
        self.assertFalse(origin.can_execute(risk_level=0, external_side_effect=True))

    def test_config_rejects_unknown_keys_and_hidden_network_override(self):
        with self.assertRaises(ContractError):
            ConfigSnapshot({"fallback_api": {"url": "http://example.invalid"}})
        with self.assertRaises(ContractError) as error:
            ConfigSnapshot({"mode": "OFFLINE", "allow_network": True})
        self.assertEqual(error.exception.code, ErrorCode.POLICY_DENIED)
        with self.assertRaises(ContractError) as error:
            ConfigSnapshot({"mode": "MAGIC"})
        self.assertEqual(error.exception.code, ErrorCode.INVALID_CONTRACT)

    def test_trust_defaults_to_deny_and_revoke_is_effective(self):
        store = TrustStore()
        identity = store.register(Identity("user", IdentityType.USER, PermissionSet(frozenset({"task.read"}))))
        self.assertTrue(store.authorize(identity.identity_id, "task.read"))
        self.assertFalse(store.authorize(identity.identity_id, "task.write"))
        store.revoke(identity.identity_id)
        self.assertFalse(store.authorize(identity.identity_id, "task.read"))

    def test_provider_registration_requires_started_origin(self):
        origin = OriginRuntime()
        with self.assertRaises(ContractError):
            origin.register_provider("model.local")
        origin.start()
        origin.register_provider("model.local")
        self.assertEqual(origin.health().providers, 1)

    def test_key_rotation_revokes_old_key_without_storing_secret_material(self):
        store = TrustStore()
        identity = store.register(Identity("rotating-user", IdentityType.USER, PermissionSet(frozenset({"task.read"}))))
        old = store.issue_key(identity.identity_id, "sha256:old")
        self.assertTrue(store.authenticate(identity.identity_id, old.key_id, "sha256:old"))
        current = store.rotate_key(identity.identity_id, "sha256:new")
        self.assertEqual(current.version, 2)
        self.assertEqual(store.key(old.key_id).status, KeyStatus.REVOKED)
        self.assertFalse(store.authenticate(identity.identity_id, old.key_id, "sha256:old"))
        self.assertTrue(store.authenticate(identity.identity_id, current.key_id, "sha256:new"))

    def test_key_rotation_rejects_id_collision_without_revoking_current_key(self):
        store = TrustStore()
        identity = store.register(Identity("collision-user", IdentityType.USER))
        current = store.issue_key(identity.identity_id, "sha256:current", key_id="key:current")
        store.issue_key(identity.identity_id, "sha256:other", key_id="key:other")
        with self.assertRaises(ContractError) as error:
            store.rotate_key(identity.identity_id, "sha256:new", key_id="key:other")
        self.assertEqual(error.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)
        self.assertEqual(store.key(current.key_id).status, KeyStatus.ACTIVE)

    def test_session_authorization_is_identity_bound_and_expires(self):
        store = TrustStore()
        first = store.register(Identity("first", IdentityType.USER, PermissionSet(frozenset({"task.read"}))))
        second = store.register(Identity("second", IdentityType.AGENT, PermissionSet()))
        key = store.issue_key(first.identity_id, "sha256:first")
        session = store.open_session(first.identity_id, key.key_id, "sha256:first", ttl_seconds=0.01)
        self.assertTrue(store.authorize(first.identity_id, "task.read", session_id=session.session_id))
        self.assertFalse(store.authorize(second.identity_id, "task.read", session_id=session.session_id))
        store.revoke_key(key.key_id)
        self.assertFalse(store.authorize(first.identity_id, "task.read", session_id=session.session_id))
        key = store.rotate_key(first.identity_id, "sha256:first-rotated")
        session = store.open_session(first.identity_id, key.key_id, "sha256:first-rotated", ttl_seconds=0.01)
        time.sleep(0.03)
        self.assertFalse(store.authorize(first.identity_id, "task.read", session_id=session.session_id))
        self.assertTrue(any(event.event == "IMPERSONATION_OR_SESSION_DENIED" for event in store.events()))
        self.assertTrue(any(event.event == "SESSION_EXPIRED" for event in store.events()))

    def test_delegation_is_limited_to_held_permissions_and_revocation(self):
        store = TrustStore()
        delegator = store.register(Identity("delegator", IdentityType.USER, PermissionSet(frozenset({"task.read"}))))
        delegatee = store.register(Identity("delegatee", IdentityType.AGENT))
        delegation = store.delegate(delegator.identity_id, delegatee.identity_id, frozenset({"task.read"}))
        self.assertTrue(store.authorize(delegatee.identity_id, "task.read"))
        with self.assertRaises(ContractError) as error:
            store.delegate(delegator.identity_id, delegatee.identity_id, frozenset({"task.write"}))
        self.assertEqual(error.exception.code, ErrorCode.POLICY_DENIED)
        store.revoke(delegator.identity_id)
        self.assertFalse(store.authorize(delegatee.identity_id, "task.read"))
        self.assertEqual(store.key("missing"), None)

    def test_sqlite_trust_restores_metadata_and_rejects_stale_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "trust.db")
            first = SQLiteTrustStore(path)
            stale = SQLiteTrustStore(path)
            owner = first.register(
                Identity("durable-owner", IdentityType.USER, PermissionSet(frozenset({"task.read"})))
            )
            delegatee = first.register(Identity("durable-agent", IdentityType.AGENT))
            key = first.issue_key(owner.identity_id, "sha256:durable", key_id="key:durable")
            session = first.open_session(owner.identity_id, key.key_id, "sha256:durable")
            first.delegate(owner.identity_id, delegatee.identity_id, frozenset({"task.read"}))
            self.assertFalse(first.authenticate(owner.identity_id, key.key_id, "sha256:wrong"))
            with self.assertRaises(ContractError):
                first.open_session(owner.identity_id, key.key_id, "sha256:wrong")

            stale_identity = Identity("stale", IdentityType.SERVICE)
            with self.assertRaises(ContractError) as error:
                stale.register(stale_identity)
            self.assertEqual(error.exception.code, ErrorCode.STALE_STATE)
            self.assertEqual(stale.register(stale_identity), stale_identity)
            self.assertEqual(stale.get(stale_identity.identity_id), stale_identity)
            stale.close()
            first.close()

            restored = SQLiteTrustStore(path)
            self.assertEqual(restored.get(owner.identity_id).subject, "durable-owner")
            self.assertTrue(restored.authenticate(owner.identity_id, key.key_id, "sha256:durable"))
            self.assertTrue(restored.authorize(owner.identity_id, "task.read", session_id=session.session_id))
            self.assertTrue(restored.authorize(delegatee.identity_id, "task.read"))
            self.assertEqual(
                [event.event for event in restored.events()].count("AUTHENTICATION_DENIED"),
                2,
            )
            observer = SQLiteTrustStore(path)
            restored.revoke(owner.identity_id)
            self.assertFalse(observer.authorize(owner.identity_id, "task.read", session_id=session.session_id))
            observer.close()
            restored.close()

    def test_sqlite_trust_refresh_retries_a_mid_load_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "trust.db")
            writer = SQLiteTrustStore(path)
            observer = SQLiteTrustStore(path)
            owner = writer.register(Identity("owner", IdentityType.USER))
            concurrent = Identity("concurrent", IdentityType.SERVICE)
            injected = False

            def inject_write(statement):
                nonlocal injected
                if not injected and "FROM jhoc_trust_identity" in statement:
                    injected = True
                    writer.register(concurrent)

            observer._db.set_trace_callback(inject_write)
            self.assertEqual(observer.get(owner.identity_id), owner)
            observer._db.set_trace_callback(None)
            current_revision = int(
                observer._db.execute(
                    "SELECT revision FROM jhoc_trust_meta WHERE singleton=1"
                ).fetchone()[0]
            )
            self.assertTrue(injected)
            self.assertEqual(observer._revision, current_revision)
            self.assertEqual(observer._identities[concurrent.identity_id], concurrent)
            observer.close()
            writer.close()


if __name__ == "__main__":
    unittest.main()
