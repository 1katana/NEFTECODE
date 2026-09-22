from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from .agent import QualityAgent
from .contracts import CandidateAction, DataConfidence, ProcessState, QualityAssessment
from .counterfactual import CandidateEffectConfig
from .feature_pipeline import InMemoryHistoryProvider
from .features import FeatureConfig
from .state_adapter import ingest_process_state

if TYPE_CHECKING:
    from .shadow import ShadowLogger

PakHealth = Literal[
    "OK",
    "SUSPECT",
    "JUMP_UNCONFIRMED",
    "FLATLINE",
    "STALE",
    "MISSING",
]
PointPolicy = Literal["model", "pak_passthrough"]


@dataclass(frozen=True)
class PakHealthAssessment:
    status: PakHealth
    age_min: float | None
    flatline_age_min: float | None


def _quality_flags(state: ProcessState) -> set[str]:
    flags: set[str] = set()
    for key in ("missing", "stale", "flatline", "outlier"):
        value = state.data_quality.get(key, [])
        values = value if isinstance(value, list) else [value]
        for item in values:
            flags.add(f"{key}:{str(item).lower()}")
    return flags


def _mentions_sulfur_pak(flag: str) -> bool:
    return "pak_mg_sulfur" in flag or "mg_sulfur" in flag or "24_2000_mg_sulfur" in flag


def assess_pak_sulfur_health(
    history: InMemoryHistoryProvider,
    state: ProcessState,
    stale_after_min: float = 20.0,
    suspect_flatline_min: float = 30.0,
    invalid_flatline_min: float = 60.0,
    jump_abs_threshold: float | None = None,
) -> PakHealthAssessment:
    flags = _quality_flags(state)
    sulfur_flags = {flag for flag in flags if _mentions_sulfur_pak(flag)}
    if any(flag.startswith("missing:") for flag in sulfur_flags):
        return PakHealthAssessment("MISSING", None, None)
    if any(flag.startswith("stale:") for flag in sulfur_flags):
        return PakHealthAssessment("STALE", None, None)
    if any(flag.startswith("flatline:") for flag in sulfur_flags):
        return PakHealthAssessment("FLATLINE", None, invalid_flatline_min)
    if any(flag.startswith("outlier:") for flag in sulfur_flags):
        return PakHealthAssessment("JUMP_UNCONFIRMED", None, None)

    timestamp = pd.Timestamp(state.timestamp)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    frame = history.frame("pak_mg_sulfur", timestamp)
    if frame.empty or "value" not in frame:
        return PakHealthAssessment("MISSING", None, None)

    latest_timestamp = pd.Timestamp(frame["date"].iloc[-1])
    age_min = max(0.0, (timestamp - latest_timestamp).total_seconds() / 60.0)
    if age_min > stale_after_min:
        return PakHealthAssessment("STALE", age_min, None)

    values = frame["value"].to_numpy(dtype=float)
    dates = frame["date"].to_numpy(dtype="datetime64[ns]")
    latest_value = values[-1]
    if latest_value == 307.0 or latest_value >= 100.0:
        return PakHealthAssessment("JUMP_UNCONFIRMED", age_min, None)
    start_index = len(values) - 1
    while start_index > 0 and (
        values[start_index - 1] == latest_value
        or (np.isnan(values[start_index - 1]) and np.isnan(latest_value))
    ):
        start_index -= 1
    run_start = pd.Timestamp(dates[start_index])
    flatline_age_min = max(0.0, (timestamp - run_start).total_seconds() / 60.0)
    if flatline_age_min >= invalid_flatline_min:
        return PakHealthAssessment("FLATLINE", age_min, flatline_age_min)
    if flatline_age_min >= suspect_flatline_min:
        return PakHealthAssessment("SUSPECT", age_min, flatline_age_min)
    if jump_abs_threshold is not None and len(values) >= 2:
        recent_deltas = np.abs(np.diff(values[-3:]))
        if (recent_deltas >= jump_abs_threshold).any():
            return PakHealthAssessment("JUMP_UNCONFIRMED", age_min, flatline_age_min)
    return PakHealthAssessment("OK", age_min, flatline_age_min)


def _with_router_warning(
    assessment: QualityAssessment,
    warning: str,
    downgrade: bool,
) -> QualityAssessment:
    confidence = assessment.data_confidence
    if downgrade and confidence in {DataConfidence.HIGH, DataConfidence.MEDIUM}:
        confidence = DataConfidence.LOW
    return assessment.model_copy(
        update={
            "data_confidence": confidence,
            "warnings": sorted({*assessment.warnings, warning}),
        }
    )


def apply_pak_point_policy(
    assessment: QualityAssessment,
    pak_value: float | None,
) -> QualityAssessment:
    """Use a healthy PAK value as point estimate while retaining model risk outputs."""
    if assessment.quality_prediction is None or pak_value is None or not np.isfinite(pak_value):
        return assessment

    point = round(float(pak_value), 3)
    lower = assessment.prediction_lower
    upper = assessment.prediction_upper
    if lower is not None:
        lower = min(lower, point)
    if upper is not None:
        upper = max(upper, point)
    return assessment.model_copy(
        update={
            "quality_prediction": point,
            "prediction_lower": lower,
            "prediction_upper": upper,
            "warnings": sorted({*assessment.warnings, "POINT_ESTIMATE_PAK_PASSTHROUGH"}),
        }
    )


