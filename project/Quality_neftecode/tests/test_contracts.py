from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from quality_agent.contracts import (
    CandidateAction,
    DataConfidence,
    ProcessState,
    QualityAssessment,
)


def test_state_roundtrip_uses_orchestrator_shape() -> None:
    state = ProcessState(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quality={"mg_sulfur": 9.0, "source": "pak"},
        telemetry={"hyd_t6": 342.0},
        data_quality={"missing": [], "stale": [], "outlier": []},
        data_confidence=DataConfidence.HIGH,
        current_controls={"hyd_t6": 342.0},
    )
    restored = ProcessState.model_validate_json(state.model_dump_json())
    assert restored == state


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProcessState.model_validate(
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "quality": {},
                "telemetry": {},
                "data_quality": {},
                "data_confidence": "HIGH",
                "unexpected": True,
            }
        )


def test_candidate_no_change_semantics() -> None:
    candidate = CandidateAction(candidate_id="NO_CHANGE", changes={}, delta={})
    assert candidate.is_no_change


def test_assessment_rejects_invalid_interval() -> None:
    with pytest.raises(ValidationError):
        QualityAssessment(
            quality_prediction=8.0,
            prediction_lower=9.0,
            prediction_upper=10.0,
            violation_probability=0.1,
            data_confidence=DataConfidence.HIGH,
        )
