from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    CandidateAction,
    ComponentResult,
    ConfidenceValue,
    OrchestratorInput,
)
from .enums import (
    AssessmentSource,
    ComponentStatus,
    DataConfidence,
    Decision,
    InputSource,
    OptimizationStatus,
    ReliabilityRisk,
)
from .reason_codes import ReasonCode


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    high_confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    medium_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    decision: Decision
    reason_codes: tuple[str, ...]
    selected_candidate: CandidateAction | None = None


class DecisionPolicy:
    """Pure, deterministic final-decision policy.

    Safety and ranking are external authorities. This class only validates their
    availability and maps their agreed outputs to RECOMMEND, KEEP or REFUSE.
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def decide(self, data: OrchestratorInput) -> PolicyOutcome:
        failed = self._failed_components(data)
        if failed:
            return PolicyOutcome(Decision.REFUSE, tuple(failed))

        quality = data.current_quality.data
        reliability = data.current_reliability.data
        current_safety = data.current_safety.data
        optimization = data.optimization.data
        assert quality is not None
        assert reliability is not None
        assert current_safety is not None
        assert optimization is not None

        if quality.quality_prediction is None or quality.violation_probability is None:
            return PolicyOutcome(
                Decision.REFUSE,
                (ReasonCode.REFUSE_REQUIRED_QUALITY_MISSING.value,),
            )

        if reliability.reliability_risk is ReliabilityRisk.UNKNOWN or reliability.risk_score is None:
            return PolicyOutcome(
                Decision.REFUSE,
                (ReasonCode.REFUSE_REQUIRED_RELIABILITY_MISSING.value,),
            )

        confidence = min(
            self._confidence_score(data.process_state.data_confidence),
            self._confidence_score(quality.data_confidence),
            self._confidence_score(reliability.data_confidence),
        )
        if confidence < self.config.medium_confidence_threshold:
            return PolicyOutcome(
                Decision.REFUSE,
                (ReasonCode.REFUSE_LOW_DATA_CONFIDENCE.value,),
            )

        if optimization.status is OptimizationStatus.NO_FEASIBLE_SOLUTION:
            if current_safety.constraint_passed:
                return PolicyOutcome(
                    Decision.KEEP,
                    (
                        ReasonCode.KEEP_CURRENT_MODE_SAFE.value,
                        ReasonCode.KEEP_NO_FEASIBLE_CHANGE.value,
                    ),
                )
            return PolicyOutcome(
                Decision.REFUSE,
                (ReasonCode.REFUSE_CURRENT_UNSAFE_NO_FEASIBLE.value,),
            )

        ranked = sorted(
            optimization.ranked_candidates, key=lambda candidate: candidate.rank
        )
        selected = ranked[0].candidate
        scenario = next(
            item
            for item in data.scenarios
            if item.candidate.candidate_id == selected.candidate_id
        )

        if selected.is_no_change:
            if not current_safety.constraint_passed:
                return PolicyOutcome(
                    Decision.REFUSE,
                    (ReasonCode.REFUSE_INCONSISTENT_NO_CHANGE.value,),
                )
            return PolicyOutcome(
                Decision.KEEP,
                (
                    ReasonCode.KEEP_CURRENT_MODE_SAFE.value,
                    ReasonCode.KEEP_TOP_CANDIDATE_IS_NO_CHANGE.value,
                ),
            )

        guard_reasons = self._recommendation_guards(optimization)
        if scenario.candidate_controls_supported is False:
            guard_reasons += ("RELIABILITY_CONTROL_UNSUPPORTED",)
        if (
            scenario.reliability_risk_score is not None
            and scenario.reliability_source is not AssessmentSource.REAL
        ):
            guard_reasons += ("RELIABILITY_CANDIDATE_STATIC_PROXY",)
        if guard_reasons:
            if current_safety.constraint_passed:
                return PolicyOutcome(
                    Decision.KEEP,
                    (
                        ReasonCode.KEEP_CURRENT_MODE_SAFE.value,
                        ReasonCode.KEEP_RECOMMENDATION_GUARD.value,
                        *guard_reasons,
                    ),
                )
            return PolicyOutcome(
                Decision.REFUSE,
                (ReasonCode.REFUSE_RECOMMENDATION_GUARD.value, *guard_reasons),
            )

        if (
            scenario.quality_prediction is None
            or scenario.violation_probability is None
        ):
            return PolicyOutcome(
                Decision.REFUSE,
                (ReasonCode.REFUSE_SCENARIO_INCOMPLETE.value,),
            )

        if confidence < self.config.high_confidence_threshold:
            if current_safety.constraint_passed:
                return PolicyOutcome(
                    Decision.KEEP,
                    (
                        ReasonCode.KEEP_CURRENT_MODE_SAFE.value,
                        ReasonCode.KEEP_CONFIDENCE_BELOW_RECOMMENDATION.value,
                    ),
                )
            return PolicyOutcome(
                Decision.REFUSE,
                (ReasonCode.REFUSE_LOW_DATA_CONFIDENCE.value,),
            )

        return PolicyOutcome(
            Decision.RECOMMEND,
            (ReasonCode.RECOMMEND_TOP_RANKED_SAFE_CANDIDATE.value,),
            selected_candidate=selected,
        )

    @staticmethod
    def _recommendation_guards(optimization) -> tuple[str, ...]:
        reasons: list[str] = []
        if optimization.input_source is not InputSource.LIVE:
            reasons.append("NON_LIVE_INPUT")
        if optimization.uses_mock_assessments:
            reasons.append("MOCK_ASSESSMENTS")
        if "RELAXED_ACTION_POLICY" in optimization.warnings:
            reasons.append("RELAXED_ACTION_POLICY")
        if optimization.search_truncated:
            reasons.append("SEARCH_TRUNCATED")
        return tuple(reasons)

    @staticmethod
    def _failed_components(data: OrchestratorInput) -> list[str]:
        failures: list[str] = []
        components: dict[str, ComponentResult[Any]] = {
            "quality": data.current_quality,
            "reliability": data.current_reliability,
            "safety": data.current_safety,
            "optimizer": data.optimization,
        }
        for name, result in components.items():
            if result.status is ComponentStatus.OK:
                continue
            if result.status is ComponentStatus.TIMEOUT:
                failures.append(f"{ReasonCode.REFUSE_COMPONENT_TIMEOUT.value}:{name}")
            else:
                failures.append(f"{ReasonCode.REFUSE_COMPONENT_FAILURE.value}:{name}")
        return failures

    def _confidence_score(self, value: ConfidenceValue) -> float:
        if isinstance(value, float):
            return value
        return {
            DataConfidence.HIGH: 1.0,
            DataConfidence.MEDIUM: self.config.medium_confidence_threshold,
            DataConfidence.LOW: 0.0,
            DataConfidence.UNKNOWN: 0.0,
        }[value]
