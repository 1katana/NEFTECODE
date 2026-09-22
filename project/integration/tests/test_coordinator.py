from __future__ import annotations

import asyncio

import pytest
from neftecode_orchestrator.contracts import ProcessState, QualityAssessment
from neftecode_orchestrator.enums import (
    AssessmentSource,
    ComponentStatus,
    DataConfidence,
    Decision,
    QualityProduct,
)
from neftecode_orchestrator.service import OrchestratorService

from neftecode_integration.adapters import (
    DemoNoChangeOptimizer,
    DemoReliabilityAdapter,
)
from neftecode_integration.coordinator import IntegrationCoordinator
from neftecode_integration.models import EvaluationRequest


class SlowQuality:
    async def evaluate_current(
        self,
        state: ProcessState,
        history: list[ProcessState],
    ) -> QualityAssessment:
        del state, history
        await asyncio.sleep(0.05)
        raise AssertionError("timeout should cancel the component")


class StaticQuality:
    async def evaluate_current(
        self,
        state: ProcessState,
        history: list[ProcessState],
    ) -> QualityAssessment:
        del state, history
        return QualityAssessment(
            quality_prediction=5.0,
            prediction_lower=4.0,
            prediction_upper=6.0,
            violation_probability=0.05,
            data_confidence=DataConfidence.HIGH,
            product=QualityProduct.COMMERCIAL_DIESEL,
            source=AssessmentSource.REAL,
        )


class SlowOptimization:
    async def optimize(self, state, input_source, quality, reliability):
        del state, input_source, quality, reliability
        await asyncio.sleep(0.05)
        raise AssertionError("timeout should cancel the component")


@pytest.mark.asyncio
async def test_quality_timeout_becomes_fail_closed_decision() -> None:
    coordinator = IntegrationCoordinator(
        quality=SlowQuality(),
        reliability=DemoReliabilityAdapter(),
        optimization=DemoNoChangeOptimizer(),
        orchestrator=OrchestratorService(),
        adapter_modes={
            "quality": "slow-test",
            "reliability": "demo_stub",
            "safety": "demo_stub",
            "optimization": "demo_no_change_only",
        },
        component_timeout_ms=5,
    )
    request = EvaluationRequest(
        run_id="timeout-001",
        process_state=ProcessState(
            timestamp="2026-09-19T10:00:00Z",
            quality={},
            telemetry={},
            data_quality={},
            data_confidence=DataConfidence.HIGH,
            current_controls={},
        ),
    )

    response = await coordinator.evaluate(request)

    assert response.assembled_input.current_quality.status is ComponentStatus.TIMEOUT
    assert response.decision.decision is Decision.REFUSE
    assert any("COMPONENT_TIMEOUT:quality" in code for code in response.decision.reason_codes)


@pytest.mark.asyncio
async def test_optimizer_timeout_becomes_fail_closed_decision() -> None:
    coordinator = IntegrationCoordinator(
        quality=StaticQuality(),
        reliability=DemoReliabilityAdapter(),
        optimization=SlowOptimization(),
        orchestrator=OrchestratorService(),
        adapter_modes={
            "quality": "static-test",
            "reliability": "demo_stub",
            "safety": "optimizer_internal_policy",
            "optimization": "slow-test",
        },
        component_timeout_ms=100,
        optimization_timeout_ms=5,
    )
    request = EvaluationRequest(
        run_id="optimizer-timeout-001",
        process_state=ProcessState(
            timestamp="2026-09-19T10:00:00Z",
            quality={},
            telemetry={},
            data_quality={},
            data_confidence=DataConfidence.HIGH,
            current_controls={},
        ),
    )

    response = await coordinator.evaluate(request)

    assert response.assembled_input.optimization.status is ComponentStatus.TIMEOUT
    assert response.assembled_input.current_safety.status is ComponentStatus.TIMEOUT
    assert response.decision.decision is Decision.REFUSE
    assert any("COMPONENT_TIMEOUT:optimizer" in code for code in response.decision.reason_codes)
