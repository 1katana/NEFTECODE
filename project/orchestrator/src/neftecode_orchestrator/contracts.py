from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .enums import (
    AssessmentSource,
    ComponentStatus,
    DataConfidence,
    Decision,
    InputSource,
    OptimizationStatus,
    QualityProduct,
    ReliabilityRisk,
)

Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
ConfidenceValue = DataConfidence | Probability


class ContractModel(BaseModel):
    """Strict base for temporary contracts until a shared package exists."""

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
                raise ValueError(
                    "prediction interval cannot exist without a prediction"
                )
            return self
        if (
            self.prediction_lower is not None
            and self.prediction_lower > self.quality_prediction
        ):
            raise ValueError("prediction_lower must not exceed quality_prediction")
        if (
            self.prediction_upper is not None
            and self.prediction_upper < self.quality_prediction
        ):
            raise ValueError("prediction_upper must not be below quality_prediction")
        if (
            self.prediction_lower is not None
            and self.prediction_upper is not None
            and self.prediction_lower > self.prediction_upper
        ):
            raise ValueError("prediction_lower must not exceed prediction_upper")
        return self


class ReliabilityAssessment(ContractModel):
    reliability_risk: ReliabilityRisk
    risk_score: Probability | None
    data_confidence: ConfidenceValue
    warnings: list[str] = Field(default_factory=list)
    risk_factors: list[dict[str, Any] | str] = Field(default_factory=list)
    partial_risk_score: Probability | None = None
    candidate_controls_supported: bool | None = None
    technology_limits_configured: bool | None = None
    assets: dict[str, Any] = Field(default_factory=dict)
    observation_issues: dict[str, Any] = Field(default_factory=dict)
    score_meaning: str | None = None
    source: AssessmentSource = AssessmentSource.UNKNOWN
    model_version: str | None = None


class SafetyResult(ContractModel):
    constraint_passed: bool
    violations: list[str]
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def validate_consistency(self) -> SafetyResult:
        if self.constraint_passed and self.violations:
            raise ValueError("passed safety result cannot contain violations")
        if (
            not self.constraint_passed
            and not self.violations
            and not self.rejection_reason
        ):
            raise ValueError("rejected safety result must explain the rejection")
        return self


