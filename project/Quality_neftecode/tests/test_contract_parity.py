from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "orchestrator" / "src"))

from neftecode_orchestrator.contracts import (
    CandidateAction as OrchestratorCandidateAction,
)
from neftecode_orchestrator.contracts import (
    ProcessState as OrchestratorProcessState,
)
from neftecode_orchestrator.contracts import (
    QualityAssessment as OrchestratorQualityAssessment,
)

from quality_agent.contracts import (
    CandidateAction,
    DataConfidence,
    ProcessState,
    QualityAssessment,
)


def test_process_state_contract_is_bidirectionally_compatible() -> None:
    local = ProcessState(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quality={"mg_sulfur": 8.0, "source": "pak"},
        telemetry={"hyd_t6": 342.0},
        data_quality={"missing": [], "stale": [], "outlier": []},
        data_confidence=DataConfidence.HIGH,
        current_controls={"hyd_t6": 342.0},
    )
    remote = OrchestratorProcessState.model_validate(local.model_dump(mode="python"))
    assert ProcessState.model_validate(remote.model_dump(mode="python")) == local


def test_candidate_contract_is_bidirectionally_compatible() -> None:
    local = CandidateAction(
        candidate_id="candidate-1", changes={"hyd_t6": 344.0}, delta={"hyd_t6": 2.0}
    )
    remote = OrchestratorCandidateAction.model_validate(local.model_dump(mode="python"))
    assert CandidateAction.model_validate(remote.model_dump(mode="python")) == local


def test_quality_assessment_contract_is_bidirectionally_compatible() -> None:
    local = QualityAssessment(
        quality_prediction=8.2,
        prediction_lower=7.5,
        prediction_upper=9.1,
        violation_probability=0.12,
        data_confidence=DataConfidence.HIGH,
        warnings=[],
    )
    remote = OrchestratorQualityAssessment.model_validate(local.model_dump(mode="python"))
    assert QualityAssessment.model_validate(remote.model_dump(mode="python")) == local
