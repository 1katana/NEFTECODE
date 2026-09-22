from __future__ import annotations

from dataclasses import replace

from neftecode_orchestrator.service import OrchestratorService
from neftecode_orchestrator.trace import JsonlTraceSink
from quality_agent.runtime import RuntimeConfig

from .adapters import (
    LocalQualityAdapter,
)
from .coordinator import IntegrationCoordinator
from .optimizer_adapter import LocalOptimizerAdapter
from .reliability_adapter import LocalReliabilityAdapter
from .settings import IntegrationSettings


def build_coordinator(settings: IntegrationSettings) -> IntegrationCoordinator:
    quality_runtime = RuntimeConfig.from_yaml(settings.quality_runtime_config)
    quality_runtime = replace(quality_runtime, shadow_log=settings.quality_shadow_log_path)
    quality = LocalQualityAdapter(quality_runtime, product=settings.quality_product)
    reliability = LocalReliabilityAdapter(settings.reliability_policy)
    return IntegrationCoordinator(
        quality=quality,
        reliability=reliability,
        optimization=LocalOptimizerAdapter(
            quality_adapter=quality,
            reliability_adapter=reliability,
            control_config=str(settings.optimizer_control_config),
            safety_policy=str(settings.optimizer_safety_policy),
            max_candidates=settings.max_candidates,
            max_changed_controls=settings.max_changed_controls,
        ),
        orchestrator=OrchestratorService(trace_sink=JsonlTraceSink(settings.trace_path)),
        adapter_modes=settings.adapter_modes,
        component_timeout_ms=settings.component_timeout_ms,
        optimization_timeout_ms=settings.optimization_timeout_ms,
    )
