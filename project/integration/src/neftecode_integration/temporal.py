from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from neftecode_orchestrator.contracts import ProcessState

LIMS_PUBLICATION_DELAY = timedelta(hours=4)
_LIMS_MEASUREMENT_KEYS = {
    "mg_sulfur",
    "sulfur_mg_kg",
    "d15",
    "density_kg_m3",
    "t95_c",
    "cetane_number",
}


def _source(value: Any, quality: Mapping[str, Any]) -> str:
    if isinstance(value, Mapping):
        return str(value.get("source") or quality.get("source") or "").lower()
    return str(quality.get("source") or "").lower()


def _available_at(value: Any, quality: Mapping[str, Any]):
    payload = value if isinstance(value, Mapping) else quality
    explicit = payload.get("available_at") or quality.get("available_at")
    if explicit is not None:
        return datetime.fromisoformat(str(explicit))
    sample = payload.get("sample_timestamp") or quality.get("sample_timestamp")
    if sample is None:
        return None
    return datetime.fromisoformat(str(sample)) + LIMS_PUBLICATION_DELAY


def hide_future_lims(state: ProcessState) -> ProcessState:
    """Remove LIMS measurements that were not available at runtime yet."""

    quality = dict(state.quality)
    hidden: list[str] = []
    for key in list(quality):
        if key not in _LIMS_MEASUREMENT_KEYS:
            continue
        value = quality[key]
        if _source(value, quality) != "lims":
            continue
        available_at = _available_at(value, quality)
        # Missing availability metadata is fail-closed for a laboratory value.
        decision_time = state.timestamp
        if available_at is not None:
            if decision_time.tzinfo is None and available_at.tzinfo is not None:
                decision_time = decision_time.replace(tzinfo=available_at.tzinfo)
            elif decision_time.tzinfo is not None and available_at.tzinfo is None:
                available_at = available_at.replace(tzinfo=decision_time.tzinfo)
        if available_at is None or decision_time < available_at:
            quality.pop(key)
            hidden.append(key)

    if not hidden:
        return state
    data_quality = dict(state.data_quality)
    existing = data_quality.get("not_yet_available", [])
    withheld = list(existing) if isinstance(existing, list) else [existing]
    withheld.extend(f"lims:{key}" for key in hidden)
    data_quality["not_yet_available"] = sorted(set(withheld))
    return state.model_copy(update={"quality": quality, "data_quality": data_quality})
