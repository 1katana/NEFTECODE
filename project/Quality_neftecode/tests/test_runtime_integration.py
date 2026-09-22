from __future__ import annotations

import sys
from datetime import timezone
from pathlib import Path

import pandas as pd

from quality_agent.contracts import DataConfidence, ProcessState, QualityAssessment
from quality_agent.router import QualityAgentRouter
from quality_agent.shadow import ShadowLogger
from quality_agent.state_adapter import ingest_process_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
PRIMARY = PROJECT_ROOT / "artifacts" / "experiments" / "H_full_pak_residual_oof_calibration"
FALLBACK = PROJECT_ROOT / "artifacts" / "experiments" / "C_telemetry_only"

sys.path.insert(0, str(WORKSPACE_ROOT / "orchestrator" / "src"))
from neftecode_orchestrator.contracts import QualityAssessment as OrchestratorQualityAssessment


def _state(router: QualityAgentRouter, timestamp: pd.Timestamp, step: int) -> ProcessState:
    telemetry: dict[str, float] = {}
    for source, signals in router.primary.schema.required_signals.items():
        if source not in {"avt", "hyd"}:
            continue
        for number, signal in enumerate(sorted(signals), start=1):
            telemetry[f"{source}_{signal.lower()}"] = 50.0 + number + step * 0.01
    sulfur = 8.0 + (step % 3) * 0.02
    return ProcessState(
        timestamp=timestamp.to_pydatetime().replace(tzinfo=timezone.utc),
        quality={
            "mg_sulfur": sulfur,
            "source": "pak",
            "pak_d15": 845.0 + (step % 2) * 0.01,
        },
        telemetry=telemetry,
        data_quality={"missing": [], "stale": [], "flatline": [], "outlier": []},
        data_confidence=DataConfidence.HIGH,
        current_controls={},
    )


def test_hybrid_router_shadow_and_orchestrator_contract(tmp_path) -> None:
    shadow_path = tmp_path / "shadow.jsonl"
    logger = ShadowLogger(shadow_path)
    router = QualityAgentRouter(
        PRIMARY,
        FALLBACK,
        point_policy="pak_passthrough",
        shadow_logger=logger,
    )
    timestamps = pd.date_range("2026-09-01 00:00", periods=37, freq="10min")
    for step, timestamp in enumerate(timestamps[:-1]):
        ingest_process_state(router.history, _state(router, timestamp, step))

    final_state = _state(router, timestamps[-1], len(timestamps) - 1)
    result = router.predict(final_state)

    expected_pak = float(final_state.quality["mg_sulfur"])
    assert result.quality_prediction == expected_pak
    assert result.violation_probability is not None
    assert result.prediction_lower is not None
    assert result.prediction_upper is not None
    assert result.prediction_lower <= expected_pak <= result.prediction_upper
    assert "POINT_ESTIMATE_PAK_PASSTHROUGH" in result.warnings
    assert QualityAssessment.model_validate(result.model_dump()) == result
    assert OrchestratorQualityAssessment.model_validate(result.model_dump())
    assert router.last_shadow_prediction_id is not None

    logger.log_lims(
        sample_timestamp=final_state.timestamp,
        sulfur_mg_kg=8.5,
        sample_id="integration-sample",
    )
    summary = logger.summary(tolerance_min=0.0)
    assert summary["prediction_events"] == 1
    assert summary["matched_samples"] == 1
    assert summary["metrics"]["selected"]["count"] == 1
    assert summary["metrics"]["primary"]["count"] == 1
    assert summary["metrics"]["telemetry_fallback"]["count"] == 1
