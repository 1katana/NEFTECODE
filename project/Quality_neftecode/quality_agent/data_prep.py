from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .feature_pipeline import (
    LAG_MINUTES,
    ROLLING_STATS,
    WINDOW_MINUTES,
    SourceData,
    build_source_features,
)

SULFUR_LIMIT = 10.0
MAX_TELEMETRY_AGE_MIN = 10.0
TRAIN_END = pd.Timestamp("2026-01-01")
VALIDATION_END = pd.Timestamp("2026-05-01")
LIMS_TIMESTAMP_COLUMN = 94  # CQ in the source workbook
LIMS_VALUE_COLUMN = 95  # CR in the source workbook


def load_lims_sulfur(path: Path) -> pd.DataFrame:
    """Read the final hydrotreater product Mg.Sulfur pair from CQ:CR.

    The workbook is a set of timestamp/value pairs. Rows 1-4 contain metadata;
    data begin at row 5. The fixed pair is validated against the indicator name
    so a changed workbook layout fails loudly instead of training on a wrong target.
    """
    raw = pd.read_excel(
        path,
        sheet_name=0,
        header=None,
        usecols=[LIMS_TIMESTAMP_COLUMN, LIMS_VALUE_COLUMN],
    )
    indicator = str(raw.iat[1, 0]).strip()
    if indicator != "Mg.Sulfur":
        raise ValueError(
            f"Expected Mg.Sulfur in CQ, found {indicator!r}. "
            "The LIMS workbook layout may have changed."
        )

    result = pd.DataFrame(
        {
            "sample_timestamp": pd.to_datetime(raw.iloc[4:, 0], errors="coerce"),
            "target_mg_sulfur": pd.to_numeric(raw.iloc[4:, 1], errors="coerce"),
        }
    ).dropna(subset=["sample_timestamp", "target_mg_sulfur"])
    result = result.sort_values("sample_timestamp", kind="stable").reset_index(drop=True)
    if result["sample_timestamp"].duplicated().any():
        duplicates = (
            result.loc[result["sample_timestamp"].duplicated(False), "sample_timestamp"]
            .astype(str)
            .tolist()
        )
        raise ValueError(f"Duplicate LIMS timestamps: {duplicates[:5]}")
    return result


def _normalize_series(
    frame: pd.DataFrame, timestamp_column: str, value_columns: Iterable[str]
) -> pd.DataFrame:
    result = frame[[timestamp_column, *value_columns]].copy()
    result[timestamp_column] = pd.to_datetime(result[timestamp_column], errors="coerce")
    for column in value_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=[timestamp_column]).sort_values(timestamp_column, kind="stable")
    result = result.drop_duplicates(timestamp_column, keep="last").reset_index(drop=True)
    return result


def _cadence_minutes(timestamps: pd.Series) -> float:
    differences = timestamps.sort_values().diff().dropna().dt.total_seconds() / 60.0
    positive = differences[differences > 0]
    if positive.empty:
        return math.nan
    return float(positive.median())


def load_telemetry_csv(path: Path, source_name: str) -> SourceData:
    frame = pd.read_csv(path, low_memory=False)
    if "date" not in frame.columns:
        raise ValueError(f"Missing date column in {path}")
    value_columns = [
        column for column in frame.columns if not column.startswith("Unnamed") and column != "date"
    ]
    normalized = _normalize_series(frame, "date", value_columns)
    return SourceData(source_name, normalized, _cadence_minutes(normalized["date"]))


def load_pak(path: Path) -> list[SourceData]:
    raw = pd.read_excel(path, sheet_name=0, header=None, usecols=[0, 1, 3, 4])
    sulfur = pd.DataFrame({"date": raw.iloc[2:, 0], "value": raw.iloc[2:, 1]})
    density = pd.DataFrame({"date": raw.iloc[2:, 2], "value": raw.iloc[2:, 3]})
    result: list[SourceData] = []
    for source_name, frame in (("pak_mg_sulfur", sulfur), ("pak_d15", density)):
        normalized = _normalize_series(frame, "date", ["value"])
        normalized = normalized.dropna(subset=["value"]).reset_index(drop=True)
        result.append(SourceData(source_name, normalized, _cadence_minutes(normalized["date"])))
    return result


def _train_jump_abs_threshold(source: SourceData, quantile: float = 0.999) -> float:
    train_values = source.frame.loc[source.frame["date"] < TRAIN_END, "value"]
    absolute_delta = train_values.diff().abs()
    nonzero = absolute_delta.loc[absolute_delta > 0]
    if nonzero.empty:
        raise ValueError(f"Cannot estimate jump threshold for {source.name}")
    return float(nonzero.quantile(quantile))


