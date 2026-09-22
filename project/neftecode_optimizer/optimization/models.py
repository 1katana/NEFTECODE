"""Typed contracts shared by the optimization components."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        allow_inf_nan=False,
        revalidate_instances="always",
    )


class DataConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AssessmentSource(str, Enum):
    UNKNOWN = "UNKNOWN"
    REAL = "REAL"
    MOCK = "MOCK"


class InputSource(str, Enum):
    """How ProcessState was obtained, independent of agent provenance."""

    SYNTHETIC = "SYNTHETIC"
    HISTORICAL = "HISTORICAL"
    LIVE = "LIVE"


class QualityProduct(str, Enum):
    """Product to which the predicted sulfur concentration applies."""

    UNKNOWN = "UNKNOWN"
    HYDROTREATED_DIESEL = "HYDROTREATED_DIESEL"
    COMMERCIAL_DIESEL = "COMMERCIAL_DIESEL"


class ControlBasis(str, Enum):
    """Evidence class of the configured control envelope."""

    CONFIRMED_OPERATING = "CONFIRMED_OPERATING"
    EXPERIMENTAL_MODEL = "EXPERIMENTAL_MODEL"
    MOCK_FIXTURE = "MOCK_FIXTURE"


class ReliabilityRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class OptimizationStatus(str, Enum):
    RECOMMEND = "RECOMMEND"
    KEEP = "KEEP"
    NO_FEASIBLE_SOLUTION = "NO_FEASIBLE_SOLUTION"


class ControlSpec(FrozenModel):
    """A control envelope whose evidence class must be explicit."""

    basis: ControlBasis
    minimum: float = Field(alias="min")
    maximum: float = Field(alias="max")
    step: float = Field(gt=0)
    max_delta: float = Field(gt=0)
    unit: str

    @model_validator(mode="after")
    def validate_range(self) -> ControlSpec:
        if self.minimum >= self.maximum:
            raise ValueError("control min must be smaller than max")
        if self.step > self.max_delta:
            raise ValueError("step must not exceed max_delta")
        if not self.unit.strip():
            raise ValueError("control unit must be specified")
        return self


class NumericBounds(FrozenModel):
    minimum: float = Field(alias="min")
    maximum: float = Field(alias="max")

    @model_validator(mode="after")
    def validate_range(self) -> NumericBounds:
        if self.minimum > self.maximum:
            raise ValueError("model bound min must not exceed max")
        return self


class ControlConfig(FrozenModel):
    controls: dict[str, ControlSpec] = Field(default_factory=dict)
    candidate_horizon_hours: float = Field(default=1.0, ge=0.0, le=3.0)


class ProcessState(FrozenModel):
    """Observed state at a point in time.

    When the state is anchored to a LIMS event, ``timestamp`` is the sample
    collection time (not registration time and not result-ready time).
    Missing measurements remain ``None`` and are never imputed here.
    """

    source: InputSource
    timestamp: datetime
    values: dict[str, float | None]
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateAction(FrozenModel):
    candidate_id: str
    changes: dict[str, float] = Field(default_factory=dict)
    deltas: dict[str, float] = Field(default_factory=dict)
    horizon_hours: float = Field(default=1.0, ge=0.0, le=3.0)

    @model_validator(mode="after")
    def matching_delta_keys(self) -> CandidateAction:
        if self.changes.keys() != self.deltas.keys():
            raise ValueError("changes and deltas must contain the same controls")
        if any(delta == 0 for delta in self.deltas.values()):
            raise ValueError("omit unchanged controls; KEEP has empty changes")
        return self

    @property
    def is_keep(self) -> bool:
        return not self.changes


class ProductQualityMetrics(FrozenModel):
    sulfur_mg_kg: float | None = None
    t95_c: float | None = None
    density_kg_m3: float | None = None
    cetane_number: float | None = None
    blend_share_sum_pct: float | None = None
    additive_pct: float | None = None
    relative_cost: float | None = None


class QualityAssessment(FrozenModel):
    """Quality-agent response; the MVP target is sulfur in mg/kg.

    The commercial diesel limit cannot be validated using an assessment of
    hydrotreated diesel unless downstream blending is explicitly modeled.
    """

    quality_prediction: float | None
    prediction_lower: float | None
    prediction_upper: float | None
    violation_probability: float | None = Field(default=None, ge=0, le=1)
    data_confidence: DataConfidence | None
    product: QualityProduct = QualityProduct.UNKNOWN
    source: AssessmentSource = AssessmentSource.UNKNOWN
    model_version: str | None = None
    grade: Literal["SUMMER", "WINTER"] | None = None
    metrics: ProductQualityMetrics | None = None
    candidate_horizon_hours: float | None = Field(default=None, ge=0.0, le=3.0)

    @model_validator(mode="after")
    def validate_interval(self) -> QualityAssessment:
        lower, mean, upper = (
            self.prediction_lower,
            self.quality_prediction,
            self.prediction_upper,
        )
        if mean is not None and mean < 0:
            raise ValueError("predicted sulfur must be nonnegative")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("prediction interval is reversed")
        if mean is not None and (
            (lower is not None and mean < lower) or (upper is not None and mean > upper)
        ):
            raise ValueError("prediction must be inside its interval")
        return self


class ReliabilityAssessment(FrozenModel):
    reliability_risk: ReliabilityRisk | None
    risk_score: float | None = Field(default=None, ge=0, le=1)
    data_confidence: DataConfidence | None
    warnings: list[str] = Field(default_factory=list)
    source: AssessmentSource = AssessmentSource.UNKNOWN
    model_version: str | None = None
    candidate_controls_supported: bool | None = None


class SafetyPolicy(FrozenModel):
    """Explicit safety policy with no economic trade-offs."""

    sulfur_limit_mg_kg: float = Field(default=10.0, gt=0, le=10)
    t95_max_c: float = Field(default=360.0, gt=0)
    summer_density_min_kg_m3: float = Field(default=820.0, gt=0)
    summer_density_max_kg_m3: float = Field(default=845.0, gt=0)
    winter_density_min_kg_m3: float = Field(default=800.0, gt=0)
    winter_density_max_kg_m3: float = Field(default=845.0, gt=0)
    summer_cetane_min: float = Field(default=51.0, gt=0)
    winter_cetane_min: float = Field(default=49.0, gt=0)
    blend_share_total_pct: float = Field(default=100.0, gt=0)
    blend_share_tolerance_pct: float = Field(default=0.05, ge=0)
    additive_max_pct: float = Field(default=3.0, ge=0, le=3.0)
    require_commercial_metrics: bool = False
    use_prediction_upper: bool = True
    rejected_confidences: frozenset[DataConfidence] = Field(
        default_factory=lambda: frozenset({DataConfidence.LOW})
    )
    rejected_reliability_risks: frozenset[ReliabilityRisk] = Field(
        default_factory=lambda: frozenset({ReliabilityRisk.CRITICAL})
    )
    max_violation_probability: float | None = Field(default=None, ge=0, le=1)
    model_bounds: dict[str, NumericBounds] = Field(default_factory=dict)
    required_inputs: frozenset[str] = Field(default_factory=frozenset)
    reject_mock_assessments: bool = False
    allow_experimental_controls: bool = False
    allow_mock_controls: bool = False
    allow_non_live_actions: bool = False
    allow_unverified_assessments_for_actions: bool = False

    @model_validator(mode="after")
    def retain_critical_guard(self) -> SafetyPolicy:
        if ReliabilityRisk.CRITICAL not in self.rejected_reliability_risks:
            raise ValueError("CRITICAL reliability risk must always be rejected")
        if self.summer_density_min_kg_m3 > self.summer_density_max_kg_m3:
            raise ValueError("summer density range is reversed")
        if self.winter_density_min_kg_m3 > self.winter_density_max_kg_m3:
            raise ValueError("winter density range is reversed")
        return self


class SafetyResult(FrozenModel):
    constraint_passed: bool
    violations: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def consistent_verdict(self) -> SafetyResult:
        if self.constraint_passed == bool(self.violations):
            raise ValueError("safety verdict must agree with violations")
        return self


class ScenarioEvaluation(FrozenModel):
    candidate: CandidateAction
    quality: QualityAssessment | None = None
    reliability: ReliabilityAssessment | None = None
    safety: SafetyResult
    production_gain: float | None = None
    rank: int | None = Field(default=None, ge=1)
    score: float | None = None
    score_components: dict[str, float | str | None] = Field(default_factory=dict)


class AgentFailure(FrozenModel):
    candidate_id: str
    agent: Literal["quality", "reliability", "economic"]
    error_type: str


class OptimizationResult(FrozenModel):
    status: OptimizationStatus
    input_source: InputSource
    best_candidate: ScenarioEvaluation | None
    ranked_candidates: list[ScenarioEvaluation] = Field(default_factory=list)
    rejected_candidates: list[ScenarioEvaluation] = Field(default_factory=list)
    agent_failures: list[AgentFailure] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    uses_mock_assessments: bool = False
    warnings: list[str] = Field(default_factory=list)
    selection_reason: str | None = None
    generated_count: int = 0
    search_truncated: bool = False
    state_timestamp: datetime | None = None


class GenerationResult(FrozenModel):
    candidates: list[CandidateAction]
    truncated: bool = False


@runtime_checkable
class QualityAgent(Protocol):
    def predict(
        self, state: ProcessState, candidate: CandidateAction
    ) -> QualityAssessment | Mapping[str, Any]: ...


@runtime_checkable
class ReliabilityAgent(Protocol):
    def evaluate(
        self, state: ProcessState, candidate: CandidateAction
    ) -> ReliabilityAssessment | Mapping[str, Any]: ...
