from __future__ import annotations

import asyncio
import json
from pathlib import Path

from neftecode_orchestrator.contracts import (
    ProcessState,
    QualityAssessment,
    ReliabilityAssessment,
)
from neftecode_orchestrator.enums import (
    AssessmentSource,
    DataConfidence,
    InputSource,
    OptimizationStatus,
    QualityProduct,
    ReliabilityRisk,
)

from neftecode_integration.optimizer_adapter import LocalOptimizerAdapter
from neftecode_integration.reliability_adapter import LocalReliabilityAdapter


class CandidateQuality:
    def __init__(self, assessment: QualityAssessment) -> None:
        self.assessment = assessment

    def evaluate_candidate_sync(self, state, candidate) -> QualityAssessment:
        del state, candidate
        return self.assessment


def _quality() -> QualityAssessment:
    return QualityAssessment(
        quality_prediction=5.0,
        prediction_lower=4.0,
        prediction_upper=6.0,
        violation_probability=0.05,
        data_confidence=DataConfidence.HIGH,
        product=QualityProduct.COMMERCIAL_DIESEL,
        source=AssessmentSource.REAL,
        model_version="quality-test-v1",
    )


def _reliability() -> ReliabilityAssessment:
    return ReliabilityAssessment(
        reliability_risk=ReliabilityRisk.LOW,
        risk_score=0.1,
        data_confidence=DataConfidence.HIGH,
        source=AssessmentSource.REAL,
        model_version="reliability-test-v1",
    )


def _write_configs(tmp_path: Path, controls: str) -> tuple[Path, Path]:
    control_path = tmp_path / "controls.yaml"
    control_path.write_text(controls, encoding="utf-8")
    safety_path = tmp_path / "safety.yaml"
    safety_path.write_text(
        "sulfur_limit_mg_kg: 10\n"
        "use_prediction_upper: true\n"
        "rejected_confidences: [LOW]\n"
        "rejected_reliability_risks: [CRITICAL]\n",
        encoding="utf-8",
    )
    return control_path, safety_path


def test_keep_is_projected_as_no_change_without_inventing_score(tmp_path: Path) -> None:
    controls, safety = _write_configs(tmp_path, "controls: {}\n")
    quality = _quality()
    adapter = LocalOptimizerAdapter(
        quality_adapter=CandidateQuality(quality),  # type: ignore[arg-type]
        control_config=str(controls),
        safety_policy=str(safety),
    )
    try:
        projection = adapter._optimize_sync(
            ProcessState(
                timestamp="2026-09-20T10:00:00Z",
                quality={},
                telemetry={},
                data_quality={"missing": []},
                data_confidence=DataConfidence.HIGH,
                current_controls={},
            ),
            InputSource.LIVE,
            quality,
            _reliability(),
        )
    finally:
        adapter.close()

    assert projection.optimization.status is OptimizationStatus.SUCCESS
    assert projection.optimization.ranked_candidates[0].candidate.candidate_id == "NO_CHANGE"
    assert projection.optimization.ranked_candidates[0].score is None
    assert projection.current_safety is not None
    assert projection.current_safety.constraint_passed is True
    assert projection.scenarios[0].candidate.candidate_id == "NO_CHANGE"


def test_current_controls_override_duplicated_telemetry(tmp_path: Path) -> None:
    controls, safety = _write_configs(
        tmp_path,
        "controls:\n"
        "  hyd_t6:\n"
        "    basis: CONFIRMED_OPERATING\n"
        "    min: 0\n"
        "    max: 10\n"
        "    step: 1\n"
        "    max_delta: 2\n"
        "    unit: degC\n",
    )
    quality = _quality()
    adapter = LocalOptimizerAdapter(
        quality_adapter=CandidateQuality(quality),  # type: ignore[arg-type]
        control_config=str(controls),
        safety_policy=str(safety),
        max_candidates=3,
        max_changed_controls=1,
    )
    try:
        projection = adapter._optimize_sync(
            ProcessState(
                timestamp="2026-09-20T10:00:00Z",
                quality={},
                telemetry={"hyd_t6": 3.0},
                data_quality={"missing": []},
                data_confidence=DataConfidence.HIGH,
                current_controls={"hyd_t6": 5.0},
            ),
            InputSource.LIVE,
            quality,
            _reliability(),
        )
    finally:
        adapter.close()

    first_change = next(
        scenario for scenario in projection.scenarios if scenario.candidate.candidate_id == "C001"
    )
    assert first_change.candidate.changes == {"hyd_t6": 4.0}
    assert first_change.candidate.delta == {"hyd_t6": -1.0}
    assert "UNVERIFIED_ASSESSMENT_FOR_ACTION" in first_change.violations


def test_real_reliability_candidate_scores_reach_safety_and_scenarios(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    sample = json.loads(
        (root / "reliability_agent" / "examples" / "state.json").read_text(encoding="utf-8")
    )
    state = ProcessState(
        timestamp=sample["timestamp"],
        quality={},
        telemetry=sample["telemetry"],
        data_quality=sample["data_quality"],
        data_confidence=DataConfidence.HIGH,
        current_controls={"hyd_t6": sample["telemetry"]["hyd_t6"]},
    )
    controls, safety = _write_configs(
        tmp_path,
        "controls:\n"
        "  hyd_t6:\n"
        "    basis: CONFIRMED_OPERATING\n"
        "    min: 350\n"
        "    max: 370\n"
        "    step: 1\n"
        "    max_delta: 2\n"
        "    unit: degC\n",
    )
    reliability_adapter = LocalReliabilityAdapter(root / "reliability_agent" / "policy.json")
    quality = _quality()
    optimizer = LocalOptimizerAdapter(
        quality_adapter=CandidateQuality(quality),  # type: ignore[arg-type]
        reliability_adapter=reliability_adapter,
        control_config=str(controls),
        safety_policy=str(safety),
        max_candidates=3,
    )
    try:
        current = asyncio.run(reliability_adapter.evaluate_current(state))
        projection = optimizer._optimize_sync(state, InputSource.LIVE, quality, current)
    finally:
        optimizer.close()
        reliability_adapter.close()

    changed = [item for item in projection.scenarios if item.candidate.changes]
    assert changed
    for scenario in changed:
        assert scenario.reliability_risk_score is not None
        assert scenario.reliability_source is AssessmentSource.UNKNOWN
        assert scenario.candidate_controls_supported is False
        assert "RELIABILITY_CONTROL_UNSUPPORTED" in scenario.violations
