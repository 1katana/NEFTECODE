from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

LAG_MINUTES = (30, 60, 120, 240, 360)
WINDOW_MINUTES = (60, 120, 240, 360)
ROLLING_STATS = ("mean", "std", "min", "max", "coverage")
PAK_FLATLINE_SUSPECT_MIN = 30.0
PAK_FLATLINE_INVALID_MIN = 60.0


@dataclass(frozen=True)
class SourceData:
    name: str
    frame: pd.DataFrame
    cadence_min: float


@dataclass(frozen=True)
class FeatureSchema:
    schema_version: str
    target_column: str
    classification_target_column: str
    all_feature_columns: tuple[str, ...]
    baseline_feature_columns: tuple[str, ...]
    forbidden_model_inputs: tuple[str, ...]
    signal_quality_rules: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> FeatureSchema:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        schema = cls(
            schema_version=str(payload["schema_version"]),
            target_column=str(payload["target"]["regression"]),
            classification_target_column=str(payload["target"]["classification"]),
            all_feature_columns=tuple(payload["all_feature_columns"]),
            baseline_feature_columns=tuple(payload["baseline_feature_columns"]),
            forbidden_model_inputs=tuple(payload.get("forbidden_model_inputs", [])),
            signal_quality_rules=payload.get("feature_rules", {}).get("signal_quality", {}),
        )
        schema.validate()
        return schema

    def validate(self) -> None:
        all_features = set(self.all_feature_columns)
        baseline = set(self.baseline_feature_columns)
        forbidden = set(self.forbidden_model_inputs)
        if len(all_features) != len(self.all_feature_columns):
            raise ValueError("Duplicate columns in all_feature_columns")
        if len(baseline) != len(self.baseline_feature_columns):
            raise ValueError("Duplicate columns in baseline_feature_columns")
        if not baseline.issubset(all_features):
            raise ValueError("Baseline feature list is not a subset of all features")
        leaked = baseline.intersection(forbidden | {self.target_column})
        if leaked:
            raise ValueError(f"Forbidden columns in baseline schema: {sorted(leaked)}")

    @property
    def required_signals(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for feature in self.baseline_feature_columns:
            base = feature.split("__", 1)[0]
            source, signal = split_signal_base(base)
            result.setdefault(source, set()).add(signal)
        return result

    @property
    def pak_sulfur_jump_abs_threshold(self) -> float | None:
        rules = self.signal_quality_rules.get("pak_mg_sulfur", {})
        if not isinstance(rules, Mapping):
            return None
        value = rules.get("jump_abs_delta_10m_train_q999_mg_kg")
        return float(value) if value is not None else None


@dataclass(frozen=True)
class FeatureDiagnostics:
    total_features: int
    available_features: int
    coverage_ratio: float
    missing_features: tuple[str, ...]
    missing_sources: tuple[str, ...]
    source_history_hours: Mapping[str, float]

    @property
    def has_complete_history(self) -> bool:
        if self.missing_sources:
            return False
        return all(hours >= 6.0 for hours in self.source_history_hours.values())


@dataclass(frozen=True)
class FeatureVector:
    timestamp: pd.Timestamp
    values: Mapping[str, float]
    diagnostics: FeatureDiagnostics

    def as_frame(self, columns: Iterable[str]) -> pd.DataFrame:
        return pd.DataFrame(
            [[self.values.get(column, np.nan) for column in columns]], columns=columns
        )


def split_signal_base(base: str) -> tuple[str, str]:
    if base.startswith("pak_mg_sulfur_"):
        return "pak_mg_sulfur", base.removeprefix("pak_mg_sulfur_")
    if base.startswith("pak_d15_"):
        return "pak_d15", base.removeprefix("pak_d15_")
    if "_" not in base:
        raise ValueError(f"Cannot determine source for feature base {base!r}")
    return tuple(base.split("_", 1))  # type: ignore[return-value]


def _safe_take(values: np.ndarray, indices: np.ndarray) -> np.ndarray:
    result = np.full(len(indices), np.nan, dtype=float)
    valid = (indices >= 0) & (indices < len(values))
    if valid.any():
        result[valid] = values[indices[valid]]
    return result


def _as_minutes(delta_ns: np.ndarray) -> np.ndarray:
    return delta_ns.astype(float) / 60_000_000_000.0


def _signal_base(source_name: str, column: str) -> str:
    return f"{source_name}_{column}"


def _rolling_block(
    times_ns: np.ndarray,
    values: np.ndarray,
    sample_ns: np.ndarray,
    window_min: int,
    cadence_min: float,
) -> dict[str, np.ndarray]:
    n_samples, n_signals = len(sample_ns), values.shape[1]
    output = {
        "mean": np.full((n_samples, n_signals), np.nan),
        "std": np.full((n_samples, n_signals), np.nan),
        "min": np.full((n_samples, n_signals), np.nan),
        "max": np.full((n_samples, n_signals), np.nan),
        "coverage": np.zeros((n_samples, n_signals), dtype=float),
    }
    window_ns = int(window_min * 60_000_000_000)
    expected = max(1, round(window_min / cadence_min)) if cadence_min > 0 else 1

    left_indices = np.searchsorted(times_ns, sample_ns - window_ns, side="right")
    right_indices = np.searchsorted(times_ns, sample_ns, side="right")
    for row_number, (left, right) in enumerate(zip(left_indices, right_indices, strict=True)):
        if right <= left:
            continue
        block = values[left:right]
        counts = np.sum(~np.isnan(block), axis=0)
        if not (counts > 0).any():
            continue
        with np.errstate(invalid="ignore"):
            output["mean"][row_number] = np.nanmean(block, axis=0)
            output["std"][row_number] = np.nanstd(block, axis=0, ddof=0)
            output["min"][row_number] = np.nanmin(block, axis=0)
            output["max"][row_number] = np.nanmax(block, axis=0)
        output["coverage"][row_number] = np.minimum(counts / expected, 1.0)
    return output


def build_source_features(
    source: SourceData,
    sample_timestamps: pd.Series,
    include_flatline_features: bool = False,
    mask_invalid_flatline: bool = False,
    jump_abs_threshold: float | None = None,
) -> tuple[pd.DataFrame, np.ndarray]:
    frame = source.frame
    value_columns = [column for column in frame.columns if column != "date"]
    times_ns = frame["date"].to_numpy(dtype="datetime64[ns]").astype("int64")
    sample_ns = sample_timestamps.to_numpy(dtype="datetime64[ns]").astype("int64")
    values = frame[value_columns].to_numpy(dtype=float, copy=False)
    current_indices = np.searchsorted(times_ns, sample_ns, side="right") - 1

    feature_data: dict[str, np.ndarray] = {}
    current_values: dict[str, np.ndarray] = {}
    for column_number, column in enumerate(value_columns):
        base = _signal_base(source.name, column)
        current = _safe_take(values[:, column_number], current_indices)
        current_values[column] = current
        feature_data[f"{base}__current"] = current

    lag_values: dict[int, dict[str, np.ndarray]] = {}
    for lag_min in LAG_MINUTES:
        lag_ns = sample_ns - int(lag_min * 60_000_000_000)
        lag_indices = np.searchsorted(times_ns, lag_ns, side="right") - 1
        lag_values[lag_min] = {}
        for column_number, column in enumerate(value_columns):
            base = _signal_base(source.name, column)
            lag = _safe_take(values[:, column_number], lag_indices)
            lag_values[lag_min][column] = lag
            feature_data[f"{base}__lag_{lag_min}m"] = lag

    for window_min in WINDOW_MINUTES:
        rolling = _rolling_block(times_ns, values, sample_ns, window_min, source.cadence_min)
        for column_number, column in enumerate(value_columns):
            base = _signal_base(source.name, column)
            for statistic in ROLLING_STATS:
                feature_data[f"{base}__roll_{statistic}_{window_min}m"] = rolling[statistic][
                    :, column_number
                ]
            feature_data[f"{base}__trend_{window_min}m"] = (
                current_values[column] - lag_values[window_min][column]
            )

    valid_current = current_indices >= 0
    source_age = np.full(len(sample_ns), np.nan)
    if valid_current.any():
        source_age[valid_current] = _as_minutes(
            sample_ns[valid_current] - times_ns[current_indices[valid_current]]
        )

    if include_flatline_features:
        for column_number, column in enumerate(value_columns):
            series_values = values[:, column_number]
            changed = np.ones(len(series_values), dtype=bool)
            if len(series_values) > 1:
                changed[1:] = ~np.isclose(series_values[1:], series_values[:-1], equal_nan=True)
            run_start_indices = np.maximum.accumulate(np.where(changed, np.arange(len(changed)), 0))
            flatline_age = np.full(len(sample_ns), np.nan)
            if valid_current.any():
                latest_indices = current_indices[valid_current]
                run_start_ns = times_ns[run_start_indices[latest_indices]]
                flatline_age[valid_current] = _as_minutes(sample_ns[valid_current] - run_start_ns)
            base = _signal_base(source.name, column)
            feature_data[f"{base}__age_min"] = source_age.copy()
            feature_data[f"{base}__flatline_age_min"] = flatline_age
            feature_data[f"{base}__flatline_ge_30m"] = (
                flatline_age >= PAK_FLATLINE_SUSPECT_MIN
            ).astype(float)
            feature_data[f"{base}__flatline_ge_60m"] = (
                flatline_age >= PAK_FLATLINE_INVALID_MIN
            ).astype(float)
            feature_data[f"{base}__flatline_ge_24h"] = (flatline_age >= 1_440).astype(float)

            previous_indices = current_indices - 1
            previous_values = _safe_take(series_values, previous_indices)
            delta_10m = current_values[column] - previous_values
            feature_data[f"{base}__delta_10m"] = delta_10m
            feature_data[f"{base}__abs_delta_10m"] = np.abs(delta_10m)
            if jump_abs_threshold is not None:
                feature_data[f"{base}__jump_ge_train_q999"] = (
                    np.abs(delta_10m) >= jump_abs_threshold
                ).astype(float)

            if mask_invalid_flatline:
                invalid = flatline_age >= PAK_FLATLINE_INVALID_MIN
                health_suffixes = {
                    "age_min",
                    "flatline_age_min",
                    "flatline_ge_30m",
                    "flatline_ge_60m",
                    "flatline_ge_24h",
                    "delta_10m",
                    "abs_delta_10m",
                    "jump_ge_train_q999",
                }
                for feature_name, feature_values in feature_data.items():
                    if not feature_name.startswith(f"{base}__"):
                        continue
                    if feature_name.rsplit("__", 1)[-1] in health_suffixes:
                        continue
                    feature_values[invalid] = np.nan

    return pd.DataFrame(feature_data), source_age


@dataclass
class InMemoryHistoryProvider:
    retention_hours: float = 7.0
    cadence_min: float = 10.0
    _rows: dict[str, list[dict[str, object]]] = field(default_factory=dict)

    def clear(self) -> None:
        self._rows.clear()

    def append(
        self,
        source: str,
        timestamp: pd.Timestamp | str,
        values: Mapping[str, float | int | None],
    ) -> None:
        parsed_timestamp = pd.Timestamp(timestamp)
        if parsed_timestamp.tzinfo is not None:
            parsed_timestamp = parsed_timestamp.tz_convert("UTC").tz_localize(None)
        row: dict[str, object] = {"date": parsed_timestamp}
        for signal, value in values.items():
            row[str(signal)] = np.nan if value is None else float(value)
        rows = self._rows.setdefault(source, [])
        rows.append(row)
        rows.sort(key=lambda item: pd.Timestamp(item["date"]))
        cutoff = parsed_timestamp - pd.Timedelta(hours=self.retention_hours)
        self._rows[source] = [item for item in rows if item["date"] >= cutoff]

    def frame(self, source: str, until: pd.Timestamp | str) -> pd.DataFrame:
        parsed_until = pd.Timestamp(until)
        if parsed_until.tzinfo is not None:
            parsed_until = parsed_until.tz_convert("UTC").tz_localize(None)
        rows = [item for item in self._rows.get(source, []) if item["date"] <= parsed_until]
        if not rows:
            return pd.DataFrame(columns=["date"])
        frame = pd.DataFrame(rows).sort_values("date", kind="stable")
        return frame.groupby("date", as_index=False).last()


class OnlineFeaturePipeline:
    def __init__(self, schema: FeatureSchema, history: InMemoryHistoryProvider):
        self.schema = schema
        self.history = history

    def build(self, timestamp: pd.Timestamp | str) -> FeatureVector:
        parsed_timestamp = pd.Timestamp(timestamp)
        if parsed_timestamp.tzinfo is not None:
            parsed_timestamp = parsed_timestamp.tz_convert("UTC").tz_localize(None)
        required = self.schema.required_signals
        feature_parts: list[pd.DataFrame] = []
        missing_sources: list[str] = []
        history_hours: dict[str, float] = {}

        for source_name, signals in required.items():
            frame = self.history.frame(source_name, parsed_timestamp)
            available_signals = [signal for signal in sorted(signals) if signal in frame.columns]
            if frame.empty or not available_signals:
                missing_sources.append(source_name)
                history_hours[source_name] = 0.0
                continue
            source_frame = frame[["date", *available_signals]].copy()
            duration = source_frame["date"].max() - source_frame["date"].min()
            history_hours[source_name] = max(0.0, duration.total_seconds() / 3_600.0)
            source_data = SourceData(source_name, source_frame, self.history.cadence_min)
            part, _ = build_source_features(
                source_data,
                pd.Series([parsed_timestamp]),
                include_flatline_features=source_name.startswith("pak_"),
                mask_invalid_flatline=source_name == "pak_mg_sulfur",
                jump_abs_threshold=(
                    self.schema.pak_sulfur_jump_abs_threshold
                    if source_name == "pak_mg_sulfur"
                    else None
                ),
            )
            feature_parts.append(part)

        combined = pd.concat(feature_parts, axis=1) if feature_parts else pd.DataFrame(index=[0])
        row = combined.reindex(columns=self.schema.baseline_feature_columns).iloc[0]
        available_mask = row.notna()
        missing_features = tuple(row.index[~available_mask].tolist())
        diagnostics = FeatureDiagnostics(
            total_features=len(row),
            available_features=int(available_mask.sum()),
            coverage_ratio=float(available_mask.mean()) if len(row) else 0.0,
            missing_features=missing_features,
            missing_sources=tuple(sorted(set(missing_sources))),
            source_history_hours=history_hours,
        )
        values = {
            column: float(value) if pd.notna(value) else math.nan for column, value in row.items()
        }
        return FeatureVector(parsed_timestamp, values, diagnostics)
