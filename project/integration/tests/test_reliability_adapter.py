from __future__ import annotations

import json
from pathlib import Path

import pytest
from neftecode_orchestrator.contracts import ProcessState
from neftecode_orchestrator.enums import AssessmentSource, DataConfidence, ReliabilityRisk

from neftecode_integration.reliability_adapter import LocalReliabilityAdapter

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def adapter():
    instance = LocalReliabilityAdapter(ROOT / "reliability_agent" / "policy.json")
    yield instance
    instance.close()


def example_state() -> ProcessState:
    sample = json.loads(
        (ROOT / "reliability_agent" / "examples" / "state.json").read_text(encoding="utf-8")
    )
    return ProcessState(
        timestamp=sample["timestamp"],
        quality={},
        telemetry=sample["telemetry"],
        data_quality={**sample["data_quality"], "missing": [], "telemetry_available": True},
        data_confidence=DataConfidence.HIGH,
        current_controls={"hyd_t6": sample["telemetry"]["hyd_t6"]},
    )


@pytest.mark.asyncio
async def test_current_state_uses_real_model_and_preserves_evidence(adapter) -> None:
    assessment = await adapter.evaluate_current(example_state())

    assert assessment.source is AssessmentSource.REAL
    assert assessment.model_version == "1.0.0"
    assert assessment.reliability_risk is ReliabilityRisk.LOW
    assert assessment.risk_score is not None
    assert assessment.assets["hyd_regime"]["status"] == "assessed"
    assert assessment.technology_limits_configured is False


def test_candidate_is_scored_as_static_proxy_and_unsupported_control_is_blocked(adapter) -> None:
    state = example_state()
    before = dict(state.telemetry)
    candidate = adapter.evaluate_candidate_sync(state, "C001", {"hyd_t6": 360.0})
    unsupported = adapter.evaluate_candidate_sync(state, "C002", {"hyd_f9": 220.0})

    assert candidate.risk_score is not None
    assert candidate.source is AssessmentSource.UNKNOWN
    assert candidate.candidate_controls_supported is False
    assert "UNCONFIRMED_CONTROL:hyd_t6" in candidate.warnings
    assert unsupported.reliability_risk is ReliabilityRisk.UNKNOWN
    assert unsupported.risk_score is None
    assert unsupported.candidate_controls_supported is False
    assert state.telemetry == before


@pytest.mark.asyncio
async def test_upstream_flatline_without_duration_lowers_confidence(adapter) -> None:
    state = example_state()
    state.data_quality["flatline"] = ["hyd_t6"]

    assessment = await adapter.evaluate_current(state)

    assert assessment.data_confidence is DataConfidence.LOW
    assert "UPSTREAM_FLATLINE_DURATION_UNKNOWN:hyd_t6" in assessment.warnings
