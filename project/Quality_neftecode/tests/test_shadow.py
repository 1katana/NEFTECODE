from __future__ import annotations

import json

from quality_agent.contracts import DataConfidence, QualityAssessment
from quality_agent.feature_pipeline import FeatureDiagnostics
from quality_agent.router import PakHealthAssessment
from quality_agent.shadow import (
    ShadowLogger,
    ShadowPromotionGates,
    evaluate_shadow_readiness,
)


def _assessment(value: float, probability: float = 0.2) -> QualityAssessment:
    return QualityAssessment(
        quality_prediction=value,
        prediction_lower=value - 1,
        prediction_upper=value + 1,
        violation_probability=probability,
        data_confidence=DataConfidence.HIGH,
        warnings=[],
    )


def _log_prediction(logger: ShadowLogger, timestamp: str, value: float) -> str:
    return logger.log_prediction(
        timestamp=__import__("pandas").Timestamp(timestamp).to_pydatetime(),
        candidate=None,
        pak_health=PakHealthAssessment("OK", 0.0, 0.0),
        point_source="pak",
        pak_value=value,
        selected=_assessment(value),
        primary=_assessment(value + 0.5),
        telemetry_fallback=_assessment(value + 1.0),
        feature_values={"finite": 1.0, "missing": float("nan")},
        feature_diagnostics=FeatureDiagnostics(2, 1, 0.5, ("missing",), (), {"avt": 6.0}),
        primary_manifest={"training_id": "primary"},
        fallback_manifest={"training_id": "fallback"},
    )


def test_shadow_log_serializes_nonfinite_features_as_null(tmp_path) -> None:
    path = tmp_path / "shadow.jsonl"
    logger = ShadowLogger(path)
    prediction_id = _log_prediction(logger, "2026-01-01T10:00:00Z", 8.0)

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["prediction_id"] == prediction_id
    assert event["feature_values"]["missing"] is None


def test_shadow_summary_matches_only_prediction_at_or_before_lims(tmp_path) -> None:
    logger = ShadowLogger(tmp_path / "shadow.jsonl")
    _log_prediction(logger, "2026-01-01T10:00:00Z", 8.0)
    _log_prediction(logger, "2026-01-01T10:20:00Z", 20.0)
    logger.log_lims(
        sample_timestamp="2026-01-01T10:05:00Z",
        sulfur_mg_kg=9.0,
        sample_id="sample-1",
    )

    summary = logger.summary(tolerance_min=10.0)

    assert summary["matched_samples"] == 1
    assert summary["metrics"]["selected"]["mae"] == 1.0
    assert summary["metrics"]["pak"]["mae"] == 1.0
    assert summary["classification"]["count"] == 1
    assert summary["classification"]["prevalence_brier"] == 0.0
    assert summary["interval"]["coverage"] == 1.0


def test_shadow_summary_does_not_use_future_prediction(tmp_path) -> None:
    logger = ShadowLogger(tmp_path / "shadow.jsonl")
    _log_prediction(logger, "2026-01-01T10:00:00Z", 8.0)
    logger.log_lims(sample_timestamp="2026-01-01T09:59:00Z", sulfur_mg_kg=9.0)

    assert logger.summary(tolerance_min=10.0)["matched_samples"] == 0


def test_shadow_readiness_stays_insufficient_until_evidence_gates_pass() -> None:
    result = evaluate_shadow_readiness(
        {"matched_samples": 12},
        ShadowPromotionGates(
            minimum_matched_samples=100,
            minimum_observation_days=30,
            minimum_fallback_samples=5,
        ),
    )

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["automatic_promotion"] is False


def test_shadow_readiness_requires_all_quality_gates() -> None:
    summary = {
        "matched_samples": 120,
        "observation_period": {"days": 90.0},
        "by_point_source": {"telemetry_fallback": {"count": 25}},
        "metrics": {"selected": {"mae": 1.0}, "pak": {"mae": 1.1}},
        "classification": {"brier": 0.1, "prevalence_brier": 0.15},
        "interval": {"coverage": 0.8},
    }
    gates = ShadowPromotionGates()

    ready = evaluate_shadow_readiness(summary, gates)
    failed = evaluate_shadow_readiness(
        {**summary, "interval": {"coverage": 0.6}},
        gates,
    )

    assert ready["status"] == "READY_FOR_REVIEW"
    assert ready["automatic_promotion"] is False
    assert failed["status"] == "NOT_READY"
