from __future__ import annotations

import pandas as pd

from quality_agent.contracts import DataConfidence, ProcessState, QualityAssessment
from quality_agent.feature_pipeline import InMemoryHistoryProvider
from quality_agent.router import apply_pak_point_policy, assess_pak_sulfur_health


def _state(timestamp: str, data_quality: dict | None = None) -> ProcessState:
    return ProcessState(
        timestamp=pd.Timestamp(timestamp).to_pydatetime(),
        quality={},
        telemetry={},
        data_quality=data_quality or {"missing": [], "stale": [], "outlier": []},
        data_confidence=DataConfidence.HIGH,
    )


def test_pak_health_detects_suspect_and_invalid_flatline() -> None:
    history = InMemoryHistoryProvider()
    for timestamp in pd.date_range("2026-01-01 00:00", periods=7, freq="10min"):
        history.append("pak_mg_sulfur", timestamp, {"value": 7.5})

    suspect = assess_pak_sulfur_health(history, _state("2026-01-01 00:40"))
    invalid = assess_pak_sulfur_health(history, _state("2026-01-01 01:00"))

    assert suspect.status == "SUSPECT"
    assert suspect.flatline_age_min == 40.0
    assert invalid.status == "FLATLINE"
    assert invalid.flatline_age_min == 60.0


def test_pak_health_uses_explicit_upstream_missing_flag() -> None:
    health = assess_pak_sulfur_health(
        InMemoryHistoryProvider(),
        _state(
            "2026-01-01 01:00",
            {"missing": ["pak_mg_sulfur"], "stale": [], "outlier": []},
        ),
    )
    assert health.status == "MISSING"


def test_pak_health_detects_stale_last_timestamp() -> None:
    history = InMemoryHistoryProvider()
    history.append("pak_mg_sulfur", "2026-01-01 00:00", {"value": 7.5})
    health = assess_pak_sulfur_health(history, _state("2026-01-01 00:30"))
    assert health.status == "STALE"
    assert health.age_min == 30.0


def test_pak_health_temporarily_flags_a_large_recent_jump() -> None:
    history = InMemoryHistoryProvider()
    for timestamp, value in zip(
        pd.date_range("2026-01-01 00:00", periods=3, freq="10min"),
        [7.0, 7.2, 12.5],
        strict=True,
    ):
        history.append("pak_mg_sulfur", timestamp, {"value": value})

    health = assess_pak_sulfur_health(
        history,
        _state("2026-01-01 00:20"),
        jump_abs_threshold=4.0,
    )

    assert health.status == "JUMP_UNCONFIRMED"
    assert health.age_min == 0.0

    history.append("pak_mg_sulfur", "2026-01-01 00:30", {"value": 12.6})
    still_unconfirmed = assess_pak_sulfur_health(
        history,
        _state("2026-01-01 00:30"),
        jump_abs_threshold=4.0,
    )
    assert still_unconfirmed.status == "JUMP_UNCONFIRMED"

    history.append("pak_mg_sulfur", "2026-01-01 00:40", {"value": 12.7})
    confirmed = assess_pak_sulfur_health(
        history,
        _state("2026-01-01 00:40"),
        jump_abs_threshold=4.0,
    )
    assert confirmed.status == "OK"


def test_pak_passthrough_preserves_risk_and_expands_interval() -> None:
    model = QualityAssessment(
        quality_prediction=8.0,
        prediction_lower=7.0,
        prediction_upper=9.0,
        violation_probability=0.31,
        data_confidence=DataConfidence.HIGH,
        warnings=[],
    )

    result = apply_pak_point_policy(model, 10.5)

    assert result.quality_prediction == 10.5
    assert result.prediction_lower == 7.0
    assert result.prediction_upper == 10.5
    assert result.violation_probability == 0.31
    assert "POINT_ESTIMATE_PAK_PASSTHROUGH" in result.warnings


def test_pak_passthrough_leaves_missing_prediction_unchanged() -> None:
    unavailable = QualityAssessment(
        quality_prediction=None,
        violation_probability=None,
        data_confidence=DataConfidence.UNKNOWN,
        warnings=["INSUFFICIENT_INPUT"],
    )

    assert apply_pak_point_policy(unavailable, 8.0) is unavailable
