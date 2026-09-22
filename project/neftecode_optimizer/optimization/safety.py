"""Hard, deterministic safety checks performed before ranking."""

from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path

from .configuration import load_yaml_mapping
from .models import (
    AssessmentSource,
    CandidateAction,
    ControlBasis,
    ControlConfig,
    InputSource,
    ProcessState,
    QualityAssessment,
    QualityProduct,
    ReliabilityAssessment,
    SafetyPolicy,
    SafetyResult,
)


def load_safety_policy(path: str | Path) -> SafetyPolicy:
    return SafetyPolicy.model_validate(load_yaml_mapping(path))


class SafetyLayer:
    def __init__(
        self,
        control_config: ControlConfig,
        policy: SafetyPolicy | None = None,
    ) -> None:
        self.control_config = ControlConfig.model_validate(control_config).model_copy(
            deep=True
        )
        self.policy = SafetyPolicy.model_validate(policy or SafetyPolicy()).model_copy(
            deep=True
        )

    def check_inputs(
        self, state: ProcessState, candidate: CandidateAction
    ) -> SafetyResult:
        state = ProcessState.model_validate(state)
        candidate = CandidateAction.model_validate(candidate)
        violations: list[str] = []
        self._check_controls(state, candidate, violations)
        return SafetyResult(
            constraint_passed=not violations,
            violations=violations,
            rejection_reason=", ".join(violations) or None,
        )

    def evaluate(
        self,
        state: ProcessState,
        candidate: CandidateAction,
        quality: QualityAssessment,
        reliability: ReliabilityAssessment,
    ) -> SafetyResult:
        state = ProcessState.model_validate(state)
        candidate = CandidateAction.model_validate(candidate)
        quality = QualityAssessment.model_validate(quality)
        reliability = ReliabilityAssessment.model_validate(reliability)
        violations: list[str] = []
        self._check_controls(state, candidate, violations)
        self._check_quality(quality, violations)
        self._check_reliability(reliability, violations)
        if candidate.changes and reliability.candidate_controls_supported is False:
            violations.append("RELIABILITY_CONTROL_UNSUPPORTED")
        if (
            candidate.changes
            and not self.policy.allow_unverified_assessments_for_actions
            and (
                quality.source != AssessmentSource.REAL
                or reliability.source != AssessmentSource.REAL
            )
        ):
            violations.append("UNVERIFIED_ASSESSMENT_FOR_ACTION")
        if self.policy.reject_mock_assessments and (
            quality.source == "MOCK" or reliability.source == "MOCK"
        ):
            violations.append("MOCK_ASSESSMENT")

        unique_violations = list(dict.fromkeys(violations))
        return SafetyResult(
            constraint_passed=not unique_violations,
            violations=unique_violations,
            rejection_reason=", ".join(unique_violations) or None,
        )

    def _check_controls(
        self,
        state: ProcessState,
        candidate: CandidateAction,
        violations: list[str],
    ) -> None:
        if (
            "telemetry_available" in state.metadata
            and state.metadata["telemetry_available"] is not True
        ):
            violations.append("TELEMETRY_UNAVAILABLE")
        if (
            candidate.changes
            and state.source != InputSource.LIVE
            and not self.policy.allow_non_live_actions
        ):
            violations.append("NON_LIVE_ACTION_NOT_ALLOWED")
        proposed_state = {**state.values, **candidate.changes}
        for tag in sorted(self.policy.required_inputs):
            if state.values.get(tag) is None:
                violations.append(f"MISSING_REQUIRED_INPUT:{tag}")
        # Check every configured control, including unchanged controls and KEEP.
        for tag, spec in sorted(self.control_config.controls.items()):
            current = state.values.get(tag)
            if current is None or not math.isfinite(current):
                violations.append(f"MISSING_CONTROL_STATE:{tag}")
            proposed = proposed_state.get(tag)
            if proposed is not None and not spec.minimum <= proposed <= spec.maximum:
                violations.append(f"CONTROL_BOUNDS:{tag}")
        # Model bounds also apply to STATE features and to KEEP.
        for tag, bounds in sorted(self.policy.model_bounds.items()):
            value = proposed_state.get(tag)
            if value is None or not math.isfinite(value):
                violations.append(f"MISSING_MODEL_INPUT:{tag}")
            elif not bounds.minimum <= value <= bounds.maximum:
                violations.append(f"MODEL_BOUNDS:{tag}")
        for tag, proposed in candidate.changes.items():
            changed_spec = self.control_config.controls.get(tag)
            if changed_spec is None:
                violations.append(f"UNKNOWN_CONTROL:{tag}")
                continue
            if (
                changed_spec.basis == ControlBasis.EXPERIMENTAL_MODEL
                and not self.policy.allow_experimental_controls
            ) or (
                changed_spec.basis == ControlBasis.MOCK_FIXTURE
                and not self.policy.allow_mock_controls
            ):
                violations.append(f"UNAPPROVED_CONTROL_BASIS:{tag}")

            current = state.values.get(tag)
            if current is None or not math.isfinite(current):
                continue
            if not math.isfinite(proposed):
                violations.append(f"INVALID_CONTROL_VALUE:{tag}")
                continue
            actual_delta = Decimal(str(proposed)) - Decimal(str(current))
            if abs(actual_delta) > Decimal(str(changed_spec.max_delta)):
                violations.append(f"MAX_DELTA:{tag}")
            if not math.isclose(
                proposed - current, candidate.deltas[tag], rel_tol=1e-12, abs_tol=0.0
            ):
                violations.append(f"DELTA_MISMATCH:{tag}")

    def _check_quality(
        self,
        quality: QualityAssessment,
        violations: list[str],
    ) -> None:
        if quality.product != QualityProduct.COMMERCIAL_DIESEL:
            violations.append("QUALITY_PRODUCT_NOT_COMMERCIAL_DIESEL")
        if quality.quality_prediction is None:
            violations.append("MISSING_QUALITY_PREDICTION")
        if quality.prediction_lower is None:
            violations.append("MISSING_PREDICTION_LOWER")
        if quality.prediction_upper is None:
            violations.append("MISSING_PREDICTION_UPPER")

        sulfur = (
            quality.prediction_upper
            if self.policy.use_prediction_upper
            else quality.quality_prediction
        )
        if sulfur is not None and sulfur > self.policy.sulfur_limit_mg_kg:
            violations.append("SULFUR_LIMIT")
        if (
            quality.quality_prediction is not None
            and quality.quality_prediction > self.policy.sulfur_limit_mg_kg
        ):
            violations.append("SULFUR_LIMIT")

        metrics = quality.metrics
        if metrics is None:
            if self.policy.require_commercial_metrics:
                violations.append("MISSING_COMMERCIAL_QUALITY_METRICS")
        else:
            if metrics.sulfur_mg_kg is None:
                violations.append("MISSING_SULFUR_METRIC")
            elif metrics.sulfur_mg_kg > self.policy.sulfur_limit_mg_kg:
                violations.append("SULFUR_LIMIT")
            if metrics.t95_c is None:
                violations.append("MISSING_T95")
            elif metrics.t95_c > self.policy.t95_max_c:
                violations.append("T95_LIMIT")
            if metrics.density_kg_m3 is None:
                violations.append("MISSING_DENSITY")
            elif quality.grade == "SUMMER":
                if not (
                    self.policy.summer_density_min_kg_m3
                    <= metrics.density_kg_m3
                    <= self.policy.summer_density_max_kg_m3
                ):
                    violations.append("DENSITY_LIMIT")
            elif quality.grade == "WINTER":
                if not (
                    self.policy.winter_density_min_kg_m3
                    <= metrics.density_kg_m3
                    <= self.policy.winter_density_max_kg_m3
                ):
                    violations.append("DENSITY_LIMIT")
            else:
                violations.append("MISSING_PRODUCT_GRADE")
            if metrics.cetane_number is None:
                violations.append("MISSING_CETANE_NUMBER")
            elif (
                quality.grade == "SUMMER"
                and metrics.cetane_number < self.policy.summer_cetane_min
            ) or (
                quality.grade == "WINTER"
                and metrics.cetane_number < self.policy.winter_cetane_min
            ):
                violations.append("CETANE_LIMIT")
            if metrics.blend_share_sum_pct is None:
                violations.append("MISSING_BLEND_SHARE_SUM")
            elif not math.isclose(
                metrics.blend_share_sum_pct,
                self.policy.blend_share_total_pct,
                rel_tol=0.0,
                abs_tol=self.policy.blend_share_tolerance_pct,
            ):
                violations.append("BLEND_SHARE_SUM")
            if metrics.additive_pct is None:
                violations.append("MISSING_ADDITIVE_DOSAGE")
            elif not 0.0 <= metrics.additive_pct <= self.policy.additive_max_pct:
                violations.append("ADDITIVE_LIMIT")

        if quality.violation_probability is None:
            violations.append("MISSING_VIOLATION_PROBABILITY")
        elif (
            self.policy.max_violation_probability is not None
            and quality.violation_probability > self.policy.max_violation_probability
        ):
            violations.append("VIOLATION_PROBABILITY")

        if quality.data_confidence is None:
            violations.append("MISSING_QUALITY_CONFIDENCE")
        elif quality.data_confidence in self.policy.rejected_confidences:
            violations.append("LOW_QUALITY_CONFIDENCE")

    def _check_reliability(
        self,
        reliability: ReliabilityAssessment,
        violations: list[str],
    ) -> None:
        if reliability.reliability_risk is None:
            violations.append("MISSING_RELIABILITY_RISK")
        elif reliability.reliability_risk in self.policy.rejected_reliability_risks:
            violations.append("RELIABILITY_RISK")

        if reliability.risk_score is None:
            violations.append("MISSING_RELIABILITY_SCORE")
        if reliability.data_confidence is None:
            violations.append("MISSING_RELIABILITY_CONFIDENCE")
        elif reliability.data_confidence in self.policy.rejected_confidences:
            violations.append("LOW_RELIABILITY_CONFIDENCE")
