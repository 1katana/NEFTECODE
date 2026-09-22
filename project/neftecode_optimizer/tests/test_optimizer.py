from datetime import datetime, timezone

from optimization import (
    ControlConfig,
    DataConfidence,
    InputSource,
    OptimizationStatus,
    Optimizer,
    ProcessState,
    ProductQualityMetrics,
    QualityAssessment,
    QualityProduct,
    ReliabilityAssessment,
    ReliabilityRisk,
)

CONFIG = ControlConfig.model_validate(
    {
        "controls": {
            "control": {
                "basis": "CONFIRMED_OPERATING",
                "min": 0,
                "max": 10,
                "step": 1,
                "max_delta": 1,
                "unit": "u",
            }
        }
    }
)
STATE = ProcessState(
    source=InputSource.LIVE, timestamp=datetime.now(timezone.utc), values={"control": 5}
)


class QualityFake:
    def __init__(self, probabilities: dict[str, float], sulfur: float = 8.0) -> None:
        self.probabilities = probabilities
        self.sulfur = sulfur

    def predict(self, state, candidate) -> QualityAssessment:
        return QualityAssessment(
            product=QualityProduct.COMMERCIAL_DIESEL,
            quality_prediction=self.sulfur,
            prediction_lower=self.sulfur - 0.5,
            prediction_upper=self.sulfur + 0.5,
            violation_probability=self.probabilities.get(candidate.candidate_id, 0.2),
            data_confidence=DataConfidence.HIGH,
            source="REAL",
        )


class ReliabilityFake:
    def evaluate(self, state, candidate) -> ReliabilityAssessment:
        return ReliabilityAssessment(
            reliability_risk=ReliabilityRisk.LOW,
            risk_score=0.1,
            data_confidence=DataConfidence.HIGH,
            warnings=[],
            source="REAL",
        )


def optimizer(probabilities: dict[str, float], sulfur: float = 8.0) -> Optimizer:
    return Optimizer(
        quality_agent=QualityFake(probabilities, sulfur),
        reliability_agent=ReliabilityFake(),
        control_config=CONFIG,
    )


def test_safe_candidates_are_ranked_by_violation_probability() -> None:
    result = optimizer({"KEEP": 0.2, "C001": 0.01, "C002": 0.1}).search(STATE)
    assert result.status == OptimizationStatus.RECOMMEND
    assert result.best_candidate is not None
    assert result.best_candidate.candidate.candidate_id == "C001"
    assert [item.rank for item in result.ranked_candidates] == [1, 2, 3]
    assert result.best_candidate.rank == 1
    assert all(item.score is None for item in result.ranked_candidates)


def test_keep_can_win() -> None:
    result = optimizer({"KEEP": 0.01, "C001": 0.1, "C002": 0.2}).search(STATE)
    assert result.status == OptimizationStatus.KEEP
    assert result.best_candidate is not None
    assert result.best_candidate.candidate.is_keep


def test_relative_blend_cost_breaks_equal_risk_tie() -> None:
    class CostAwareQuality(QualityFake):
        def predict(self, state, candidate) -> QualityAssessment:
            assessment = super().predict(state, candidate)
            costs = {"KEEP": 3.2, "C001": 1.1, "C002": 2.0}
            return assessment.model_copy(
                update={
                    "grade": "SUMMER",
                    "metrics": ProductQualityMetrics(
                        sulfur_mg_kg=8.0,
                        t95_c=350.0,
                        density_kg_m3=835.0,
                        cetane_number=52.0,
                        blend_share_sum_pct=100.0,
                        additive_pct=0.0,
                        relative_cost=costs[candidate.candidate_id],
                    ),
                }
            )

    result = Optimizer(
        quality_agent=CostAwareQuality({"KEEP": 0.1, "C001": 0.1, "C002": 0.1}),
        reliability_agent=ReliabilityFake(),
        control_config=CONFIG,
    ).search(STATE)

    assert result.best_candidate is not None
    assert result.best_candidate.candidate.candidate_id == "C001"
    assert result.best_candidate.score_components["relative_cost"] == 1.1


def test_all_rejected_returns_no_feasible_solution() -> None:
    result = optimizer({}, sulfur=11.0).search(STATE)
    assert result.status == OptimizationStatus.NO_FEASIBLE_SOLUTION
    assert result.best_candidate is None
    assert result.ranked_candidates == []
    assert len(result.rejected_candidates) == 3
    assert any("SULFUR_LIMIT" in reason for reason in result.reasons)


def test_same_input_is_reproducible() -> None:
    subject = optimizer({"KEEP": 0.2, "C001": 0.01, "C002": 0.1})
    assert subject.search(STATE) == subject.search(STATE)


def test_synthetic_input_is_visible_and_cannot_recommend_by_default() -> None:
    synthetic = STATE.model_copy(update={"source": InputSource.SYNTHETIC})
    result = optimizer({"KEEP": 0.2, "C001": 0.01, "C002": 0.1}).search(synthetic)
    assert result.status == OptimizationStatus.KEEP
    assert result.input_source == InputSource.SYNTHETIC
    assert "NON_LIVE_INPUT:SYNTHETIC" in result.warnings
    assert all(
        "NON_LIVE_ACTION_NOT_ALLOWED" in item.safety.violations
        for item in result.rejected_candidates
    )


def test_unknown_agent_provenance_cannot_recommend_live_action() -> None:
    class UnknownQuality(QualityFake):
        def predict(self, state, candidate):
            return (
                super()
                .predict(state, candidate)
                .model_copy(update={"source": "UNKNOWN"})
            )

    result = Optimizer(
        quality_agent=UnknownQuality({"KEEP": 0.2, "C001": 0.01, "C002": 0.1}),
        reliability_agent=ReliabilityFake(),
        control_config=CONFIG,
    ).search(STATE)
    assert result.status == OptimizationStatus.KEEP
    assert all(
        "UNVERIFIED_ASSESSMENT_FOR_ACTION" in item.safety.violations
        for item in result.rejected_candidates
    )


class BrokenQualityAgent:
    def predict(self, state, candidate):
        raise RuntimeError("agent unavailable")


class DictQualityAgent:
    def predict(self, state, candidate):
        return {
            "product": "COMMERCIAL_DIESEL",
            "source": "REAL",
            "quality_prediction": 8.0,
            "prediction_lower": 7.5,
            "prediction_upper": 8.5,
            "violation_probability": 0.05,
            "data_confidence": "HIGH",
        }


def test_agent_failure_is_fail_closed() -> None:
    subject = Optimizer(
        quality_agent=BrokenQualityAgent(),
        reliability_agent=ReliabilityFake(),
        control_config=CONFIG,
    )
    result = subject.search(STATE)
    assert result.status == OptimizationStatus.NO_FEASIBLE_SOLUTION
    assert all("QUALITY_AGENT_ERROR" in reason for reason in result.reasons)
    assert len(result.agent_failures) == 3
    assert all(failure.agent == "quality" for failure in result.agent_failures)


def test_plain_dict_agent_response_is_validated_at_boundary() -> None:
    subject = Optimizer(
        quality_agent=DictQualityAgent(),
        reliability_agent=ReliabilityFake(),
        control_config=CONFIG,
    )
    assert subject.search(STATE).status == OptimizationStatus.KEEP
