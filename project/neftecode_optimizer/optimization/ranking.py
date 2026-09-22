"""Transparent lexicographic ranking for safe scenarios only."""

from __future__ import annotations

from .models import ControlConfig, ScenarioEvaluation


class LexicographicRanker:
    """Rank by quality risk, reliability risk, gain, then action size.

    No weights are introduced. Economics must be available for every scenario
    or disabled for all. Action size is dimensionless: sum(abs(delta)/max_delta).
    """

    def __init__(self, control_config: ControlConfig | None = None) -> None:
        self.control_config = ControlConfig.model_validate(
            control_config or ControlConfig()
        ).model_copy(deep=True)

    def rank(self, scenarios: list[ScenarioEvaluation]) -> list[ScenarioEvaluation]:
        scenarios = [ScenarioEvaluation.model_validate(item) for item in scenarios]
        unsafe = [
            item.candidate.candidate_id
            for item in scenarios
            if not item.safety.constraint_passed
        ]
        if unsafe:
            raise ValueError(f"unsafe scenarios cannot be ranked: {unsafe}")
        for item in scenarios:
            if not item.candidate.changes.keys() <= self.control_config.controls.keys():
                raise ValueError("ranking requires specs for every changed control")
            if (
                item.quality is None
                or item.reliability is None
                or item.quality.violation_probability is None
                or item.reliability.risk_score is None
            ):
                raise ValueError("ranking requires complete risk assessments")
        gains_present = [item.production_gain is not None for item in scenarios]
        if any(gains_present) and not all(gains_present):
            raise ValueError("economic gain must be supplied for every safe candidate")

        ranked = sorted(scenarios, key=self._key)
        return [
            item.model_copy(
                update={
                    "rank": position,
                    "score_components": self._score_components(item),
                }
            )
            for position, item in enumerate(ranked, start=1)
        ]

    def _key(
        self, item: ScenarioEvaluation
    ) -> tuple[float, float, float, float, float, str]:
        quality = item.quality
        reliability_assessment = item.reliability
        assert quality is not None
        assert reliability_assessment is not None
        probability = quality.violation_probability
        reliability = reliability_assessment.risk_score
        assert probability is not None
        assert reliability is not None
        gain = item.production_gain if item.production_gain is not None else 0.0
        relative_cost = (
            quality.metrics.relative_cost
            if quality.metrics is not None and quality.metrics.relative_cost is not None
            else float("inf")
        )
        return (
            probability,
            reliability,
            relative_cost,
            -gain,
            self._action_size(item),
            item.candidate.candidate_id,
        )

    def _score_components(
        self, item: ScenarioEvaluation
    ) -> dict[str, float | str | None]:
        quality = item.quality
        reliability = item.reliability
        assert quality is not None
        assert reliability is not None
        return {
            "violation_probability": quality.violation_probability,
            "reliability_risk_score": reliability.risk_score,
            "relative_cost": (
                quality.metrics.relative_cost if quality.metrics is not None else None
            ),
            "production_gain": item.production_gain,
            "action_size": self._action_size(item),
            "ranking": "lexicographic",
        }

    def _action_size(self, item: ScenarioEvaluation) -> float:
        return sum(
            (
                abs(delta) / self.control_config.controls[tag].max_delta
                for tag, delta in item.candidate.deltas.items()
            ),
            0.0,
        )
