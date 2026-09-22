"""End-to-end orchestration of generation, assessment, safety, and ranking."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import FiniteFloat, TypeAdapter

from .candidate_generator import CandidateGenerator, load_control_config
from .models import (
    AgentFailure,
    AssessmentSource,
    CandidateAction,
    ControlBasis,
    ControlConfig,
    InputSource,
    OptimizationResult,
    OptimizationStatus,
    ProcessState,
    QualityAgent,
    QualityAssessment,
    ReliabilityAgent,
    ReliabilityAssessment,
    SafetyPolicy,
    ScenarioEvaluation,
)
from .ranking import LexicographicRanker
from .safety import SafetyLayer


class Optimizer:
    def __init__(
        self,
        *,
        quality_agent: QualityAgent,
        reliability_agent: ReliabilityAgent,
        control_config: ControlConfig | str | Path,
        safety_policy: SafetyPolicy | None = None,
        max_changed_controls: int = 2,
        max_candidates: int = 100,
        economic_evaluator: Callable[[ProcessState, CandidateAction], float]
        | None = None,
    ) -> None:
        config = (
            load_control_config(control_config)
            if isinstance(control_config, (str, Path))
            else control_config
        )
        self.quality_agent = quality_agent
        self.reliability_agent = reliability_agent
        self.economic_evaluator = economic_evaluator
        config = ControlConfig.model_validate(config).model_copy(deep=True)
        self.generator = CandidateGenerator(
            config,
            max_changed_controls=max_changed_controls,
            max_candidates=max_candidates,
        )
        policy = SafetyPolicy.model_validate(safety_policy or SafetyPolicy())
        self.safety = SafetyLayer(config, policy.model_copy(deep=True))
        self.ranker = LexicographicRanker(config)

    def search(self, state: ProcessState) -> OptimizationResult:
        state = ProcessState.model_validate(state).model_copy(deep=True)
        safe: list[ScenarioEvaluation] = []
        rejected: list[ScenarioEvaluation] = []
        agent_failures: list[AgentFailure] = []
        rejection_reasons: list[str] = []
        uses_mocks = (
            getattr(self.quality_agent, "is_mock", False) is True
            or getattr(self.reliability_agent, "is_mock", False) is True
        )
        generation = self.generator.generate_with_report(state)
        warnings: list[str] = []
        control_specs = self.generator.control_config.controls.values()
        if not any(
            spec.basis == ControlBasis.CONFIRMED_OPERATING for spec in control_specs
        ):
            warnings.append("NO_CONFIRMED_CONTROL_ENVELOPES")
        if any(
            spec.basis != ControlBasis.CONFIRMED_OPERATING for spec in control_specs
        ):
            warnings.append("CONTROL_RANGES_NOT_OPERATIONAL")
        if not self.safety.policy.model_bounds:
            warnings.append("MODEL_BOUNDS_NOT_CONFIGURED")
        if not self.safety.policy.required_inputs:
            warnings.append("REQUIRED_INPUTS_NOT_CONFIGURED")
        if self.economic_evaluator is None:
            warnings.append("ECONOMICS_DISABLED")
        if generation.truncated:
            warnings.append("SEARCH_TRUNCATED")
        if state.source != InputSource.LIVE:
            warnings.append(f"NON_LIVE_INPUT:{state.source.value}")
        if (
            self.safety.policy.allow_non_live_actions
            or self.safety.policy.allow_unverified_assessments_for_actions
            or self.safety.policy.allow_experimental_controls
            or self.safety.policy.allow_mock_controls
        ):
            warnings.append("RELAXED_ACTION_POLICY")

        for candidate in generation.candidates:
            preflight = self.safety.check_inputs(state, candidate)
            if not preflight.constraint_passed:
                rejected.append(
                    ScenarioEvaluation(candidate=candidate, safety=preflight)
                )
                rejection_reasons.extend(
                    f"{candidate.candidate_id}:{reason}"
                    for reason in preflight.violations
                )
                continue
            try:
                quality = QualityAssessment.model_validate(
                    self.quality_agent.predict(
                        state.model_copy(deep=True), candidate.model_copy(deep=True)
                    )
                )
            except Exception as error:  # noqa: BLE001 - fail-closed agent boundary
                agent_failures.append(
                    AgentFailure(
                        candidate_id=candidate.candidate_id,
                        agent="quality",
                        error_type=type(error).__name__,
                    )
                )
                rejection_reasons.append(
                    f"{candidate.candidate_id}:QUALITY_AGENT_ERROR:{type(error).__name__}"
                )
                continue
            uses_mocks = uses_mocks or quality.source == AssessmentSource.MOCK
            try:
                reliability = ReliabilityAssessment.model_validate(
                    self.reliability_agent.evaluate(
                        state.model_copy(deep=True), candidate.model_copy(deep=True)
                    )
                )
            except Exception as error:  # noqa: BLE001 - fail-closed agent boundary
                agent_failures.append(
                    AgentFailure(
                        candidate_id=candidate.candidate_id,
                        agent="reliability",
                        error_type=type(error).__name__,
                    )
                )
                rejection_reasons.append(
                    f"{candidate.candidate_id}:RELIABILITY_AGENT_ERROR:{type(error).__name__}"
                )
                continue
            uses_mocks = uses_mocks or reliability.source == AssessmentSource.MOCK
            safety = self.safety.evaluate(state, candidate, quality, reliability)
            scenario = ScenarioEvaluation(
                candidate=candidate,
                quality=quality,
                reliability=reliability,
                safety=safety,
            )
            if safety.constraint_passed:
                if self.economic_evaluator is not None:
                    try:
                        gain = TypeAdapter(FiniteFloat).validate_python(
                            self.economic_evaluator(
                                state.model_copy(deep=True),
                                candidate.model_copy(deep=True),
                            ),
                            strict=True,
                        )
                        scenario = scenario.model_copy(update={"production_gain": gain})
                    except Exception as error:  # noqa: BLE001 - optional adapter boundary
                        agent_failures.append(
                            AgentFailure(
                                candidate_id=candidate.candidate_id,
                                agent="economic",
                                error_type=type(error).__name__,
                            )
                        )
                        rejection_reasons.append(
                            f"{candidate.candidate_id}:ECONOMIC_ERROR:{type(error).__name__}"
                        )
                        continue
                safe.append(scenario)
            else:
                rejected.append(scenario)
                rejection_reasons.extend(
                    f"{candidate.candidate_id}:{reason}" for reason in safety.violations
                )

        if not safe:
            return OptimizationResult(
                status=OptimizationStatus.NO_FEASIBLE_SOLUTION,
                input_source=state.source,
                best_candidate=None,
                rejected_candidates=rejected,
                agent_failures=agent_failures,
                reasons=list(dict.fromkeys(rejection_reasons)),
                uses_mock_assessments=uses_mocks,
                warnings=warnings,
                generated_count=len(generation.candidates),
                search_truncated=generation.truncated,
                state_timestamp=state.timestamp,
                selection_reason="NO_SAFE_EVALUATED_CANDIDATE",
            )

        ranked = self.ranker.rank(safe)
        best = ranked[0]
        status = (
            OptimizationStatus.KEEP
            if best.candidate.is_keep
            else OptimizationStatus.RECOMMEND
        )
        return OptimizationResult(
            status=status,
            input_source=state.source,
            best_candidate=best,
            ranked_candidates=ranked,
            rejected_candidates=rejected,
            agent_failures=agent_failures,
            reasons=list(dict.fromkeys(rejection_reasons)),
            uses_mock_assessments=uses_mocks,
            warnings=warnings,
            generated_count=len(generation.candidates),
            search_truncated=generation.truncated,
            state_timestamp=state.timestamp,
            selection_reason=(
                "KEEP_BEST_OR_TIED"
                if best.candidate.is_keep
                else "MINIMUM_LEXICOGRAPHIC_KEY"
            ),
        )
