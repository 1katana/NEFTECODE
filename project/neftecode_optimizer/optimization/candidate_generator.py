"""Bounded, deterministic generation of candidate control actions."""

from __future__ import annotations

from decimal import Decimal
from itertools import combinations, product
from pathlib import Path

from .configuration import load_yaml_mapping
from .models import (
    CandidateAction,
    ControlConfig,
    ControlSpec,
    GenerationResult,
    ProcessState,
)


def load_control_config(path: str | Path) -> ControlConfig:
    return ControlConfig.model_validate(load_yaml_mapping(path))


class CandidateGenerator:
    """Generate KEEP plus bounded +/- multiples of step for configured controls.

    Safety decides whether the declared basis permits an actual recommendation.
    """

    def __init__(
        self,
        control_config: ControlConfig,
        *,
        max_changed_controls: int = 2,
        max_candidates: int = 100,
    ) -> None:
        if type(max_changed_controls) is not int or max_changed_controls < 1:
            raise ValueError("max_changed_controls must be positive")
        if type(max_candidates) is not int or max_candidates < 1:
            raise ValueError("max_candidates must include at least KEEP")
        self.control_config = ControlConfig.model_validate(control_config).model_copy(
            deep=True
        )
        self.max_changed_controls = max_changed_controls
        self.max_candidates = max_candidates

    def generate(self, state: ProcessState) -> list[CandidateAction]:
        return self.generate_with_report(state).candidates

    def generate_with_report(self, state: ProcessState) -> GenerationResult:
        state = ProcessState.model_validate(state)
        horizon = self.control_config.candidate_horizon_hours
        candidates = [CandidateAction(candidate_id="KEEP", horizon_hours=horizon)]
        proposals: dict[str, list[tuple[float, float]]] = {}

        for tag, spec in sorted(self.control_config.controls.items()):
            current = state.values.get(tag)
            if current is None:
                continue
            stepped = self._step_proposals(current, spec, limit=self.max_candidates)
            if stepped:
                proposals[tag] = stepped

        sequence = 1
        max_size = min(self.max_changed_controls, len(proposals))
        for size in range(1, max_size + 1):
            for tags in combinations(proposals, size):
                for selected in product(*(proposals[tag] for tag in tags)):
                    if len(candidates) >= self.max_candidates:
                        return GenerationResult(candidates=candidates, truncated=True)
                    changes = {tag: value for tag, (value, _) in zip(tags, selected)}
                    deltas = {tag: delta for tag, (_, delta) in zip(tags, selected)}
                    candidates.append(
                        CandidateAction(
                            candidate_id=f"C{sequence:03d}",
                            changes=changes,
                            deltas=deltas,
                            horizon_hours=horizon,
                        )
                    )
                    sequence += 1
        return GenerationResult(candidates=candidates)

    @staticmethod
    def _step_proposals(
        current: float, spec: ControlSpec, *, limit: int
    ) -> list[tuple[float, float]]:
        current_decimal = Decimal(str(current))
        step = Decimal(str(spec.step))
        max_delta = Decimal(str(spec.max_delta))
        minimum = Decimal(str(spec.minimum))
        maximum = Decimal(str(spec.maximum))
        values: list[tuple[float, float]] = []

        # An out-of-range current state cannot justify a generated action.
        if not minimum <= current_decimal <= maximum:
            return values

        # The cap prevents a tiny step / large max_delta from materializing an
        # unbounded grid when the whole search can use at most `limit` entries.
        max_levels = min(int(max_delta // step), limit)
        for level in range(1, max_levels + 1):
            for direction in (-1, 1):
                delta = step * level * direction
                proposed = current_decimal + delta
                if not minimum <= proposed <= maximum:
                    continue
                value = float(proposed)
                if value == current:
                    continue
                values.append((value, value - current))
                if len(values) >= limit:
                    return values
        return values
