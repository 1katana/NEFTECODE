from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from neftecode_orchestrator.contracts import (
    CandidateAction,
    OptimizationResult,
    ProcessState,
    ProductQualityMetrics,
    QualityAssessment,
    RankedCandidate,
    ReliabilityAssessment,
    SafetyResult,
    ScenarioEvaluation,
)
from neftecode_orchestrator.enums import (
    AssessmentSource,
    DataConfidence,
    InputSource,
    OptimizationStatus,
    ReliabilityRisk,
)
from optimization import (
    AssessmentSource as NativeAssessmentSource,
)
from optimization import (
    CandidateAction as NativeCandidateAction,
)
from optimization import (
    ControlConfig,
    Optimizer,
    SafetyPolicy,
    load_control_config,
    load_safety_policy,
)
from optimization import (
    DataConfidence as NativeDataConfidence,
)
from optimization import (
    InputSource as NativeInputSource,
)
from optimization import (
    OptimizationResult as NativeOptimizationResult,
)
from optimization import (
    OptimizationStatus as NativeOptimizationStatus,
)
from optimization import (
    ProcessState as NativeProcessState,
)
from optimization import (
    ProductQualityMetrics as NativeProductQualityMetrics,
)
from optimization import (
    QualityAssessment as NativeQualityAssessment,
)
from optimization import (
    QualityProduct as NativeQualityProduct,
)
from optimization import (
    ReliabilityAssessment as NativeReliabilityAssessment,
)
from optimization import (
    ReliabilityRisk as NativeReliabilityRisk,
)
from optimization import (
    ScenarioEvaluation as NativeScenarioEvaluation,
)
from quality_agent.contracts import CandidateAction as QualityCandidateAction

from .adapters import LocalQualityAdapter
from .models import OptimizationProjection
from .reliability_adapter import LocalReliabilityAdapter


def _confidence(value: DataConfidence | float) -> NativeDataConfidence | None:
    if isinstance(value, float):
        if value >= 0.8:
            return NativeDataConfidence.HIGH
        if value >= 0.5:
            return NativeDataConfidence.MEDIUM
        return NativeDataConfidence.LOW
    if value is DataConfidence.UNKNOWN:
        return None
    return NativeDataConfidence(value.value)


def _quality(assessment: QualityAssessment) -> NativeQualityAssessment:
    return NativeQualityAssessment(
        quality_prediction=assessment.quality_prediction,
        prediction_lower=assessment.prediction_lower,
        prediction_upper=assessment.prediction_upper,
        violation_probability=assessment.violation_probability,
        data_confidence=_confidence(assessment.data_confidence),
        product=NativeQualityProduct(assessment.product.value),
        source=NativeAssessmentSource(assessment.source.value),
        model_version=assessment.model_version,
        grade=assessment.grade,
        metrics=(
            NativeProductQualityMetrics.model_validate(assessment.metrics.model_dump(mode="python"))
            if assessment.metrics
            else None
        ),
        candidate_horizon_hours=assessment.candidate_horizon_hours,
    )


def _reliability(
    assessment: ReliabilityAssessment,
) -> NativeReliabilityAssessment:
    return NativeReliabilityAssessment(
        reliability_risk=(
            None
            if assessment.reliability_risk is ReliabilityRisk.UNKNOWN
            else NativeReliabilityRisk(assessment.reliability_risk.value)
        ),
        risk_score=assessment.risk_score,
        data_confidence=_confidence(assessment.data_confidence),
        warnings=list(assessment.warnings),
        source=NativeAssessmentSource(assessment.source.value),
        model_version=assessment.model_version,
        candidate_controls_supported=assessment.candidate_controls_supported,
    )


class _BoundQualityAgent:
    def __init__(
        self,
        adapter: LocalQualityAdapter,
        state: ProcessState,
        current: QualityAssessment,
    ) -> None:
        self.adapter = adapter
        self.state = state
        self.current = current
        self.is_mock = current.source is AssessmentSource.MOCK

    def predict(
        self,
        state: NativeProcessState,
        candidate: NativeCandidateAction,
    ) -> NativeQualityAssessment:
        del state
        if candidate.is_keep:
            return _quality(self.current)
        common_candidate = QualityCandidateAction(
            candidate_id=candidate.candidate_id,
            changes=dict(candidate.changes),
            delta=dict(candidate.deltas),
            horizon_hours=candidate.horizon_hours,
        )
        return _quality(self.adapter.evaluate_candidate_sync(self.state, common_candidate))