class ScenarioEvaluation(ContractModel):
    candidate: CandidateAction
    quality_prediction: FiniteFloat | None
    violation_probability: Probability | None
    reliability_risk: ReliabilityRisk | Probability | None
    reliability_risk_score: Probability | None = None
    reliability_source: AssessmentSource = AssessmentSource.UNKNOWN
    reliability_warnings: list[str] = Field(default_factory=list)
    candidate_controls_supported: bool | None = None
    constraint_passed: bool
    violations: list[str]
    score: FiniteFloat | None
    grade: Literal["SUMMER", "WINTER"] | None = None
    metrics: ProductQualityMetrics | None = None
    candidate_horizon_hours: float | None = Field(
        default=None,
        ge=0.0,
        le=3.0,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def validate_consistency(self) -> ScenarioEvaluation:
        if self.constraint_passed and self.violations:
            raise ValueError("safe scenario cannot contain violations")
        if not self.constraint_passed and not self.violations:
            raise ValueError("unsafe scenario must contain at least one violation")
        return self


class RankedCandidate(ContractModel):
    rank: int = Field(ge=1)
    score: FiniteFloat | None = None
    score_components: dict[str, FiniteFloat | str | None] = Field(default_factory=dict)
    candidate: CandidateAction


class OptimizationResult(ContractModel):
    status: OptimizationStatus
    ranked_candidates: list[RankedCandidate]
    reasons: list[str] = Field(default_factory=list)
    input_source: InputSource | None = None
    uses_mock_assessments: bool = False
    warnings: list[str] = Field(default_factory=list)
    selection_reason: str | None = None
    generated_count: int = Field(default=0, ge=0)
    search_truncated: bool = False

    @model_validator(mode="after")
    def validate_status(self) -> OptimizationResult:
        if self.status is OptimizationStatus.SUCCESS and not self.ranked_candidates:
            raise ValueError("SUCCESS optimization result requires ranked candidates")
        if self.status is OptimizationStatus.NO_FEASIBLE_SOLUTION:
            if self.ranked_candidates:
                raise ValueError(
                    "NO_FEASIBLE_SOLUTION cannot contain ranked candidates"
                )
            if not self.reasons:
                raise ValueError("NO_FEASIBLE_SOLUTION requires at least one reason")
        return self


T = TypeVar("T")


class ComponentResult(ContractModel, Generic[T]):
    status: ComponentStatus
    data: T | None = None
    error_code: str | None = None
    message: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_status(self) -> ComponentResult[T]:
        if self.status is ComponentStatus.OK:
            if self.data is None:
                raise ValueError("OK component result requires data")
            if self.error_code is not None:
                raise ValueError("OK component result cannot contain error_code")
        else:
            if self.data is not None:
                raise ValueError("failed component result cannot contain data")
            if not self.error_code:
                raise ValueError("failed component result requires error_code")
        return self


class OrchestratorInput(ContractModel):
    schema_version: str = Field(pattern=r"^1\.0\.0$")
    run_id: str = Field(min_length=1)
    process_state: ProcessState
    current_quality: ComponentResult[QualityAssessment]
    current_reliability: ComponentResult[ReliabilityAssessment]
    current_safety: ComponentResult[SafetyResult]
    scenarios: list[ScenarioEvaluation]
    optimization: ComponentResult[OptimizationResult]

    @model_validator(mode="after")
    def validate_references(self) -> OrchestratorInput:
        scenario_by_id: dict[str, ScenarioEvaluation] = {}
        for scenario in self.scenarios:
            candidate_id = scenario.candidate.candidate_id
            if candidate_id in scenario_by_id:
                raise ValueError(f"duplicate scenario candidate_id: {candidate_id}")
            scenario_by_id[candidate_id] = scenario

        if self.optimization.status is not ComponentStatus.OK:
            return self

        optimization = self.optimization.data
        assert optimization is not None
        ranks: set[int] = set()
        ranked_ids: set[str] = set()
        for ranked in optimization.ranked_candidates:
            candidate_id = ranked.candidate.candidate_id
            if ranked.rank in ranks:
                raise ValueError(f"duplicate candidate rank: {ranked.rank}")
            if candidate_id in ranked_ids:
                raise ValueError(f"duplicate ranked candidate_id: {candidate_id}")
            ranks.add(ranked.rank)
            ranked_ids.add(candidate_id)

            matched_scenario = scenario_by_id.get(candidate_id)
            if matched_scenario is None:
                raise ValueError(f"ranked candidate has no scenario: {candidate_id}")
            if not matched_scenario.constraint_passed:
                raise ValueError(f"unsafe candidate cannot be ranked: {candidate_id}")
            if matched_scenario.candidate != ranked.candidate:
                raise ValueError(
                    f"ranked candidate payload differs from scenario: {candidate_id}"
                )

        if ranks and ranks != set(range(1, len(ranks) + 1)):
            raise ValueError("candidate ranks must be contiguous and start at 1")

        no_change = next(
            (item for item in self.scenarios if item.candidate.is_no_change), None
        )
        if (
            no_change is not None
            and self.current_safety.status is ComponentStatus.OK
            and self.current_safety.data is not None
        ):
            current_safety = self.current_safety.data
            if no_change.constraint_passed != current_safety.constraint_passed:
                raise ValueError("NO_CHANGE safety must match current_safety")
            if set(no_change.violations) != set(current_safety.violations):
                raise ValueError("NO_CHANGE violations must match current_safety")
        return self


class FinalDecision(ContractModel):
    schema_version: str = Field(pattern=r"^1\.0\.0$")
    run_id: str = Field(min_length=1)
    timestamp: datetime
    decision: Decision
    reason_codes: list[str] = Field(min_length=1)
    selected_candidate: CandidateAction | None
    current_state_summary: dict[str, Any]
    predicted_result: dict[str, Any] | None
    warnings: list[str]
    explanation: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decision_shape(self) -> FinalDecision:
        if self.decision is Decision.RECOMMEND:
            if self.selected_candidate is None or self.predicted_result is None:
                raise ValueError("RECOMMEND requires a candidate and predicted result")
        elif self.selected_candidate is not None:
            raise ValueError("KEEP and REFUSE cannot contain a selected candidate")
        return self


class ExecutionTrace(ContractModel):
    trace_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    started_at: datetime
    finished_at: datetime
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_statuses: dict[str, ComponentStatus]
    scenario_count: int = Field(ge=0)
    safe_scenario_count: int = Field(ge=0)
    input_snapshot: dict[str, Any]
    decision: FinalDecision
