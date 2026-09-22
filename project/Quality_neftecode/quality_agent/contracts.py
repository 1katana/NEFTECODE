from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class DataConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class AssessmentSource(StrEnum):
    UNKNOWN = "UNKNOWN"
    REAL = "REAL"
    MOCK = "MOCK"


class QualityProduct(StrEnum):
    UNKNOWN = "UNKNOWN"
    HYDROTREATED_DIESEL = "HYDROTREATED_DIESEL"
    COMMERCIAL_DIESEL = "COMMERCIAL_DIESEL"


Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
ConfidenceValue = DataConfidence | Probability


class ContractModel(BaseModel):
    """Mirror of the temporary strict contracts owned by Orchestrator."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ProcessState(ContractModel):
    timestamp: datetime
    quality: dict[str, Any]
    telemetry: dict[str, FiniteFloat | None]
    data_quality: dict[str, Any]
    data_confidence: ConfidenceValue
    current_controls: dict[str, FiniteFloat] = Field(default_factory=dict)


class CandidateAction(ContractModel):
    candidate_id: str = Field(min_length=1)
    changes: dict[str, FiniteFloat]
    delta: dict[str, FiniteFloat] = Field(default_factory=dict)
    horizon_hours: float = Field(default=1.0, ge=0.0, le=3.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_action(self) -> CandidateAction:
        if not self.is_no_change and not self.changes and not self.delta:
            raise ValueError("control-change candidate must contain changes or delta")
        return self

    @property
    def is_no_change(self) -> bool:
        if self.candidate_id.upper() == "NO_CHANGE":
            return True
        if self.changes or self.delta:
            values = [*self.changes.values(), *self.delta.values()]
            return bool(values) and all(value == 0 for value in values)
        return False


class ProductQualityMetrics(ContractModel):
    """Commercial-product properties produced by the transparent blend model."""

    sulfur_mg_kg: FiniteFloat | None = None
    t95_c: FiniteFloat | None = None
    density_kg_m3: FiniteFloat | None = None
    cetane_number: FiniteFloat | None = None
    blend_share_sum_pct: FiniteFloat | None = None
    additive_pct: FiniteFloat | None = None
    relative_cost: FiniteFloat | None = None


class QualityAssessment(ContractModel):
    quality_prediction: FiniteFloat | None
    prediction_lower: FiniteFloat | None = None
    prediction_upper: FiniteFloat | None = None
    violation_probability: Probability | None
    data_confidence: ConfidenceValue
    warnings: list[str] = Field(default_factory=list)
    product: QualityProduct = QualityProduct.UNKNOWN
    source: AssessmentSource = AssessmentSource.UNKNOWN
    model_version: str | None = None
    grade: Literal["SUMMER", "WINTER"] | None = None
    metrics: ProductQualityMetrics | None = None
    candidate_horizon_hours: float | None = Field(
        default=None,
        ge=0.0,
        le=3.0,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def validate_interval(self) -> QualityAssessment:
        if self.quality_prediction is None:
            if self.prediction_lower is not None or self.prediction_upper is not None:
                raise ValueError("prediction interval cannot exist without a prediction")
            return self
        if self.prediction_lower is not None and self.prediction_lower > self.quality_prediction:
            raise ValueError("prediction_lower must not exceed quality_prediction")
        if self.prediction_upper is not None and self.prediction_upper < self.quality_prediction:
            raise ValueError("prediction_upper must not be below quality_prediction")
        if (
            self.prediction_lower is not None
            and self.prediction_upper is not None
            and self.prediction_lower > self.prediction_upper
        ):
            raise ValueError("prediction_lower must not exceed prediction_upper")
        return self


class QualityAgentPort(Protocol):
    def predict(
        self,
        state: ProcessState,
        candidate: CandidateAction | None = None,
    ) -> QualityAssessment: ...
