from __future__ import annotations

import json
import math
import threading
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from .contracts import CandidateAction, QualityAssessment
from .feature_pipeline import FeatureDiagnostics
from .router import PakHealthAssessment


@dataclass(frozen=True)
class ShadowPromotionGates:
    minimum_matched_samples: int = 100
    minimum_observation_days: float = 60.0
    minimum_fallback_samples: int = 20
    maximum_selected_mae_vs_pak_ratio: float = 1.0
    maximum_brier_vs_prevalence_ratio: float = 1.0
    minimum_interval_coverage: float = 0.75

    def validate(self) -> None:
        if self.minimum_matched_samples < 1:
            raise ValueError("minimum_matched_samples must be positive")
        if self.minimum_observation_days < 0:
            raise ValueError("minimum_observation_days must be non-negative")
        if self.minimum_fallback_samples < 0:
            raise ValueError("minimum_fallback_samples must be non-negative")
        if self.maximum_selected_mae_vs_pak_ratio <= 0:
            raise ValueError("maximum_selected_mae_vs_pak_ratio must be positive")
        if self.maximum_brier_vs_prevalence_ratio <= 0:
            raise ValueError("maximum_brier_vs_prevalence_ratio must be positive")
        if not 0 <= self.minimum_interval_coverage <= 1:
            raise ValueError("minimum_interval_coverage must be in [0, 1]")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(cast(Any, value)))
    if isinstance(value, (datetime, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _numeric_ratio(numerator: object, denominator: object) -> float:
    """Return a safe ratio for JSON-native numeric shadow metrics."""
    if isinstance(numerator, bool) or isinstance(denominator, bool):
        return math.inf
    if not isinstance(numerator, (int, float)) or not isinstance(denominator, (int, float)):
        return math.inf
    if denominator == 0:
        return math.inf
    return float(numerator) / float(denominator)


def _assessment_payload(assessment: QualityAssessment) -> dict[str, Any]:
    return assessment.model_dump(mode="json")


class ShadowLogger:
    """Append-only JSONL log for delayed, LIMS-grounded model evaluation."""

    def __init__(self, path: str | Path, include_features: bool = True) -> None:
        self.path = Path(path)
        self.include_features = include_features
        self._lock = threading.Lock()

    def _append(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            _json_safe(payload),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded + "\n")

    def log_prediction(
        self,
        *,
        timestamp: datetime,
        candidate: CandidateAction | None,
        pak_health: PakHealthAssessment,
        point_source: str,
        pak_value: float | None,
        selected: QualityAssessment,
        primary: QualityAssessment,
        telemetry_fallback: QualityAssessment,
        feature_values: Mapping[str, float],
        feature_diagnostics: FeatureDiagnostics,
        primary_manifest: Mapping[str, Any],
        fallback_manifest: Mapping[str, Any],
    ) -> str:
        prediction_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "event_type": "prediction",
            "prediction_id": prediction_id,
            "logged_at": datetime.now(UTC),
            "process_timestamp": timestamp,
            "candidate": None if candidate is None else candidate.model_dump(mode="json"),
            "pak_health": pak_health,
            "point_source": point_source,
            "pak_value": pak_value,
            "selected": _assessment_payload(selected),
            "primary": _assessment_payload(primary),
            "telemetry_fallback": _assessment_payload(telemetry_fallback),
            "feature_diagnostics": feature_diagnostics,
            "model_metadata": {
                "primary": {
                    "training_id": primary_manifest.get("training_id"),
                    "created_at_utc": primary_manifest.get("created_at_utc"),
                    "schema_version": primary_manifest.get("schema_version"),
                    "schema_sha256": primary_manifest.get("schema_sha256"),
                    "model_variant": primary_manifest.get("model_variant"),
                    "regression_mode": primary_manifest.get("regression_mode"),
                },
                "telemetry_fallback": {
                    "training_id": fallback_manifest.get("training_id"),
                    "created_at_utc": fallback_manifest.get("created_at_utc"),
                    "schema_version": fallback_manifest.get("schema_version"),
                    "schema_sha256": fallback_manifest.get("schema_sha256"),
                    "model_variant": fallback_manifest.get("model_variant"),
                    "regression_mode": fallback_manifest.get("regression_mode"),
                },
            },
        }
        if self.include_features:
            payload["feature_values"] = feature_values
        self._append(payload)
        return prediction_id

    def log_lims(
        self,
        *,
        sample_timestamp: datetime | str,
        sulfur_mg_kg: float,
        sample_id: str | None = None,
    ) -> None:
        value = float(sulfur_mg_kg)
        if not math.isfinite(value):
            raise ValueError("LIMS sulfur value must be finite")
        timestamp = pd.Timestamp(sample_timestamp)
        if pd.isna(timestamp):
            raise ValueError("LIMS sample timestamp is invalid")
        self._append(
            {
                "event_type": "lims",
                "logged_at": datetime.now(UTC),
                "sample_timestamp": timestamp,
                "sample_id": sample_id,
                "sulfur_mg_kg": value,
            }
        )

    def read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid shadow JSONL at line {line_number}") from error
            if isinstance(event, dict):
                events.append(event)
        return events

    @staticmethod
    def _metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, float | int | None]:
        actual_values = pd.to_numeric(actual, errors="coerce")
        predicted_values = pd.to_numeric(predicted, errors="coerce")
        valid = actual_values.notna() & predicted_values.notna()
        if not valid.any():
            return {"count": 0, "mae": None, "rmse": None}
        error = predicted_values[valid] - actual_values[valid]
        return {
            "count": int(valid.sum()),
            "mae": float(error.abs().mean()),
            "rmse": float(np.sqrt(np.mean(np.square(error)))),
        }

    def summary(
        self,
        *,
        tolerance_min: float = 10.0,
        sulfur_limit: float = 10.0,
    ) -> dict[str, Any]:
        if tolerance_min < 0:
            raise ValueError("tolerance_min must be non-negative")
        events = self.read_events()
        predictions = [event for event in events if event.get("event_type") == "prediction"]
        lims = [event for event in events if event.get("event_type") == "lims"]
        base: dict[str, Any] = {
            "prediction_events": len(predictions),
            "lims_events": len(lims),
            "matched_samples": 0,
            "tolerance_min": tolerance_min,
            "metrics": {},
            "by_point_source": {},
        }
        if not predictions or not lims:
            return base

        prediction_rows = []
        for event in predictions:
            prediction_rows.append(
                {
                    "prediction_timestamp": event.get("process_timestamp"),
                    "prediction_id": event.get("prediction_id"),
                    "point_source": event.get("point_source"),
                    "selected": (event.get("selected") or {}).get("quality_prediction"),
                    "selected_lower": (event.get("selected") or {}).get("prediction_lower"),
                    "selected_upper": (event.get("selected") or {}).get("prediction_upper"),
                    "primary": (event.get("primary") or {}).get("quality_prediction"),
                    "fallback": (event.get("telemetry_fallback") or {}).get("quality_prediction"),
                    "probability": (event.get("selected") or {}).get("violation_probability"),
                    "pak": event.get("pak_value"),
                }
            )
        prediction_frame = pd.DataFrame(prediction_rows)
        prediction_frame["prediction_timestamp"] = pd.to_datetime(
            prediction_frame["prediction_timestamp"], utc=True, errors="coerce"
        )
        prediction_frame = prediction_frame.dropna(subset=["prediction_timestamp"]).sort_values(
            "prediction_timestamp"
        )

        lims_frame = pd.DataFrame(
            {
                "sample_timestamp": [event.get("sample_timestamp") for event in lims],
                "sample_id": [event.get("sample_id") for event in lims],
                "actual": [event.get("sulfur_mg_kg") for event in lims],
            }
        )
        lims_frame["sample_timestamp"] = pd.to_datetime(
            lims_frame["sample_timestamp"], utc=True, errors="coerce"
        )
        lims_frame = lims_frame.dropna(subset=["sample_timestamp"]).sort_values("sample_timestamp")
        if prediction_frame.empty or lims_frame.empty:
            return base

        matched = pd.merge_asof(
            lims_frame,
            prediction_frame,
            left_on="sample_timestamp",
            right_on="prediction_timestamp",
            direction="backward",
            tolerance=pd.Timedelta(minutes=tolerance_min),
        )
        paired = matched[matched["prediction_id"].notna()].copy()
        base["matched_samples"] = len(paired)
        if paired.empty:
            return base

        first_sample = paired["sample_timestamp"].min()
        last_sample = paired["sample_timestamp"].max()
        base["observation_period"] = {
            "first_sample": first_sample.isoformat(),
            "last_sample": last_sample.isoformat(),
            "days": float((last_sample - first_sample).total_seconds() / 86_400.0),
        }

        base["metrics"] = {
            name: self._metrics(paired["actual"], paired[column])
            for name, column in {
                "selected": "selected",
                "primary": "primary",
                "telemetry_fallback": "fallback",
                "pak": "pak",
            }.items()
        }
        probability = pd.to_numeric(paired["probability"], errors="coerce")
        actual = pd.to_numeric(paired["actual"], errors="coerce")
        valid_probability = probability.notna() & actual.notna()
        if valid_probability.any():
            target = (actual[valid_probability] > sulfur_limit).astype(float)
            prevalence = float(target.mean())
            base["classification"] = {
                "count": int(valid_probability.sum()),
                "brier": float(np.mean(np.square(probability[valid_probability] - target))),
                "prevalence": prevalence,
                "prevalence_brier": float(np.mean(np.square(prevalence - target))),
                "sulfur_limit": sulfur_limit,
            }

        lower = pd.to_numeric(paired["selected_lower"], errors="coerce")
        upper = pd.to_numeric(paired["selected_upper"], errors="coerce")
        valid_interval = actual.notna() & lower.notna() & upper.notna()
        if valid_interval.any():
            covered = (actual[valid_interval] >= lower[valid_interval]) & (
                actual[valid_interval] <= upper[valid_interval]
            )
            base["interval"] = {
                "count": int(valid_interval.sum()),
                "coverage": float(covered.mean()),
                "average_width": float((upper[valid_interval] - lower[valid_interval]).mean()),
            }

        by_source: dict[str, Any] = {}
        for point_source, group in paired.groupby("point_source", dropna=False):
            by_source[str(point_source)] = self._metrics(group["actual"], group["selected"])
        base["by_point_source"] = by_source
        return base


