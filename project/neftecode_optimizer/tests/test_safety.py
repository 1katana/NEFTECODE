from datetime import datetime, timezone

from optimization import (
    CandidateAction,
    ControlConfig,
    DataConfidence,
    ProcessState,
    ProductQualityMetrics,
    QualityAssessment,
    QualityProduct,
    ReliabilityAssessment,
    ReliabilityRisk,
    SafetyLayer,
    SafetyPolicy,
)

CONFIG = ControlConfig.model_validate(
    {
        "controls": {
            "confirmed": {
                "basis": "CONFIRMED_OPERATING",
                "min": 0,
                "max": 10,
                "step": 1,
                "max_delta": 2,
                "unit": "u",
            }
        }
    }
)
STATE = ProcessState(
    source="LIVE",
    timestamp=datetime.now(timezone.utc),
    values={"confirmed": 5, "other": 1},
)


def quality(**overrides: object) -> QualityAssessment:
    values = {
        "product": QualityProduct.COMMERCIAL_DIESEL,
        "quality_prediction": 8.0,
        "prediction_lower": 7.5,
        "prediction_upper": 9.0,
        "violation_probability": 0.05,
        "data_confidence": DataConfidence.HIGH,
        "source": "REAL",
    }
    values.update(overrides)
    return QualityAssessment.model_validate(values)


def reliability(**overrides: object) -> ReliabilityAssessment:
    values = {
        "reliability_risk": ReliabilityRisk.LOW,
        "risk_score": 0.1,
        "data_confidence": DataConfidence.HIGH,
        "warnings": [],
        "source": "REAL",
    }
    values.update(overrides)
    return ReliabilityAssessment.model_validate(values)


def test_sulfur_prediction_above_limit_is_rejected() -> None:
    result = SafetyLayer(CONFIG).evaluate(
        STATE,
        CandidateAction(candidate_id="KEEP"),
        quality(quality_prediction=10.1, prediction_upper=10.1),
        reliability(),
    )
    assert not result.constraint_passed
    assert "SULFUR_LIMIT" in result.violations


def test_upper_bound_policy_is_conservative() -> None:
    result = SafetyLayer(CONFIG).evaluate(
        STATE,
        CandidateAction(candidate_id="KEEP"),
        quality(quality_prediction=9.0, prediction_upper=10.01),
        reliability(),
    )
    assert "SULFUR_LIMIT" in result.violations


def test_hydrotreated_sulfur_cannot_prove_commercial_diesel_spec() -> None:
    layer = SafetyLayer(CONFIG)
    for product in (QualityProduct.HYDROTREATED_DIESEL, QualityProduct.UNKNOWN):
        result = layer.evaluate(
            STATE,
            CandidateAction(candidate_id="KEEP"),
            quality(product=product),
            reliability(),
        )
        assert "QUALITY_PRODUCT_NOT_COMMERCIAL_DIESEL" in result.violations


def test_low_confidence_and_critical_reliability_are_rejected() -> None:
    result = SafetyLayer(CONFIG).evaluate(
        STATE,
        CandidateAction(candidate_id="KEEP"),
        quality(data_confidence=DataConfidence.LOW),
        reliability(reliability_risk=ReliabilityRisk.CRITICAL),
    )
    assert {"LOW_QUALITY_CONFIDENCE", "RELIABILITY_RISK"} <= set(result.violations)


def test_unsupported_reliability_control_is_rejected_even_with_relaxed_assessment_policy() -> None:
    layer = SafetyLayer(CONFIG, SafetyPolicy(allow_unverified_assessments_for_actions=True))
    result = layer.evaluate(
        STATE,
        CandidateAction(candidate_id="C001", changes={"confirmed": 6}, deltas={"confirmed": 1}),
        quality(),
        reliability(candidate_controls_supported=False),
    )
    assert "RELIABILITY_CONTROL_UNSUPPORTED" in result.violations


