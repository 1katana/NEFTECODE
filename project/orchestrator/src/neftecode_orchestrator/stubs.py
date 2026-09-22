"""Temporary fixtures that emulate agreed outputs of external components.

Delete this module after the shared contract package and real adapters are ready.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .contracts import (
    CandidateAction,
    ComponentResult,
    OptimizationResult,
    OrchestratorInput,
    ProcessState,
    QualityAssessment,
    RankedCandidate,
    ReliabilityAssessment,
    SafetyResult,
    ScenarioEvaluation,
)
from .enums import (
    ComponentStatus,
    DataConfidence,
    InputSource,
    OptimizationStatus,
    ReliabilityRisk,
)


def process_state() -> ProcessState:
    return ProcessState(
        timestamp=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
        quality={"mg_sulfur": 11.2, "source": "pak"},
        telemetry={"hyd_t6": 342.0, "hyd_f9": 218.0, "hyd_p13": 3.9},
        data_quality={"missing": [], "stale": [], "outlier": []},
        data_confidence=DataConfidence.HIGH,
        current_controls={"hyd_t6": 342.0, "hyd_f9": 218.0, "hyd_p13": 3.9},
    )


def quality(
    prediction: float | None = 11.2,
    probability: float | None = 0.68,
    confidence: DataConfidence | float = DataConfidence.HIGH,
) -> QualityAssessment:
    return QualityAssessment(
        quality_prediction=prediction,
        prediction_lower=10.4 if prediction is not None else None,
        prediction_upper=12.0 if prediction is not None else None,
        violation_probability=probability,
        data_confidence=confidence,
        warnings=[],
    )


def reliability(
    risk: ReliabilityRisk = ReliabilityRisk.MEDIUM,
    score: float = 0.45,
    confidence: DataConfidence | float = DataConfidence.HIGH,
) -> ReliabilityAssessment:
    return ReliabilityAssessment(
        reliability_risk=risk,
        risk_score=score,
        data_confidence=confidence,
        warnings=[],
        risk_factors=["MODE_NEAR_QUALITY_LIMIT"]
        if risk is not ReliabilityRisk.LOW
        else [],
    )


def ok(data):
    return ComponentResult(status=ComponentStatus.OK, data=data, latency_ms=12)


def safe() -> SafetyResult:
    return SafetyResult(constraint_passed=True, violations=[])


def unsafe(*violations: str) -> SafetyResult:
    values = list(violations) or ["UNSPECIFIED_SAFETY_REJECTION"]
    return SafetyResult(
        constraint_passed=False,
        violations=values,
        rejection_reason=", ".join(values),
    )


def make_recommend_input() -> OrchestratorInput:
    candidate = CandidateAction(
        candidate_id="CANDIDATE_001",
        changes={"hyd_t6": 345.0, "hyd_f9": 216.0, "hyd_p13": 3.92},
        delta={"hyd_t6": 3.0, "hyd_f9": -2.0, "hyd_p13": 0.02},
    )
    scenario = ScenarioEvaluation(
        candidate=candidate,
        quality_prediction=8.8,
        violation_probability=0.09,
        reliability_risk=ReliabilityRisk.LOW,
        constraint_passed=True,
        violations=[],
        score=0.82,
        candidate_horizon_hours=candidate.horizon_hours,
    )
    optimization = OptimizationResult(
        status=OptimizationStatus.SUCCESS,
        ranked_candidates=[
            RankedCandidate(
                rank=1,
                score=0.82,
                score_components={
                    "quality": 0.55,
                    "reliability": 0.20,
                    "change_penalty": -0.07,
                },
                candidate=candidate,
            )
        ],
        reasons=[],
        input_source=InputSource.LIVE,
    )
    return OrchestratorInput(
        schema_version="1.0.0",
        run_id="demo-recommend-001",
        process_state=process_state(),
        current_quality=ok(quality()),
        current_reliability=ok(reliability()),
        current_safety=ok(unsafe("SULFUR_LIMIT")),
        scenarios=[scenario],
        optimization=ok(optimization),
    )


def make_keep_input() -> OrchestratorInput:
    state = process_state().model_copy(
        update={
            "quality": {"mg_sulfur": 6.7, "source": "lims"},
            "data_confidence": DataConfidence.HIGH,
        }
    )
    no_feasible = OptimizationResult(
        status=OptimizationStatus.NO_FEASIBLE_SOLUTION,
        ranked_candidates=[],
        reasons=["NO_BETTER_SAFE_ACTION"],
        input_source=InputSource.LIVE,
    )
    return OrchestratorInput(
        schema_version="1.0.0",
        run_id="demo-keep-001",
        process_state=state,
        current_quality=ok(
            QualityAssessment(
                quality_prediction=6.7,
                prediction_lower=6.2,
                prediction_upper=7.3,
                violation_probability=0.02,
                data_confidence=DataConfidence.HIGH,
                warnings=[],
            )
        ),
        current_reliability=ok(reliability(risk=ReliabilityRisk.LOW, score=0.12)),
        current_safety=ok(safe()),
        scenarios=[],
        optimization=ok(no_feasible),
    )


def make_refuse_input() -> OrchestratorInput:
    no_feasible = OptimizationResult(
        status=OptimizationStatus.NO_FEASIBLE_SOLUTION,
        ranked_candidates=[],
        reasons=["ALL_CANDIDATES_REJECTED"],
        input_source=InputSource.LIVE,
    )
    return OrchestratorInput(
        schema_version="1.0.0",
        run_id="demo-refuse-001",
        process_state=process_state(),
        current_quality=ok(quality()),
        current_reliability=ok(reliability(risk=ReliabilityRisk.HIGH, score=0.91)),
        current_safety=ok(unsafe("SULFUR_LIMIT", "RELIABILITY_LIMIT")),
        scenarios=[],
        optimization=ok(no_feasible),
    )


def make_no_change_input() -> OrchestratorInput:
    base = make_keep_input()
    candidate = CandidateAction(candidate_id="NO_CHANGE", changes={}, delta={})
    scenario = ScenarioEvaluation(
        candidate=candidate,
        quality_prediction=6.7,
        violation_probability=0.02,
        reliability_risk=ReliabilityRisk.LOW,
        constraint_passed=True,
        violations=[],
        score=0.91,
    )
    optimization = OptimizationResult(
        status=OptimizationStatus.SUCCESS,
        ranked_candidates=[
            RankedCandidate(
                rank=1,
                score=0.91,
                score_components={"quality": 0.70, "reliability": 0.21},
                candidate=candidate,
            )
        ],
        reasons=["NO_CHANGE_IS_BEST"],
        input_source=InputSource.LIVE,
    )
    payload = base.model_dump(mode="python")
    payload["run_id"] = "demo-no-change-001"
    payload["scenarios"] = [scenario]
    payload["optimization"] = ok(optimization)
    return OrchestratorInput.model_validate(payload)


def make_medium_confidence_input() -> OrchestratorInput:
    base = make_recommend_input()
    payload = base.model_dump(mode="python")
    payload["run_id"] = "demo-medium-confidence-001"
    payload["process_state"]["quality"]["mg_sulfur"] = 8.9
    payload["current_quality"]["data"]["data_confidence"] = DataConfidence.MEDIUM
    payload["current_safety"] = ok(safe())
    return OrchestratorInput.model_validate(payload)


def make_low_confidence_input() -> OrchestratorInput:
    base = make_keep_input()
    payload = base.model_dump(mode="python")
    payload["run_id"] = "demo-low-confidence-001"
    payload["process_state"]["data_confidence"] = DataConfidence.LOW
    return OrchestratorInput.model_validate(payload)


def make_missing_quality_input() -> OrchestratorInput:
    base = make_recommend_input()
    payload = base.model_dump(mode="python")
    payload["run_id"] = "demo-missing-quality-001"
    payload["current_quality"] = ok(
        QualityAssessment(
            quality_prediction=None,
            prediction_lower=None,
            prediction_upper=None,
            violation_probability=None,
            data_confidence=DataConfidence.HIGH,
            warnings=["MODEL_DID_NOT_RETURN_PREDICTION"],
        )
    )
    return OrchestratorInput.model_validate(payload)


def make_quality_timeout_input() -> OrchestratorInput:
    base = make_recommend_input()
    payload = base.model_dump(mode="python")
    payload["run_id"] = "demo-quality-timeout-001"
    payload["current_quality"] = ComponentResult[QualityAssessment](
        status=ComponentStatus.TIMEOUT,
        error_code="QUALITY_TIMEOUT",
        message="QualityAgent did not respond within the configured timeout",
        latency_ms=2000,
    )
    return OrchestratorInput.model_validate(payload)