def _flatline_statistics(values: np.ndarray, cadence_min: float) -> tuple[int, float, float]:
    if not len(values):
        return 0, 0.0, 0.0
    changed = np.ones(len(values), dtype=bool)
    if len(values) > 1:
        changed[1:] = ~np.isclose(values[1:], values[:-1], equal_nan=True)
    starts = np.flatnonzero(changed)
    lengths = np.diff(np.r_[starts, len(values)])
    max_points = int(lengths.max(initial=0))
    threshold_points = max(1, round(1_440 / cadence_min)) if cadence_min > 0 else len(values) + 1
    points_in_long_runs = int(lengths[lengths >= threshold_points].sum())
    share = points_in_long_runs / len(values)
    return max_points, max_points * cadence_min / 60.0, share


def build_data_quality_report(sources: Iterable[SourceData]) -> pd.DataFrame:
    rows: list[dict] = []
    for source in sources:
        value_columns = [column for column in source.frame.columns if column != "date"]
        for column in value_columns:
            series = source.frame[column]
            numeric = series.to_numpy(dtype=float, copy=False)
            finite = numeric[np.isfinite(numeric)]
            max_points, max_hours, long_flat_share = _flatline_statistics(
                numeric, source.cadence_min
            )
            unique_count = int(pd.Series(finite).nunique())
            rows.append(
                {
                    "source": source.name,
                    "signal": column,
                    "row_count": len(series),
                    "start_timestamp": source.frame["date"].min(),
                    "end_timestamp": source.frame["date"].max(),
                    "cadence_min": source.cadence_min,
                    "missing_count": int(series.isna().sum()),
                    "missing_rate": float(series.isna().mean()),
                    "unique_count": unique_count,
                    "min": float(np.min(finite)) if len(finite) else np.nan,
                    "max": float(np.max(finite)) if len(finite) else np.nan,
                    "max_exact_flatline_points": max_points,
                    "max_exact_flatline_hours": max_hours,
                    "share_points_in_flatlines_ge_24h": long_flat_share,
                    "requires_review": bool(unique_count <= 1 or long_flat_share >= 0.05),
                }
            )
    return pd.DataFrame(rows)


def _feature_family(column: str) -> str:
    return column.rsplit("__", 1)[-1]


def _baseline_feature_columns(
    dataset: pd.DataFrame,
    train_mask: pd.Series,
    excluded_signal_bases: set[str],
) -> list[str]:
    allowed_suffixes = {
        "current",
        "roll_mean_60m",
        "roll_std_60m",
        "roll_mean_240m",
        "roll_std_240m",
        "trend_60m",
        "trend_240m",
        "age_min",
        "flatline_age_min",
        "flatline_ge_30m",
        "flatline_ge_60m",
        "flatline_ge_24h",
        "delta_10m",
        "abs_delta_10m",
        "jump_ge_train_q999",
    }
    candidates = [
        column
        for column in dataset.columns
        if "__" in column
        and _feature_family(column) in allowed_suffixes
        and column.split("__", 1)[0] not in excluded_signal_bases
    ]
    train = dataset.loc[train_mask, candidates]
    selected: list[str] = []
    for column in candidates:
        values = train[column]
        # A feature that appears only late in history acts as a time marker and
        # creates a different train/validation distribution. Keep it in the
        # complete dataset, but not in the conservative first baseline.
        if values.notna().mean() < 0.50:
            continue
        if values.nunique(dropna=True) <= 1:
            continue
        selected.append(column)
    return selected