def _latest_pak_value(
    history: InMemoryHistoryProvider,
    timestamp: pd.Timestamp | str,
) -> float | None:
    frame = history.frame("pak_mg_sulfur", timestamp)
    if frame.empty or "value" not in frame:
        return None
    value = float(frame["value"].iloc[-1])
    return value if np.isfinite(value) else None


class QualityAgentRouter:
    """Route invalid sulfur-PAK states to a separately trained telemetry-only model."""

    def __init__(
        self,
        primary_artifacts_dir: str | Path,
        telemetry_fallback_artifacts_dir: str | Path,
        config: FeatureConfig | None = None,
        history: InMemoryHistoryProvider | None = None,
        point_policy: PointPolicy = "model",
        shadow_logger: ShadowLogger | None = None,
        candidate_effect_config: CandidateEffectConfig | None = None,
    ) -> None:
        if point_policy not in {"model", "pak_passthrough"}:
            raise ValueError(f"Unsupported point policy: {point_policy!r}")
        shared_history = history or InMemoryHistoryProvider()
        self.history = shared_history
        self.point_policy = point_policy
        self.shadow_logger = shadow_logger
        self.last_shadow_prediction_id: str | None = None
        self.primary = QualityAgent(
            primary_artifacts_dir,
            config,
            shared_history,
            candidate_effect_config,
        )
        self.telemetry_fallback = QualityAgent(
            telemetry_fallback_artifacts_dir,
            config,
            shared_history,
            candidate_effect_config,
        )

    def predict(
        self,
        state: ProcessState,
        candidate: CandidateAction | None = None,
        *,
        ingest_state: bool = True,
    ) -> QualityAssessment:
        adapter_warnings = list(ingest_process_state(self.history, state)) if ingest_state else []
        health = assess_pak_sulfur_health(
            self.history,
            state,
            jump_abs_threshold=self.primary.schema.pak_sulfur_jump_abs_threshold,
        )
        invalid_pak = health.status in {"FLATLINE", "STALE", "MISSING", "JUMP_UNCONFIRMED"}
        primary_result: QualityAssessment | None
        fallback_result: QualityAssessment | None
        if invalid_pak:
            fallback_result = self.telemetry_fallback.predict_from_history(
                state,
                candidate,
                adapter_warnings,
            )
            result = _with_router_warning(
                fallback_result,
                f"MODEL_FALLBACK_TELEMETRY_ONLY:PAK_SULFUR_{health.status}",
                downgrade=True,
            )
            primary_result = (
                self.primary.predict_from_history(
                    state,
                    candidate,
                    adapter_warnings,
                )
                if self.shadow_logger is not None
                else None
            )
            point_source = "telemetry_fallback"
        else:
            primary_result = self.primary.predict_from_history(
                state,
                candidate,
                adapter_warnings,
            )
            fallback_result = (
                self.telemetry_fallback.predict_from_history(
                    state,
                    candidate,
                    adapter_warnings,
                )
                if self.shadow_logger is not None
                else None
            )
            result = primary_result
            pak_value = _latest_pak_value(self.history, state.timestamp)
            if self.point_policy == "pak_passthrough" and (
                candidate is None or candidate.is_no_change
            ):
                result = apply_pak_point_policy(result, pak_value)
                point_source = "pak" if result is not primary_result else "primary_model"
            else:
                point_source = "primary_model"
            if health.status == "SUSPECT":
                result = _with_router_warning(
                    result,
                    "PAK_SULFUR_SUSPECT_FLATLINE",
                    downgrade=True,
                )
            elif health.status == "JUMP_UNCONFIRMED":
                result = _with_router_warning(
                    result,
                    "PAK_SULFUR_JUMP_UNCONFIRMED",
                    downgrade=True,
                )

        if (
            self.shadow_logger is not None
            and primary_result is not None
            and fallback_result is not None
        ):
            try:
                vector = self.primary.feature_pipeline.build(state.timestamp)
                self.last_shadow_prediction_id = self.shadow_logger.log_prediction(
                    timestamp=state.timestamp,
                    candidate=candidate,
                    pak_health=health,
                    point_source=point_source,
                    pak_value=_latest_pak_value(self.history, state.timestamp),
                    selected=result,
                    primary=primary_result,
                    telemetry_fallback=fallback_result,
                    feature_values=vector.values,
                    feature_diagnostics=vector.diagnostics,
                    primary_manifest=self.primary.manifest,
                    fallback_manifest=self.telemetry_fallback.manifest,
                )
            except (OSError, TypeError, ValueError):
                result = _with_router_warning(result, "SHADOW_LOG_WRITE_FAILED", downgrade=False)
        return result