def evaluate_shadow_readiness(
    summary: Mapping[str, Any],
    gates: ShadowPromotionGates | None = None,
) -> dict[str, Any]:
    """Evaluate predeclared evidence gates; never promotes a model automatically."""
    policy = gates or ShadowPromotionGates()
    policy.validate()
    checks: list[dict[str, Any]] = []

    def add_check(name: str, actual: Any, expected: str, passed: bool) -> None:
        checks.append({"name": name, "actual": actual, "expected": expected, "passed": passed})

    matched = int(summary.get("matched_samples", 0))
    days = float((summary.get("observation_period") or {}).get("days", 0.0))
    fallback_count = int(
        ((summary.get("by_point_source") or {}).get("telemetry_fallback") or {}).get("count", 0)
    )
    add_check(
        "matched_samples",
        matched,
        f">= {policy.minimum_matched_samples}",
        matched >= policy.minimum_matched_samples,
    )
    add_check(
        "observation_days",
        days,
        f">= {policy.minimum_observation_days}",
        days >= policy.minimum_observation_days,
    )
    add_check(
        "fallback_samples",
        fallback_count,
        f">= {policy.minimum_fallback_samples}",
        fallback_count >= policy.minimum_fallback_samples,
    )
    evidence_ready = all(check["passed"] for check in checks)
    if not evidence_ready:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "automatic_promotion": False,
            "gates": asdict(policy),
            "checks": checks,
        }

    metrics = summary.get("metrics") or {}
    selected_mae = (metrics.get("selected") or {}).get("mae")
    pak_mae = (metrics.get("pak") or {}).get("mae")
    regression_ratio = _numeric_ratio(selected_mae, pak_mae)
    add_check(
        "selected_mae_vs_pak_ratio",
        regression_ratio,
        f"<= {policy.maximum_selected_mae_vs_pak_ratio}",
        regression_ratio <= policy.maximum_selected_mae_vs_pak_ratio,
    )

    classification = summary.get("classification") or {}
    brier = classification.get("brier")
    prevalence_brier = classification.get("prevalence_brier")
    brier_ratio = _numeric_ratio(brier, prevalence_brier)
    add_check(
        "brier_vs_prevalence_ratio",
        brier_ratio,
        f"<= {policy.maximum_brier_vs_prevalence_ratio}",
        brier_ratio <= policy.maximum_brier_vs_prevalence_ratio,
    )

    coverage = (summary.get("interval") or {}).get("coverage")
    interval_coverage = float(coverage) if coverage is not None else -math.inf
    add_check(
        "interval_coverage",
        coverage,
        f">= {policy.minimum_interval_coverage}",
        interval_coverage >= policy.minimum_interval_coverage,
    )
    quality_ready = all(check["passed"] for check in checks)
    return {
        "status": "READY_FOR_REVIEW" if quality_ready else "NOT_READY",
        "automatic_promotion": False,
        "gates": asdict(policy),
        "checks": checks,
    }