def _calendar_split(timestamp: pd.Timestamp) -> str:
    if timestamp < TRAIN_END:
        return "train"
    if timestamp < VALIDATION_END:
        return "validation"
    return "test"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_training_data(
    workspace_root: Path,
    output_dir: Path,
    feature_anchor_offset_min: int = 0,
) -> dict:
    workspace_root = workspace_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if feature_anchor_offset_min < 0:
        raise ValueError("feature_anchor_offset_min must be non-negative")

    lims_path = workspace_root / "ЛИМСы 01.01.2023 - н.в_ (2).xlsx"
    pak_path = workspace_root / "Выгрузка ПАК 01.01.2023 - н.в_.xlsx"
    avt_path = workspace_root / "data" / "data" / "avt_tags.csv"
    hydro_path = workspace_root / "data" / "data" / "242000_tags.csv"
    for required in (lims_path, pak_path, avt_path, hydro_path):
        if not required.exists():
            raise FileNotFoundError(required)

    lims = load_lims_sulfur(lims_path)
    sources = [
        load_telemetry_csv(avt_path, "avt"),
        load_telemetry_csv(hydro_path, "hyd"),
        *load_pak(pak_path),
    ]
    pak_sulfur_source = next(source for source in sources if source.name == "pak_mg_sulfur")
    pak_sulfur_jump_threshold = _train_jump_abs_threshold(pak_sulfur_source)

    feature_timestamps = lims["sample_timestamp"] - pd.to_timedelta(
        feature_anchor_offset_min, unit="min"
    )
    feature_frames: list[pd.DataFrame] = []
    source_ages: dict[str, np.ndarray] = {}
    for source in sources:
        features, source_age = build_source_features(
            source,
            feature_timestamps,
            include_flatline_features=source.name.startswith("pak_"),
            mask_invalid_flatline=source.name == "pak_mg_sulfur",
            jump_abs_threshold=(
                pak_sulfur_jump_threshold if source.name == "pak_mg_sulfur" else None
            ),
        )
        feature_frames.append(features)
        source_ages[source.name] = source_age

    metadata = lims.copy()
    metadata.insert(
        0,
        "sample_id",
        metadata["sample_timestamp"].dt.strftime("lims_hydro2_sulfur_%Y%m%dT%H%M%S"),
    )
    metadata["feature_anchor_timestamp"] = feature_timestamps
    metadata["target_violation_gt_10"] = (metadata["target_mg_sulfur"] > SULFUR_LIMIT).astype(int)
    metadata["target_requires_review"] = (metadata["target_mg_sulfur"] > 100.0).astype(int)
    metadata["calendar_split"] = metadata["sample_timestamp"].map(_calendar_split)
    metadata["avt_state_age_min"] = source_ages["avt"]
    metadata["hyd_state_age_min"] = source_ages["hyd"]
    fresh_avt = metadata["avt_state_age_min"].between(0, MAX_TELEMETRY_AGE_MIN)
    fresh_hyd = metadata["hyd_state_age_min"].between(0, MAX_TELEMETRY_AGE_MIN)
    metadata["eligible_for_training"] = (fresh_avt & fresh_hyd).astype(int)
    metadata["exclusion_reason"] = np.where(
        metadata["eligible_for_training"].eq(1), "", "telemetry_missing_or_older_than_10m"
    )

    dataset = pd.concat([metadata, *feature_frames], axis=1)
    target_and_metadata_columns = list(metadata.columns)
    all_feature_columns = [
        column for column in dataset.columns if column not in target_and_metadata_columns
    ]
    if any(column.startswith("target_") for column in all_feature_columns):
        raise AssertionError("Target leakage: a target column entered the feature set")
    if dataset["sample_timestamp"].duplicated().any():
        raise AssertionError("One LIMS sample must map to exactly one row")
    if (dataset[["avt_state_age_min", "hyd_state_age_min"]].dropna() < 0).any().any():
        raise AssertionError("Future telemetry was joined to a LIMS sample")

    quality_report = build_data_quality_report(sources)
    excluded_signal_bases = {
        f"{row.source}_{row.signal}"
        for row in quality_report.itertuples(index=False)
        if row.source in {"avt", "hyd"} and row.requires_review
    }

    eligible = dataset["eligible_for_training"].eq(1)
    train_mask = eligible & dataset["calendar_split"].eq("train")
    baseline_features = _baseline_feature_columns(dataset, train_mask, excluded_signal_bases)

    main_path = output_dir / "quality_training_lims_samples.csv"
    dataset.to_csv(main_path, index=False, float_format="%.8g", date_format="%Y-%m-%d %H:%M:%S")
    split_paths: dict[str, Path] = {}
    split_file_names = {
        "train": "split_train.csv",
        "validation": "split_val.csv",
        "test": "split_test.csv",
    }
    for split_name, file_name in split_file_names.items():
        split = dataset.loc[eligible & dataset["calendar_split"].eq(split_name)].copy()
        split_path = output_dir / file_name
        split.to_csv(split_path, index=False, float_format="%.8g", date_format="%Y-%m-%d %H:%M:%S")
        split_paths[split_name] = split_path

    quality_report_path = output_dir / "data_quality_report.csv"
    quality_report.to_csv(
        quality_report_path, index=False, float_format="%.8g", date_format="%Y-%m-%d %H:%M:%S"
    )

    split_stats = {}
    for split_name in split_file_names:
        split_mask = eligible & dataset["calendar_split"].eq(split_name)
        split_stats[split_name] = {
            "rows": int(split_mask.sum()),
            "violations_gt_10": int(dataset.loc[split_mask, "target_violation_gt_10"].sum()),
            "violation_rate": float(dataset.loc[split_mask, "target_violation_gt_10"].mean()),
        }

    schema = {
        "schema_version": "quality-lims-samples-v2",
        "grain": "one row per real LIMS Mg.Sulfur sample",
        "timestamp_semantics": "assumed sample collection time; not domain-confirmed",
        "target": {
            "regression": "target_mg_sulfur",
            "classification": "target_violation_gt_10",
            "limit_mg_kg": SULFUR_LIMIT,
        },
        "metadata_columns": target_and_metadata_columns,
        "all_feature_columns": all_feature_columns,
        "baseline_feature_columns": baseline_features,
        "forbidden_model_inputs": [
            "target_mg_sulfur",
            "target_violation_gt_10",
            "target_requires_review",
            "sample_id",
            "sample_timestamp",
            "feature_anchor_timestamp",
            "calendar_split",
            "eligible_for_training",
            "exclusion_reason",
        ],
        "feature_rules": {
            "join": "as-of, latest timestamp <= feature anchor timestamp",
            "feature_anchor_offset_min": feature_anchor_offset_min,
            "lags_min": list(LAG_MINUTES),
            "windows_min": list(WINDOW_MINUTES),
            "rolling_statistics": list(ROLLING_STATS),
            "trend": "current minus as-of value at t-window",
            "lims_history_used_as_feature": False,
            "pak_used_as_target": False,
            "baseline_excluded_telemetry_signals": sorted(excluded_signal_bases),
            "baseline_minimum_train_non_null_rate": 0.50,
            "signal_quality": {
                "pak_mg_sulfur": {
                    "suspect_flatline_min": 30,
                    "invalid_flatline_min": 60,
                    "jump_abs_delta_10m_train_q999_mg_kg": pak_sulfur_jump_threshold,
                    "jump_threshold_fit_scope": "raw PAK rows with timestamp < train end",
                }
            },
        },
        "split_rules": {
            "train": f"timestamp < {TRAIN_END}",
            "validation": f"{TRAIN_END} <= timestamp < {VALIDATION_END}",
            "test": f"timestamp >= {VALIDATION_END}",
            "eligibility": f"AVT and 24-2000 age in [0, {MAX_TELEMETRY_AGE_MIN}] minutes",
        },
    }
    _write_json(output_dir / "feature_schema.json", schema)

    extreme_rows = dataset.loc[
        dataset["target_requires_review"].eq(1),
        ["sample_timestamp", "target_mg_sulfur"],
    ]
    manifest = {
        "dataset_version": "quality-lims-samples-v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "lims": str(lims_path),
            "pak": str(pak_path),
            "avt_telemetry": str(avt_path),
            "hydrotreater_telemetry": str(hydro_path),
        },
        "outputs": {
            "dataset": str(main_path),
            "splits": {name: str(path) for name, path in split_paths.items()},
            "data_quality_report": str(quality_report_path),
            "feature_schema": str(output_dir / "feature_schema.json"),
        },
        "rows": {
            "all_lims_samples": len(dataset),
            "eligible_for_training": int(eligible.sum()),
            "excluded_stale_or_missing_telemetry": int((~eligible).sum()),
        },
        "columns": {
            "total": int(dataset.shape[1]),
            "all_features": len(all_feature_columns),
            "baseline_features": len(baseline_features),
        },
        "target": {
            "minimum": float(dataset["target_mg_sulfur"].min()),
            "median": float(dataset["target_mg_sulfur"].median()),
            "maximum": float(dataset["target_mg_sulfur"].max()),
            "violations_gt_10": int(dataset["target_violation_gt_10"].sum()),
            "violation_rate": float(dataset["target_violation_gt_10"].mean()),
            "extreme_values_gt_100_kept_for_review": [
                {
                    "sample_timestamp": row.sample_timestamp.isoformat(),
                    "target_mg_sulfur": float(row.target_mg_sulfur),
                }
                for row in extreme_rows.itertuples(index=False)
            ],
        },
        "feature_anchor": {
            "offset_before_lims_timestamp_min": feature_anchor_offset_min,
            "policy": "sensitivity offsets are separate datasets; no future data",
        },
        "splits": split_stats,
        "readiness": {
            "dataset_preparation": "ready",
            "baseline_training": "ready_with_caveats",
            "production_calibration": "not_ready",
            "enough_for_initial_baseline": True,
            "enough_for_stable_production_probability_calibration": False,
            "caveats": [
                "LIMS timestamp is provisionally treated as sample collection time; confirm it before production use.",
                "Validation contains few S > 10 events; isotonic calibration will be unstable.",
                "Three target values above 100 mg/kg require domain review and were not deleted.",
                "PAK D15 begins only in March 2025, so earlier rows contain missing D15 features.",
                "Several source tags contain long exact flatlines; see data_quality_report.csv.",
            ],
        },
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build one-row-per-LIMS-sample QualityAgent training data."
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--feature-anchor-offset-min", type=int, default=0)
    arguments = parser.parse_args()
    manifest = prepare_training_data(
        arguments.workspace_root,
        arguments.output_dir,
        feature_anchor_offset_min=arguments.feature_anchor_offset_min,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
