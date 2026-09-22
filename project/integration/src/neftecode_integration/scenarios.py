from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .models import EvaluationRequest


class ScenarioDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    history_limit: int | None = Field(default=None, ge=0)
    history_tail_state_overrides: list[dict[str, Any]] = Field(default_factory=list)
    request_overrides: dict[str, Any] = Field(default_factory=dict)
    state_overrides: dict[str, Any] = Field(default_factory=dict)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class ScenarioCatalog:
    def __init__(self, catalog_path: str | Path, base_request_path: str | Path) -> None:
        self.catalog_path = Path(catalog_path)
        self.base_request_path = Path(base_request_path)
        payload = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8")) or {}
        raw = payload.get("scenarios", payload)
        if not isinstance(raw, dict):
            raise TypeError("scenario catalog must contain a scenarios mapping")
        self.scenarios = {
            str(name): ScenarioDefinition.model_validate(definition)
            for name, definition in raw.items()
        }

    def summary(self) -> list[dict[str, str]]:
        return [
            {
                "scenario_id": scenario_id,
                "title": definition.title,
                "description": definition.description,
            }
            for scenario_id, definition in self.scenarios.items()
        ]

    def build(self, scenario_id: str) -> EvaluationRequest:
        try:
            definition = self.scenarios[scenario_id]
        except KeyError as error:
            raise KeyError(f"unknown scenario: {scenario_id}") from error
        base = json.loads(self.base_request_path.read_text(encoding="utf-8"))
        payload = _deep_merge(base, definition.request_overrides)
        payload["run_id"] = f"scenario-{scenario_id}"
        payload["process_state"] = _deep_merge(payload["process_state"], definition.state_overrides)
        payload["process_state"].setdefault("data_quality", {})["replace_history"] = True
        if definition.history_tail_state_overrides:
            available_count = min(
                len(payload["history"]), len(definition.history_tail_state_overrides)
            )
            tail_start = len(payload["history"]) - available_count
            overrides = (
                definition.history_tail_state_overrides[-available_count:]
                if available_count
                else []
            )
            for index, state_overrides in zip(
                range(tail_start, len(payload["history"])),
                overrides,
                strict=True,
            ):
                payload["history"][index] = _deep_merge(
                    payload["history"][index],
                    state_overrides,
                )
        if definition.history_limit is not None:
            payload["history"] = payload["history"][-definition.history_limit :]
            if definition.history_limit == 0:
                payload["history"] = []
        return EvaluationRequest.model_validate(payload)
