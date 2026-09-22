from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from time import perf_counter
from typing import Any, TypeVar
from uuid import uuid4

from neftecode_orchestrator.contracts import (
    ComponentResult,
    OptimizationResult,
    OrchestratorInput,
    QualityAssessment,
    ReliabilityAssessment,
    SafetyResult,
)
from neftecode_orchestrator.enums import ComponentStatus
from neftecode_orchestrator.service import OrchestratorService

from .models import EvaluationRequest, EvaluationResponse, OptimizationProjection
from .ports import OptimizationPort, QualityPort, ReliabilityPort
from .temporal import hide_future_lims

T = TypeVar("T")


class IntegrationCoordinator:
    def __init__(
        self,
        *,
        quality: QualityPort,
        reliability: ReliabilityPort,
        optimization: OptimizationPort,
        orchestrator: OrchestratorService,
        adapter_modes: dict[str, str],
        component_timeout_ms: int = 2_000,
        optimization_timeout_ms: int = 15_000,
    ) -> None:
        self.quality = quality
        self.reliability = reliability
        self.optimization = optimization
        self.orchestrator = orchestrator
        self.adapter_modes = dict(adapter_modes)
        self.component_timeout_ms = component_timeout_ms
        self.optimization_timeout_ms = optimization_timeout_ms
        self.runs: dict[str, EvaluationResponse] = {}

    async def _run_component(
        self,
        name: str,
        call: Awaitable[T],
        *,
        timeout_ms: int | None = None,
    ) -> ComponentResult[T]:
        started = perf_counter()
        resolved_timeout = timeout_ms or self.component_timeout_ms
        try:
            data = await asyncio.wait_for(
                call,
                timeout=resolved_timeout / 1_000.0,
            )
        except TimeoutError:
            return ComponentResult(
                status=ComponentStatus.TIMEOUT,
                error_code=f"{name.upper()}_TIMEOUT",
                message=f"{name} did not respond within {resolved_timeout} ms",
                latency_ms=round((perf_counter() - started) * 1_000),
            )
        except Exception as error:  # noqa: BLE001 - external component boundary
            return ComponentResult(
                status=ComponentStatus.ERROR,
                error_code=f"{name.upper()}_ERROR",
                message=f"{type(error).__name__}: {error}",
                latency_ms=round((perf_counter() - started) * 1_000),
            )
        return ComponentResult(
            status=ComponentStatus.OK,
            data=data,
            latency_ms=round((perf_counter() - started) * 1_000),
        )

    async def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        started = perf_counter()
        run_id = request.run_id or str(uuid4())
        process_state = hide_future_lims(request.process_state)
        history = [hide_future_lims(item) for item in request.history]
        quality_result, reliability_result = await asyncio.gather(
            self._run_component(
                "quality",
                self.quality.evaluate_current(process_state, history),
            ),
            self._run_component(
                "reliability",
                self.reliability.evaluate_current(process_state),
            ),
        )
        quality = quality_result.data if quality_result.status is ComponentStatus.OK else None
        reliability = (
            reliability_result.data if reliability_result.status is ComponentStatus.OK else None
        )
        if quality is not None and reliability is not None:
            projection_result = await self._run_component(
                "optimization",
                self.optimization.optimize(
                    process_state,
                    request.input_source,
                    quality,
                    reliability,
                ),
                timeout_ms=self.optimization_timeout_ms,
            )
        else:
            projection_result = ComponentResult[OptimizationProjection](
                status=ComponentStatus.ERROR,
                error_code="OPTIMIZATION_PREREQUISITE_FAILED",
                message="quality and reliability are required before optimization",
                latency_ms=0,
            )

        if projection_result.status is ComponentStatus.OK:
            projection = projection_result.data
            assert projection is not None
            optimization_result = ComponentResult[OptimizationResult](
                status=ComponentStatus.OK,
                data=projection.optimization,
                latency_ms=projection_result.latency_ms,
            )
            scenarios = projection.scenarios
            if projection.current_safety is not None:
                safety_result = ComponentResult[SafetyResult](
                    status=ComponentStatus.OK,
                    data=projection.current_safety,
                    latency_ms=projection_result.latency_ms,
                )
            else:
                safety_result = ComponentResult[SafetyResult](
                    status=ComponentStatus.ERROR,
                    error_code="CURRENT_SAFETY_UNAVAILABLE",
                    message="optimizer did not evaluate the NO_CHANGE scenario",
                    latency_ms=projection_result.latency_ms,
                )
        else:
            scenarios = []
            optimization_result = ComponentResult[OptimizationResult](
                status=projection_result.status,
                error_code=projection_result.error_code,
                message=projection_result.message,
                latency_ms=projection_result.latency_ms,
            )
            safety_result = ComponentResult[SafetyResult](
                status=projection_result.status,
                error_code="CURRENT_SAFETY_UNAVAILABLE",
                message=projection_result.message,
                latency_ms=projection_result.latency_ms,
            )
        assembled = OrchestratorInput(
            schema_version="1.0.0",
            run_id=run_id,
            process_state=process_state,
            current_quality=ComponentResult[QualityAssessment].model_validate(
                quality_result.model_dump(mode="python")
            ),
            current_reliability=ComponentResult[ReliabilityAssessment].model_validate(
                reliability_result.model_dump(mode="python")
            ),
            current_safety=ComponentResult[SafetyResult].model_validate(
                safety_result.model_dump(mode="python")
            ),
            scenarios=scenarios,
            optimization=optimization_result,
        )
        decision = self.orchestrator.decide(assembled)
        response = EvaluationResponse(
            run_id=run_id,
            decision=decision,
            assembled_input=assembled,
            adapter_modes=self.adapter_modes,
            total_latency_ms=round((perf_counter() - started) * 1_000),
        )
        self.runs[run_id] = response
        return response

    def get_run(self, run_id: str) -> EvaluationResponse | None:
        return self.runs.get(run_id)

    def metadata(self) -> dict[str, Any]:
        optimizer_metadata = getattr(self.optimization, "metadata", None)
        optimizer = optimizer_metadata() if optimizer_metadata else {}
        reliability_metadata = getattr(self.reliability, "metadata", None)
        reliability = reliability_metadata() if reliability_metadata else {}
        blockers = list(optimizer.get("production_blockers", []))
        if self.adapter_modes.get("reliability") == "real_regime_proxy_candidate_static":
            blockers.append("RELIABILITY_CANDIDATE_CAUSAL_MODEL_NOT_READY")
        if reliability and not reliability.get("technology_limits_configured"):
            blockers.append("RELIABILITY_TECHNOLOGY_LIMITS_NOT_CONFIGURED")
        return {
            "adapter_modes": self.adapter_modes,
            "component_timeout_ms": self.component_timeout_ms,
            "optimization_timeout_ms": self.optimization_timeout_ms,
            "stored_runs": len(self.runs),
            "optimizer": optimizer,
            "reliability": reliability,
            "production_blockers": list(dict.fromkeys(blockers)),
        }
