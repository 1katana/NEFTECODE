import json
from pathlib import Path

from quality_agent.contracts import CandidateAction, ProcessState, QualityAssessment
from quality_agent.features import FeatureConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = PROJECT_ROOT / "artifacts" / "experiments" / "H_full_pak_residual_oof_calibration"


def _fixture(name: str) -> dict:
    return json.loads((PROJECT_ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def test_predict_returns_strict_contract() -> None:
    from quality_agent.agent import QualityAgent

    data = _fixture("normal.json")
    agent = QualityAgent(ARTIFACTS, FeatureConfig())
    result = agent.predict(
        ProcessState.model_validate(data["state"]),
        CandidateAction.model_validate(data["candidate"]),
    )
    assert QualityAssessment.model_validate(result.model_dump()) == result


def test_changing_candidate_has_explicit_horizon_even_when_history_is_insufficient() -> None:
    from quality_agent.agent import QualityAgent

    data = _fixture("risky.json")
    result = QualityAgent(ARTIFACTS, FeatureConfig()).predict(
        ProcessState.model_validate(data["state"]),
        CandidateAction.model_validate(data["candidate"]),
    )
    assert result.quality_prediction is None
    assert result.violation_probability is None
    assert result.candidate_horizon_hours == 1.0
    assert "CANDIDATE_MODEL_NOT_READY" not in result.warnings
    assert "EXPERIMENTAL_LINEAR_COUNTERFACTUAL" in result.warnings
