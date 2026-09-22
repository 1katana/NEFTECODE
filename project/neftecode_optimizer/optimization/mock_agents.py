"""Explicit, table-driven agent mocks for integration testing only."""

from __future__ import annotations

from pathlib import Path

from .configuration import load_yaml_mapping
from pydantic import Field

from .models import (
    AssessmentSource,
    CandidateAction,
    FrozenModel,
    ProcessState,
    QualityAssessment,
    ReliabilityAssessment,
)


class MockQualityConfig(FrozenModel):
    default: QualityAssessment
    by_candidate: dict[str, QualityAssessment] = Field(default_factory=dict)


class MockReliabilityConfig(FrozenModel):
    default: ReliabilityAssessment
    by_candidate: dict[str, ReliabilityAssessment] = Field(default_factory=dict)


class MockAgentsConfig(FrozenModel):
    quality: MockQualityConfig
    reliability: MockReliabilityConfig


def load_mock_agents_config(path: str | Path) -> MockAgentsConfig:
    return MockAgentsConfig.model_validate(load_yaml_mapping(path))


class MockQualityAgent:
    """Return configured values without pretending to be an ML model."""

    is_mock = True

    def __init__(self, config: MockQualityConfig) -> None:
        self.config = config

    def predict(
        self, state: ProcessState, candidate: CandidateAction
    ) -> QualityAssessment:
        assessment = self.config.by_candidate.get(
            candidate.candidate_id, self.config.default
        )
        return assessment.model_copy(update={"source": AssessmentSource.MOCK})


class MockReliabilityAgent:
    """Return configured values without simulating physical relationships."""

    is_mock = True

    def __init__(self, config: MockReliabilityConfig) -> None:
        self.config = config

    def evaluate(
        self, state: ProcessState, candidate: CandidateAction
    ) -> ReliabilityAssessment:
        assessment = self.config.by_candidate.get(
            candidate.candidate_id, self.config.default
        )
        return assessment.model_copy(update={"source": AssessmentSource.MOCK})
