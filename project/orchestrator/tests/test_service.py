from __future__ import annotations

import unittest

from neftecode_orchestrator.contracts import (
    ComponentResult,
    OrchestratorInput,
    QualityAssessment,
    ReliabilityAssessment,
)
from neftecode_orchestrator.enums import (
    ComponentStatus,
    DataConfidence,
    Decision,
    InputSource,
    ReliabilityRisk,
)
from neftecode_orchestrator.reason_codes import ReasonCode
from neftecode_orchestrator.service import OrchestratorService
from neftecode_orchestrator.stubs import (
    make_keep_input,
    make_no_change_input,
    make_recommend_input,
    make_refuse_input,
    safe,
)
from neftecode_orchestrator.trace import InMemoryTraceSink


def replace(data: OrchestratorInput, **changes) -> OrchestratorInput:
    payload = data.model_dump(mode="python")
    payload.update(changes)
    return OrchestratorInput.model_validate(payload)


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = OrchestratorService()

    def test_recommend_top_ranked_safe_candidate(self) -> None:
        decision = self.service.decide(make_recommend_input())
        self.assertEqual(decision.decision, Decision.RECOMMEND)
        self.assertEqual(decision.selected_candidate.candidate_id, "CANDIDATE_001")
        self.assertEqual(decision.predicted_result["quality_prediction"], 8.8)
        self.assertEqual(decision.predicted_result["candidate_horizon_hours"], 1.0)

    def test_keep_safe_current_mode_when_no_change_is_feasible(self) -> None:
        decision = self.service.decide(make_keep_input())
        self.assertEqual(decision.decision, Decision.KEEP)
        self.assertIsNone(decision.selected_candidate)
        self.assertIn(ReasonCode.KEEP_NO_FEASIBLE_CHANGE.value, decision.reason_codes)

    def test_keep_when_no_change_is_ranked_first(self) -> None:
        decision = self.service.decide(make_no_change_input())
        self.assertEqual(decision.decision, Decision.KEEP)
        self.assertIn(
            ReasonCode.KEEP_TOP_CANDIDATE_IS_NO_CHANGE.value,
            decision.reason_codes,
        )

    def test_refuse_unsafe_current_mode_when_no_candidate_is_feasible(self) -> None:
        decision = self.service.decide(make_refuse_input())
        self.assertEqual(decision.decision, Decision.REFUSE)
        self.assertIn(
            ReasonCode.REFUSE_CURRENT_UNSAFE_NO_FEASIBLE.value,
            decision.reason_codes,
        )

    def test_timeout_is_fail_closed(self) -> None:
        data = make_recommend_input()
        timeout = ComponentResult[QualityAssessment](
            status=ComponentStatus.TIMEOUT,
            error_code="QUALITY_TIMEOUT",
            message="QualityAgent did not respond",
        )
        decision = self.service.decide(replace(data, current_quality=timeout))
        self.assertEqual(decision.decision, Decision.REFUSE)
        self.assertIn(
            f"{ReasonCode.REFUSE_COMPONENT_TIMEOUT.value}:quality",
            decision.reason_codes,
        )

    def test_missing_required_quality_is_refused(self) -> None:
        data = make_recommend_input()
        quality = ComponentResult[QualityAssessment](
            status=ComponentStatus.OK,
            data=QualityAssessment(
                quality_prediction=None,
                prediction_lower=None,
                prediction_upper=None,
                violation_probability=None,
                data_confidence=DataConfidence.HIGH,
                warnings=["MODEL_UNAVAILABLE"],
            ),
        )
        decision = self.service.decide(replace(data, current_quality=quality))
        self.assertEqual(decision.decision, Decision.REFUSE)
        self.assertIn(
            ReasonCode.REFUSE_REQUIRED_QUALITY_MISSING.value,
            decision.reason_codes,
        )

    def test_unknown_reliability_is_refused_even_with_high_input_confidence(self) -> None:
        data = make_keep_input()
        reliability = ComponentResult[ReliabilityAssessment](
            status=ComponentStatus.OK,
            data=ReliabilityAssessment(
                reliability_risk=ReliabilityRisk.UNKNOWN,
                risk_score=None,
                data_confidence=DataConfidence.HIGH,
                source="REAL",
            ),
        )
        decision = self.service.decide(replace(data, current_reliability=reliability))
        self.assertEqual(decision.decision, Decision.REFUSE)
        self.assertIn(
            ReasonCode.REFUSE_REQUIRED_RELIABILITY_MISSING.value,
            decision.reason_codes,
        )

    def test_medium_confidence_keeps_safe_current_mode(self) -> None:
        data = make_recommend_input()
        quality = data.current_quality.data.model_copy(
            update={"data_confidence": DataConfidence.MEDIUM}
        )
        changed = replace(
            data,
            current_quality=ComponentResult(status=ComponentStatus.OK, data=quality),
            current_safety=ComponentResult(status=ComponentStatus.OK, data=safe()),
        )
        decision = self.service.decide(changed)
        self.assertEqual(decision.decision, Decision.KEEP)
        self.assertIn(
            ReasonCode.KEEP_CONFIDENCE_BELOW_RECOMMENDATION.value,
            decision.reason_codes,
        )

    def test_non_live_candidate_is_blocked_by_recommendation_guard(self) -> None:
        data = make_recommend_input()
        optimization = data.optimization.data.model_copy(
            update={"input_source": InputSource.SYNTHETIC}
        )
        changed = replace(
            data,
            current_safety=ComponentResult(status=ComponentStatus.OK, data=safe()),
            optimization=ComponentResult(status=ComponentStatus.OK, data=optimization),
        )
        decision = self.service.decide(changed)
        self.assertEqual(decision.decision, Decision.KEEP)
        self.assertIn(ReasonCode.KEEP_RECOMMENDATION_GUARD.value, decision.reason_codes)
        self.assertIn("NON_LIVE_INPUT", decision.reason_codes)

    def test_unsupported_reliability_candidate_cannot_be_recommended(self) -> None:
        data = make_recommend_input()
        scenarios = [
            item.model_copy(update={"candidate_controls_supported": False})
            for item in data.scenarios
        ]
        decision = self.service.decide(
            replace(
                data,
                scenarios=scenarios,
                current_safety=ComponentResult(status=ComponentStatus.OK, data=safe()),
            )
        )
        self.assertEqual(decision.decision, Decision.KEEP)
        self.assertIn("RELIABILITY_CONTROL_UNSUPPORTED", decision.reason_codes)

    def test_low_confidence_is_refused(self) -> None:
        data = make_keep_input()
        state = data.process_state.model_copy(
            update={"data_confidence": DataConfidence.LOW}
        )
        decision = self.service.decide(replace(data, process_state=state))
        self.assertEqual(decision.decision, Decision.REFUSE)
        self.assertIn(
            ReasonCode.REFUSE_LOW_DATA_CONFIDENCE.value,
            decision.reason_codes,
        )

    def test_optional_prediction_interval_can_be_absent(self) -> None:
        data = make_recommend_input()
        quality = data.current_quality.data.model_copy(
            update={"prediction_lower": None, "prediction_upper": None}
        )
        decision = self.service.decide(
            replace(
                data,
                current_quality=ComponentResult(
                    status=ComponentStatus.OK, data=quality
                ),
            )
        )
        self.assertEqual(decision.decision, Decision.RECOMMEND)

    def test_invalid_raw_payload_returns_refuse_instead_of_raising(self) -> None:
        payload = make_recommend_input().model_dump(mode="json")
        payload["current_quality"]["data"]["violation_probability"] = 3.0
        decision = self.service.decide_payload(payload)
        self.assertEqual(decision.decision, Decision.REFUSE)
        self.assertEqual(
            decision.reason_codes,
            [ReasonCode.REFUSE_CONTRACT_INVALID.value],
        )

    def test_trace_is_created(self) -> None:
        sink = InMemoryTraceSink()
        service = OrchestratorService(trace_sink=sink)
        decision = service.decide(make_recommend_input())
        self.assertEqual(len(sink.traces), 1)
        trace = sink.traces[0]
        self.assertEqual(trace.trace_id, decision.trace_id)
        self.assertEqual(trace.scenario_count, 1)
        self.assertEqual(trace.safe_scenario_count, 1)


if __name__ == "__main__":
    unittest.main()