def test_unknown_control_and_excessive_delta_are_rejected() -> None:
    layer = SafetyLayer(CONFIG)
    unknown = layer.evaluate(
        STATE,
        CandidateAction(candidate_id="X", changes={"other": 2}, deltas={"other": 1}),
        quality(),
        reliability(),
    )
    excessive = layer.evaluate(
        STATE,
        CandidateAction(
            candidate_id="Y", changes={"confirmed": 8}, deltas={"confirmed": 3}
        ),
        quality(),
        reliability(),
    )
    assert "UNKNOWN_CONTROL:other" in unknown.violations
    assert "MAX_DELTA:confirmed" in excessive.violations


def test_experimental_control_requires_explicit_opt_in() -> None:
    raw = CONFIG.model_dump(by_alias=True)
    raw["controls"]["confirmed"]["basis"] = "EXPERIMENTAL_MODEL"
    config = ControlConfig.model_validate(raw)
    candidate = CandidateAction(
        candidate_id="EXPERIMENT", changes={"confirmed": 6}, deltas={"confirmed": 1}
    )
    blocked = SafetyLayer(config).check_inputs(STATE, candidate)
    allowed = SafetyLayer(
        config, SafetyPolicy(allow_experimental_controls=True)
    ).check_inputs(STATE, candidate)
    assert "UNAPPROVED_CONTROL_BASIS:confirmed" in blocked.violations
    assert allowed.constraint_passed


def test_mock_control_requires_separate_opt_in() -> None:
    raw = CONFIG.model_dump(by_alias=True)
    raw["controls"]["confirmed"]["basis"] = "MOCK_FIXTURE"
    config = ControlConfig.model_validate(raw)
    candidate = CandidateAction(
        candidate_id="MOCK", changes={"confirmed": 6}, deltas={"confirmed": 1}
    )
    blocked = SafetyLayer(config).check_inputs(STATE, candidate)
    allowed = SafetyLayer(config, SafetyPolicy(allow_mock_controls=True)).check_inputs(
        STATE, candidate
    )
    assert "UNAPPROVED_CONTROL_BASIS:confirmed" in blocked.violations
    assert allowed.constraint_passed


def test_probability_threshold_is_only_applied_when_configured() -> None:
    policy = SafetyPolicy(max_violation_probability=0.1)
    result = SafetyLayer(CONFIG, policy).evaluate(
        STATE,
        CandidateAction(candidate_id="KEEP"),
        quality(violation_probability=0.11),
        reliability(),
    )
    assert "VIOLATION_PROBABILITY" in result.violations


def test_incomplete_quality_contract_is_rejected() -> None:
    result = SafetyLayer(CONFIG).evaluate(
        STATE,
        CandidateAction(candidate_id="KEEP"),
        quality(quality_prediction=None, prediction_lower=None, prediction_upper=None),
        reliability(),
    )
    assert {
        "MISSING_QUALITY_PREDICTION",
        "MISSING_PREDICTION_LOWER",
        "MISSING_PREDICTION_UPPER",
    } <= set(result.violations)


def test_commercial_quality_constraints_are_checked_together() -> None:
    policy = SafetyPolicy(require_commercial_metrics=True)
    metrics = ProductQualityMetrics(
        sulfur_mg_kg=11.0,
        t95_c=365.0,
        density_kg_m3=850.0,
        cetane_number=48.0,
        blend_share_sum_pct=95.0,
        additive_pct=3.1,
        relative_cost=4.0,
    )
    result = SafetyLayer(CONFIG, policy).evaluate(
        STATE,
        CandidateAction(candidate_id="KEEP"),
        quality(
            quality_prediction=11.0,
            prediction_lower=10.5,
            prediction_upper=11.5,
            grade="SUMMER",
            metrics=metrics,
        ),
        reliability(),
    )

    assert {
        "SULFUR_LIMIT",
        "T95_LIMIT",
        "DENSITY_LIMIT",
        "CETANE_LIMIT",
        "BLEND_SHARE_SUM",
        "ADDITIVE_LIMIT",
    } <= set(result.violations)
