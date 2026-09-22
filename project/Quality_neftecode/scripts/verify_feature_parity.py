from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from quality_agent.data_prep import load_pak, load_telemetry_csv
from quality_agent.feature_pipeline import (
    FeatureSchema,
    InMemoryHistoryProvider,
    OnlineFeaturePipeline,
    SourceData,
    build_source_features,
)


def verify(workspace_root: Path, schema_path: Path, timestamp: pd.Timestamp) -> dict:
    schema = FeatureSchema.load(schema_path)
    sources = [
        load_telemetry_csv(workspace_root / "data" / "data" / "avt_tags.csv", "avt"),
        load_telemetry_csv(workspace_root / "data" / "data" / "242000_tags.csv", "hyd"),
        *load_pak(workspace_root / "Выгрузка ПАК 01.01.2023 - н.в_.xlsx"),
    ]
    required = schema.required_signals
    history = InMemoryHistoryProvider(retention_hours=7.0, cadence_min=10.0)
    offline_parts: list[pd.DataFrame] = []

    for source in sources:
        if source.name not in required:
            continue
        signals = sorted(required[source.name])
        full_frame = source.frame[["date", *signals]].copy()
        offline_source = SourceData(source.name, full_frame, source.cadence_min)
        offline_part, _ = build_source_features(
            offline_source,
            pd.Series([timestamp]),
            include_flatline_features=source.name.startswith("pak_"),
            mask_invalid_flatline=source.name == "pak_mg_sulfur",
            jump_abs_threshold=(
                schema.pak_sulfur_jump_abs_threshold if source.name == "pak_mg_sulfur" else None
            ),
        )
        offline_parts.append(offline_part)

        start = timestamp - pd.Timedelta(hours=7)
        window = full_frame[full_frame["date"].between(start, timestamp)]
        for row in window.itertuples(index=False):
            values = {
                signal: getattr(row, signal) for signal in signals if pd.notna(getattr(row, signal))
            }
            history.append(source.name, row.date, values)

    offline = pd.concat(offline_parts, axis=1).reindex(columns=schema.baseline_feature_columns)
    online = (
        OnlineFeaturePipeline(schema, history)
        .build(timestamp)
        .as_frame(schema.baseline_feature_columns)
    )
    offline_values = offline.to_numpy(dtype=float)
    online_values = online.to_numpy(dtype=float)
    equal = np.isclose(offline_values, online_values, rtol=1e-10, atol=1e-10, equal_nan=True)
    differences = np.abs(offline_values - online_values)
    finite_differences = differences[np.isfinite(differences)]
    mismatched_columns = [
        column
        for column, matches in zip(schema.baseline_feature_columns, equal[0], strict=True)
        if not matches
    ]
    return {
        "timestamp": timestamp.isoformat(),
        "features": len(schema.baseline_feature_columns),
        "equal_features": int(equal.sum()),
        "mismatched_features": int((~equal).sum()),
        "mismatched_columns": mismatched_columns,
        "maximum_absolute_difference": (
            float(finite_differences.max()) if len(finite_differences) else 0.0
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--timestamp", type=pd.Timestamp, required=True)
    arguments = parser.parse_args()
    result = verify(
        arguments.workspace_root.resolve(),
        arguments.schema.resolve(),
        arguments.timestamp,
    )
    print(result)
    if result["mismatched_features"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
