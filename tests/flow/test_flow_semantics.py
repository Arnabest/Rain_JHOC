import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.contracts import ContractError, ErrorCode, SideEffectState, WorkStatus  # noqa: E402
from jhoc.flow import (  # noqa: E402
    CancellationToken,
    FlowActor,
    FlowStateError,
    FlowStateMachine,
    IdempotencyLedger,
    RetryDecision,
    RetryPolicy,
)


class FlowSemanticsTests(unittest.TestCase):
    def test_happy_path_and_gate_owned_completion(self):
        flow = FlowStateMachine()
        for state in (WorkStatus.PLAN, WorkStatus.ACT, WorkStatus.OBSERVE, WorkStatus.VERIFY, WorkStatus.COMPLETION_PENDING):
            flow.transition(state, actor=FlowActor.RUNNER, reason="advance")
        with self.assertRaises(FlowStateError):
            flow.transition(WorkStatus.COMPLETE, actor=FlowActor.RUNNER, reason="finish")
        done = flow.transition(WorkStatus.COMPLETE, actor=FlowActor.GATE, reason="evidence accepted")
        self.assertEqual(done.sequence, 6)

    def test_stale_version_is_rejected(self):
        flow = FlowStateMachine()
        flow.transition(WorkStatus.PLAN, actor="runner", reason="plan")
        with self.assertRaises(FlowStateError) as error:
            flow.transition(WorkStatus.ACT, actor="runner", reason="act", expected_version=0)
        self.assertEqual(error.exception.code, ErrorCode.STALE_STATE)

    def test_terminal_states_cannot_be_reopened(self):
        flow = FlowStateMachine()
        flow.transition(WorkStatus.BLOCKED, actor="guard", reason="denied")
        with self.assertRaises(FlowStateError):
            flow.transition(WorkStatus.PLAN, actor="runner", reason="retry")

    def test_retry_policy_bounds_and_unknown_side_effect(self):
        policy = RetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=2)
        self.assertEqual(policy.delay_seconds(4), 2)
        self.assertEqual(policy.decide(1, retryable=True), RetryDecision.RETRY)
        self.assertEqual(policy.decide(3, retryable=True), RetryDecision.FAIL)
        self.assertEqual(
            policy.decide(1, retryable=True, side_effect_state=SideEffectState.UNKNOWN_SIDE_EFFECT),
            RetryDecision.RECONCILE,
        )

    def test_idempotency_duplicate_is_replay_and_conflict_is_rejected(self):
        ledger = IdempotencyLedger()
        first = ledger.claim("k1", {"a": 1, "b": 2})
        replay = ledger.claim("k1", {"b": 2, "a": 1})
        self.assertEqual(first.fingerprint, replay.fingerprint)
        with self.assertRaises(ContractError) as error:
            ledger.claim("k1", {"a": 9})
        self.assertEqual(error.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)

    def test_cancellation_is_one_way_and_observable(self):
        token = CancellationToken()
        self.assertTrue(token.cancel())
        self.assertFalse(token.cancel())
        with self.assertRaises(FlowStateError) as error:
            token.raise_if_cancelled()
        self.assertEqual(error.exception.code, ErrorCode.CANCELLED)


if __name__ == "__main__":
    unittest.main()

