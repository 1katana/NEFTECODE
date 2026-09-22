from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist

import yaml

from .contracts import CandidateAction, ProcessState, QualityAssessment


@dataclass(frozen=True)
class CandidateEffectConfig:
    """Transparent scenario model for effects not identified by historical replay.

    Coefficients are deliberately isolated from the trained CatBoost artifacts. They
    are engineering assumptions for editable what-if scenarios, not causal estimates.
    """

    response_time_hours: float = 1.0
    sulfur_limit_mg_kg: float = 10.0
    sulfur_sensitivity: dict[str, float] = field(
        default_factory=lambda: {
            "hyd_t6": -0.03,  # mg/kg per degC
            "hyd_f9": 0.015,  # mg/kg per t/h
            "hyd_p13": -1.5,  # mg/kg per MPa
        }
    )

    def validate(self) -> None:
        if self.response_time_hours <= 0:
            raise ValueError("response_time_hours must be positive")
        if self.sulfur_limit_mg_kg <= 0:
            raise ValueError("sulfur_limit_mg_kg must be positive")

    @classmethod
    def from_yaml(cls, path: str | Path) -> CandidateEffectConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        raw = payload.get("candidate_effect_model", {})
        if not isinstance(raw, dict):
            raise TypeError("candidate_effect_model must be a mapping")
        sensitivity = raw.get("sulfur_sensitivity")
        if sensitivity is not None and not isinstance(sensitivity, dict):
            raise TypeError("candidate sulfur_sensitivity must be a mapping")
        config = cls(
            response_time_hours=float(raw.get("response_time_hours", 1.0)),
            sulfur_limit_mg_kg=float(payload.get("sulfur_limit", 10.0)),
            sulfur_sensitivity=(
                {str(key).lower(): float(value) for key, value in sensitivity.items()}
                if sensitivity is not None
                else cls().sulfur_sensitivity
            ),
        )
        config.validate()
        return config


def _candidate_deltas(state: ProcessState, candidate: CandidateAction) -> dict[str, float]:
    deltas = {key.lower(): float(value) for key, value in candidate.delta.items()}
    for key, proposed in candidate.changes.items():
        lowered = key.lower()
        if lowered in deltas:
            continue
        current = state.current_controls.get(key)
        if current is None:
            current = state.telemetry.get(key)
        if current is not None:
            deltas[lowered] = float(proposed) - float(current)
    return deltas


def apply_candidate_effect(
    assessment: QualityAssessment,
    state: ProcessState,
    candidate: CandidateAction,
    config: CandidateEffectConfig,
) -> QualityAssessment:
    """Apply a horizon-aware linear sulfur response to a baseline assessment."""

    config.validate()
    horizon = float(candidate.horizon_hours)
    downstream_prefixes = ("blend_", "cetane_additive_")
    deltas = _candidate_deltas(state, candidate)
    unsupported = sorted(
        key
        for key in deltas
        if key not in config.sulfur_sensitivity and not key.startswith(downstream_prefixes)
    )
    warnings = set(assessment.warnings)
    warnings.add("EXPERIMENTAL_LINEAR_COUNTERFACTUAL")
    warnings.add(f"CANDIDATE_HORIZON_HOURS:{horizon:g}")
    if unsupported:
        warnings.update(f"UNSUPPORTED_CANDIDATE_CONTROL:{key}" for key in unsupported)
        return assessment.model_copy(
            update={
                "quality_prediction": None,
                "prediction_lower": None,
                "prediction_upper": None,
                "violation_probability": None,
                "warnings": sorted(warnings),
                "candidate_horizon_hours": horizon,
            }
        )

    if assessment.quality_prediction is None:
        return assessment.model_copy(
            update={
                "warnings": sorted(warnings),
                "candidate_horizon_hours": horizon,
            }
        )

    response_fraction = 1.0 - math.exp(-horizon / config.response_time_hours)
    sulfur_delta = response_fraction * sum(
        deltas.get(tag, 0.0) * sensitivity for tag, sensitivity in config.sulfur_sensitivity.items()
    )
    prediction = max(0.0, float(assessment.quality_prediction) + sulfur_delta)
    lower = (
        None
        if assessment.prediction_lower is None
        else max(0.0, float(assessment.prediction_lower) + sulfur_delta)
    )
    upper = (
        None
        if assessment.prediction_upper is None
        else max(0.0, float(assessment.prediction_upper) + sulfur_delta)
    )

    probability = assessment.violation_probability
    if lower is not None and upper is not None:
        # The stored interval is the empirical 10--90% interval.
        sigma = max((upper - lower) / (2.0 * 1.2815515655446004), 0.05)
        probability = 1.0 - NormalDist(mu=prediction, sigma=sigma).cdf(config.sulfur_limit_mg_kg)

    return assessment.model_copy(
        update={
            "quality_prediction": round(prediction, 3),
            "prediction_lower": None if lower is None else round(lower, 3),
            "prediction_upper": None if upper is None else round(upper, 3),
            "violation_probability": (
                None if probability is None else round(min(max(float(probability), 0.0), 1.0), 4)
            ),
            "warnings": sorted(warnings),
            "candidate_horizon_hours": horizon,
        }
    )
