from __future__ import annotations

import json
from pathlib import Path

import pytest

from quality_agent.contracts import CandidateAction, ProcessState, QualityAssessment
from quality_agent.features import FeatureConfig

FIXTURES = sorted(Path("fixtures").glob("*.json"))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = sorted((PROJECT_ROOT / "fixtures").glob("*.json"))
ARTIFACTS = PROJECT_ROOT / "artifacts" / "experiments" / "H_full_pak_residual_oof_calibration"


@pytest.mark.parametrize("path", FIXTURES, ids=[path.stem for path in FIXTURES])
def test_fixture_inputs_match_contract(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    ProcessState.model_validate(data["state"])
    if data.get("candidate") is not None:
        CandidateAction.model_validate(data["candidate"])


@pytest.mark.parametrize("path", FIXTURES, ids=[path.stem for path in FIXTURES])
def test_fixture_agent_response_contract(path: Path) -> None:
    from quality_agent.agent import QualityAgent

    data = json.loads(path.read_text(encoding="utf-8"))
    state = ProcessState.model_validate(data["state"])
    candidate = (
        CandidateAction.model_validate(data["candidate"])
        if data.get("candidate") is not None
        else None
    )
    result = QualityAgent(ARTIFACTS, FeatureConfig()).predict(state, candidate)
    assert isinstance(QualityAssessment.model_validate(result.model_dump()), QualityAssessment)

    expected = data.get("expected_until_candidate_model_exists") or data.get("expected")
    if expected:
        for warning in expected.get("warnings", []):
            assert warning in result.warnings
