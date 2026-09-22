from __future__ import annotations

from quality_agent.blending import assess_commercial_blend
from quality_agent.contracts import (
    CandidateAction,
    DataConfidence,
    ProcessState,
    QualityAssessment,
)
from quality_agent.counterfactual import CandidateEffectConfig, apply_candidate_effect


def _state() -> ProcessState:
    return ProcessState(
        timestamp="2026-09-20T12:00:00Z",
        quality={
            "blending": {
                "grade": "SUMMER",
                "components": [
                    {
                        "name": "hydrotreated",
                        "share_pct": 80,
                        "share_control": "blend_hydrotreated_share_pct",
                        "use_hydrotreated_sulfur": True,
                        "t95_c": 350,
                        "density_kg_m3": 835,
                        "cetane_number": 50,
                    },
                    {
                        "name": "tank_b",
                        "share_pct": 20,
                        "share_control": "blend_low_sulfur_share_pct",
                        "sulfur_mg_kg": 2,
                        "t95_c": 345,
                        "density_kg_m3": 825,
                        "cetane_number": 55,
                        "relative_cost": 1.08,
                    },
                ],
            }
        },
        telemetry={"hyd_t6": 362.0, "hyd_f9": 218.0, "hyd_p13": 3.9},
        current_controls={"hyd_t6": 362.0, "hyd_f9": 218.0, "hyd_p13": 3.9},
        data_quality={},
        data_confidence=DataConfidence.HIGH,
    )


def _hydro() -> QualityAssessment:
    return QualityAssessment(
        quality_prediction=8.0,
        prediction_lower=7.0,
        prediction_upper=9.0,
        violation_probability=0.1,
        data_confidence=DataConfidence.HIGH,
    )


def test_candidate_effect_uses_confirmed_tags_and_horizon() -> None:
    state = _state()
    one_hour = apply_candidate_effect(
        _hydro(),
        state,
        CandidateAction(
            candidate_id="T6_PLUS_5",
            changes={"hyd_t6": 367.0},
            delta={"hyd_t6": 5.0},
            horizon_hours=1.0,
        ),
        CandidateEffectConfig(),
    )
    three_hours = apply_candidate_effect(
        _hydro(),
        state,
        CandidateAction(
            candidate_id="T6_PLUS_5",
            changes={"hyd_t6": 367.0},
            delta={"hyd_t6": 5.0},
            horizon_hours=3.0,
        ),
        CandidateEffectConfig(),
    )

    assert 0 < three_hours.quality_prediction < one_hour.quality_prediction < 8.0
    assert one_hour.candidate_horizon_hours == 1.0
    assert "CANDIDATE_MODEL_NOT_READY" not in one_hour.warnings


def test_linear_blend_produces_all_commercial_metrics() -> None:
    result = assess_commercial_blend(_hydro(), _state())

    assert result.product.value == "COMMERCIAL_DIESEL"
    assert result.grade == "SUMMER"
    assert result.quality_prediction == 6.8
    assert result.metrics is not None
    assert result.metrics.t95_c == 349.0
    assert result.metrics.density_kg_m3 == 833.0
    assert result.metrics.cetane_number == 51.0
    assert result.metrics.blend_share_sum_pct == 100.0
