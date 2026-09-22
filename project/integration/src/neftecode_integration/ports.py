from __future__ import annotations

from typing import Protocol

from neftecode_orchestrator.contracts import (
    ProcessState,
    QualityAssessment,
    ReliabilityAssessment,
    SafetyResult,
)
from neftecode_orchestrator.enums import InputSource

from .models import OptimizationProjection


class QualityPort(Protocol):
    async def evaluate_current(
        self,
        state: ProcessState,
        history: list[ProcessState],
    ) -> QualityAssessment: ...


class ReliabilityPort(Protocol):
    async def evaluate_current(self, state: ProcessState) -> ReliabilityAssessment: ...


class SafetyPort(Protocol):
    async def evaluate_current(
        self,
        state: ProcessState,
        quality: QualityAssessment | None,
        reliability: ReliabilityAssessment | None,
    ) -> SafetyResult: ...


class OptimizationPort(Protocol):
    async def optimize(
        self,
        state: ProcessState,
        input_source: InputSource,
        quality: QualityAssessment,
        reliability: ReliabilityAssessment,
    ) -> OptimizationProjection: ...
