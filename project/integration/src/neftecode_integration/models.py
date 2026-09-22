from __future__ import annotations

from typing import Any

from neftecode_orchestrator.contracts import (
    FinalDecision,
    OptimizationResult,
    OrchestratorInput,
    ProcessState,
    SafetyResult,
    ScenarioEvaluation,
)
from neftecode_orchestrator.enums import InputSource
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationRequest(ApiModel):
    run_id: str | None = Field(default=None, min_length=1)
    input_source: InputSource = InputSource.SYNTHETIC
    process_state: ProcessState
    history: list[ProcessState] = Field(default_factory=list, max_length=1_000)

    @model_validator(mode="after")
    def validate_history(self) -> EvaluationRequest:
        future = [
            item.timestamp.isoformat()
            for item in self.history
            if item.timestamp > self.process_state.timestamp
        ]
        if future:
            raise ValueError("history cannot contain timestamps after process_state.timestamp")
        return self


class EvaluationResponse(ApiModel):
    run_id: str
    decision: FinalDecision
    assembled_input: OrchestratorInput
    adapter_modes: dict[str, str]
    total_latency_ms: int = Field(ge=0)


class UploadEvaluationResponse(EvaluationResponse):
    """Evaluation response enriched with the preprocessing/upload contract."""

    processing: dict[str, Any]


class OptimizationProjection(ApiModel):
    optimization: OptimizationResult
    scenarios: list[ScenarioEvaluation]
    current_safety: SafetyResult | None = None


class LimsObservation(ApiModel):
    sample_timestamp: str
    sulfur_mg_kg: float
    sample_id: str | None = None


class HealthResponse(ApiModel):
    status: str
    runtime: dict[str, Any]
    integration: dict[str, Any]