class _BoundReliabilityAgent:
    def __init__(
        self,
        current: ReliabilityAssessment,
        adapter: LocalReliabilityAdapter | None = None,
        state: ProcessState | None = None,
    ) -> None:
        self.current = current
        self.adapter = adapter
        self.state = state
        self.is_mock = current.source is AssessmentSource.MOCK

    def evaluate(
        self,
        state: NativeProcessState,
        candidate: NativeCandidateAction,
    ) -> NativeReliabilityAssessment:
        del state
        if candidate.is_keep:
            return _reliability(self.current)
        if self.adapter is None or self.state is None:
            fallback = self.current.model_copy(
                update={
                    "source": AssessmentSource.UNKNOWN,
                    "candidate_controls_supported": False,
                }
            )
            return _reliability(fallback)
        return _reliability(
            self.adapter.evaluate_candidate_sync(
                self.state, candidate.candidate_id, dict(candidate.changes)
            )
        )


def _candidate(candidate: NativeCandidateAction) -> CandidateAction:
    return CandidateAction(
        candidate_id="NO_CHANGE" if candidate.is_keep else candidate.candidate_id,
        changes=dict(candidate.changes),
        delta=dict(candidate.deltas),
        horizon_hours=candidate.horizon_hours,
    )


def _safety(safety) -> SafetyResult:
    return SafetyResult(
        constraint_passed=safety.constraint_passed,
        violations=list(safety.violations),
        rejection_reason=safety.rejection_reason,
    )


def _scenario(scenario: NativeScenarioEvaluation) -> ScenarioEvaluation:
    return ScenarioEvaluation(
        candidate=_candidate(scenario.candidate),
        quality_prediction=(
            scenario.quality.quality_prediction if scenario.quality is not None else None
        ),
        violation_probability=(
            scenario.quality.violation_probability if scenario.quality is not None else None
        ),
        reliability_risk=(
            ReliabilityRisk(scenario.reliability.reliability_risk.value)
            if scenario.reliability is not None
            and scenario.reliability.reliability_risk is not None
            else None
        ),
        reliability_risk_score=(
            scenario.reliability.risk_score if scenario.reliability is not None else None
        ),
        reliability_source=(
            AssessmentSource(scenario.reliability.source.value)
            if scenario.reliability is not None
            else AssessmentSource.UNKNOWN
        ),
        reliability_warnings=(
            list(scenario.reliability.warnings) if scenario.reliability is not None else []
        ),
        candidate_controls_supported=(
            scenario.reliability.candidate_controls_supported
            if scenario.reliability is not None
            else None
        ),
        constraint_passed=scenario.safety.constraint_passed,
        violations=list(scenario.safety.violations),
        score=scenario.score,
        grade=scenario.quality.grade if scenario.quality is not None else None,
        metrics=(
            ProductQualityMetrics.model_validate(scenario.quality.metrics.model_dump(mode="python"))
            if scenario.quality is not None and scenario.quality.metrics is not None
            else None
        ),
        candidate_horizon_hours=(
            scenario.quality.candidate_horizon_hours if scenario.quality is not None else None
        ),
    )


