from datetime import datetime, timezone

from quality_agent.confidence import compute_data_confidence
from quality_agent.contracts import DataConfidence, ProcessState
from quality_agent.feature_pipeline import FeatureDiagnostics


def _state(confidence=DataConfidence.HIGH) -> ProcessState:
    return ProcessState(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quality={"mg_sulfur": 8.0, "source": "pak"},
        telemetry={"hyd_t6": 342.0, "avt_t1": 130.0},
        data_quality={"missing": [], "stale": [], "outlier": []},
        data_confidence=confidence,
        current_controls={},
    )


def _diagnostics(coverage: float, history_hours: float = 6.0) -> FeatureDiagnostics:
    return FeatureDiagnostics(
        total_features=100,
        available_features=int(coverage * 100),
        coverage_ratio=coverage,
        missing_features=(),
        missing_sources=(),
        source_history_hours={
            "avt": history_hours,
            "hyd": history_hours,
            "pak_mg_sulfur": history_hours,
        },
    )


def test_high_when_upstream_and_features_are_good() -> None:
    assert compute_data_confidence(_state(), _diagnostics(0.95)) is DataConfidence.HIGH


def test_unknown_during_history_warmup() -> None:
    assert compute_data_confidence(_state(), _diagnostics(0.95, 1.0)) is DataConfidence.UNKNOWN


def test_feature_coverage_can_lower_confidence() -> None:
    assert compute_data_confidence(_state(), _diagnostics(0.80)) is DataConfidence.MEDIUM


def test_upstream_confidence_is_an_upper_bound() -> None:
    state = _state(DataConfidence.LOW)
    assert compute_data_confidence(state, _diagnostics(0.95)) is DataConfidence.LOW
