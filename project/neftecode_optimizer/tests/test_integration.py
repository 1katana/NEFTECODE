import json
from argparse import Namespace
from pathlib import Path

from optimization import AssessmentSource, OptimizationStatus
from optimization.cli import run

ROOT = Path(__file__).parents[1]


def test_mock_pipeline_runs_end_to_end_and_is_labeled() -> None:
    payload = run(
        Namespace(
            state=ROOT / "examples" / "mock_state.json",
            control_config=ROOT / "examples" / "mock_control_config.yaml",
            mock_config=ROOT / "examples" / "mock_assessments.yaml",
            output=None,
            max_candidates=100,
            max_changed_controls=2,
            safety_policy=ROOT / "examples" / "mock_safety_policy.yaml",
        )
    )

    result = json.loads(payload)
    assert result["status"] == OptimizationStatus.RECOMMEND
    assert result["best_candidate"]["candidate"]["candidate_id"] == "C001"
    assert result["best_candidate"]["quality"]["source"] == AssessmentSource.MOCK
    assert result["best_candidate"]["quality"]["product"] == "COMMERCIAL_DIESEL"
    assert result["uses_mock_assessments"] is True
    assert result["input_source"] == "SYNTHETIC"
    assert "NON_LIVE_INPUT:SYNTHETIC" in result["warnings"]
    assert "RELAXED_ACTION_POLICY" in result["warnings"]
    assert "CONTROL_RANGES_NOT_OPERATIONAL" in result["warnings"]