def _projection(result: NativeOptimizationResult) -> OptimizationProjection:
    native_scenarios = [*result.ranked_candidates, *result.rejected_candidates]
    scenarios = [_scenario(item) for item in native_scenarios]
    ranked: list[RankedCandidate] = []
    for item in result.ranked_candidates:
        if item.rank is None:
            raise ValueError(f"ranked candidate has no rank: {item.candidate.candidate_id}")
        ranked.append(
            RankedCandidate(
                rank=item.rank,
                score=item.score,
                score_components=dict(item.score_components),
                candidate=_candidate(item.candidate),
            )
        )
    optimization = OptimizationResult(
        status=(
            OptimizationStatus.NO_FEASIBLE_SOLUTION
            if result.status is NativeOptimizationStatus.NO_FEASIBLE_SOLUTION
            else OptimizationStatus.SUCCESS
        ),
        ranked_candidates=ranked,
        reasons=list(result.reasons),
        input_source=InputSource(result.input_source.value),
        uses_mock_assessments=result.uses_mock_assessments,
        warnings=list(result.warnings),
        selection_reason=result.selection_reason,
        generated_count=result.generated_count,
        search_truncated=result.search_truncated,
    )
    keep = next((item for item in native_scenarios if item.candidate.is_keep), None)
    return OptimizationProjection(
        optimization=optimization,
        scenarios=scenarios,
        current_safety=_safety(keep.safety) if keep is not None else None,
    )


class LocalOptimizerAdapter:
    def __init__(
        self,
        *,
        quality_adapter: LocalQualityAdapter,
        reliability_adapter: LocalReliabilityAdapter | None = None,
        control_config: str,
        safety_policy: str,
        max_candidates: int = 100,
        max_changed_controls: int = 2,
    ) -> None:
        self.quality_adapter = quality_adapter
        self.reliability_adapter = reliability_adapter
        self.control_config: ControlConfig = load_control_config(control_config)
        self.safety_policy: SafetyPolicy = load_safety_policy(safety_policy)
        self.max_candidates = max_candidates
        self.max_changed_controls = max_changed_controls
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="optimizer")

    async def optimize(
        self,
        state: ProcessState,
        input_source: InputSource,
        quality: QualityAssessment,
        reliability: ReliabilityAssessment,
    ) -> OptimizationProjection:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._optimize_sync,
            state,
            input_source,
            quality,
            reliability,
        )

    def _optimize_sync(
        self,
        state: ProcessState,
        input_source: InputSource,
        quality: QualityAssessment,
        reliability: ReliabilityAssessment,
    ) -> OptimizationProjection:
        values = {**state.telemetry, **state.current_controls}
        metadata = {
            "data_quality": state.data_quality,
            "data_confidence": (
                state.data_confidence.value
                if isinstance(state.data_confidence, DataConfidence)
                else state.data_confidence
            ),
        }
        if "telemetry_available" in state.data_quality:
            metadata["telemetry_available"] = state.data_quality["telemetry_available"]
        native_state = NativeProcessState(
            source=NativeInputSource(input_source.value),
            timestamp=state.timestamp,
            values=values,
            metadata=metadata,
        )
        optimizer = Optimizer(
            quality_agent=_BoundQualityAgent(self.quality_adapter, state, quality),
            reliability_agent=_BoundReliabilityAgent(reliability, self.reliability_adapter, state),
            control_config=self.control_config,
            safety_policy=self.safety_policy,
            max_candidates=self.max_candidates,
            max_changed_controls=self.max_changed_controls,
        )
        return _projection(optimizer.search(native_state))

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def metadata(self) -> dict[str, object]:
        controls = self.control_config.controls
        confirmed_controls = sum(
            spec.basis.value == "CONFIRMED_OPERATING" for spec in controls.values()
        )
        blockers: list[str] = []
        if not confirmed_controls:
            blockers.append("NO_CONFIRMED_CONTROL_ENVELOPES")
        if self.quality_adapter.product.value != "COMMERCIAL_DIESEL":
            blockers.append("QUALITY_PRODUCT_NOT_COMMERCIAL_DIESEL")
        if not self.safety_policy.required_inputs:
            blockers.append("REQUIRED_INPUTS_NOT_CONFIGURED")
        if not self.safety_policy.model_bounds:
            blockers.append("MODEL_BOUNDS_NOT_CONFIGURED")
        if not self.safety_policy.reject_mock_assessments:
            blockers.append("MOCK_ASSESSMENTS_NOT_REJECTED")
        return {
            "status": "SHADOW_FAIL_CLOSED",
            "configured_controls": len(controls),
            "confirmed_controls": confirmed_controls,
            "max_candidates": self.max_candidates,
            "max_changed_controls": self.max_changed_controls,
            "quality_product": self.quality_adapter.product.value,
            "production_blockers": blockers,
        }
