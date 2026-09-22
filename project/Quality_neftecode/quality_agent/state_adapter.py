from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd

from .contracts import ProcessState
from .feature_pipeline import InMemoryHistoryProvider


@dataclass(frozen=True)
class AdaptedState:
    sources: Mapping[str, Mapping[str, float]]
    warnings: tuple[str, ...]


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _quality_value(quality: Mapping[str, Any], key: str) -> tuple[float | None, str | None]:
    raw = quality.get(key)
    if isinstance(raw, Mapping):
        return _finite_number(raw.get("value")), str(raw.get("source") or "").lower() or None
    source = str(quality.get("source") or "").lower() or None
    return _finite_number(raw), source


def adapt_process_state(state: ProcessState) -> AdaptedState:
    sources: dict[str, dict[str, float]] = {"avt": {}, "hyd": {}}
    warnings: list[str] = []
    not_yet_available = state.data_quality.get("not_yet_available", [])
    unavailable_items = (
        not_yet_available if isinstance(not_yet_available, list) else [not_yet_available]
    )
    warnings.extend(f"NOT_YET_AVAILABLE:{item}" for item in unavailable_items if item)

    # Controls override duplicated telemetry fields because they are the
    # canonical current values supplied to candidate generation.
    merged_telemetry = {**state.telemetry, **state.current_controls}
    for name, raw_value in merged_telemetry.items():
        value = _finite_number(raw_value)
        if value is None:
            continue
        lowered = name.lower()
        if lowered.startswith("avt_"):
            sources["avt"][name.split("_", 1)[1].upper()] = value
        elif lowered.startswith("hyd_"):
            if lowered == "hyd_q21" and value == 307.0:
                warnings.append("Q21_OUTLIER_307_NOT_INGESTED")
                continue
            sources["hyd"][name.split("_", 1)[1].upper()] = value
        elif lowered.startswith(("blend_", "cetane_additive_")):
            # These controls are inputs to the downstream blend model, not
            # hydrotreater features.
            continue
        else:
            warnings.append(f"UNMAPPED_TELEMETRY:{name}")

    pak_sulfur = None
    if "pak_mg_sulfur" in state.quality:
        pak_sulfur, _ = _quality_value(state.quality, "pak_mg_sulfur")
    elif "24_2000_mg_sulfur" in state.quality:
        pak_sulfur, _ = _quality_value(state.quality, "24_2000_mg_sulfur")
    elif "mg_sulfur" in state.quality:
        value, source = _quality_value(state.quality, "mg_sulfur")
        if source == "pak":
            pak_sulfur = value
        elif value is not None:
            warnings.append("LIMS_VALUE_NOT_USED_AS_FEATURE")
    if pak_sulfur is not None:
        sources["pak_mg_sulfur"] = {"value": pak_sulfur}

    pak_d15 = None
    if "pak_d15" in state.quality:
        pak_d15, _ = _quality_value(state.quality, "pak_d15")
    elif "d15" in state.quality:
        value, source = _quality_value(state.quality, "d15")
        if source == "pak":
            pak_d15 = value
    if pak_d15 is not None:
        sources["pak_d15"] = {"value": pak_d15}

    sources = {source: values for source, values in sources.items() if values}
    return AdaptedState(sources=sources, warnings=tuple(sorted(set(warnings))))


def ingest_process_state(
    history: InMemoryHistoryProvider,
    state: ProcessState,
) -> tuple[str, ...]:
    adapted = adapt_process_state(state)
    timestamp = pd.Timestamp(state.timestamp)
    for source, values in adapted.sources.items():
        history.append(source, timestamp, values)
    return adapted.warnings
