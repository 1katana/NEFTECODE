from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quality_agent.data_prep import (
    load_lims_sulfur,
    load_pak,
    load_telemetry_csv,
)


def _run_annotations(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame[["date", "value"]].copy().reset_index(drop=True)
    values = result["value"].to_numpy(dtype=float)
    changed = np.ones(len(result), dtype=bool)
    if len(result) > 1:
        changed[1:] = values[1:] != values[:-1]
    run_id = np.cumsum(changed)
    result["run_id"] = run_id
    groups = result.groupby("run_id", sort=False)
    result["run_start"] = groups["date"].transform("min")
    result["run_end"] = groups["date"].transform("max")
    result["run_points"] = groups["date"].transform("size")
    result["flatline_age_min"] = (
        result["date"] - result["run_start"]
    ).dt.total_seconds() / 60.0
    result["run_duration_min"] = (result["run_points"] - 1) * 10.0
    return result


def _asof(left: pd.DataFrame, right: pd.DataFrame, left_on: str) -> pd.DataFrame:
    return pd.merge_asof(
        left.sort_values(left_on),
        right.sort_values("date"),
        left_on=left_on,
        right_on="date",
        direction="backward",
        tolerance=pd.Timedelta(minutes=10),
    )


def _finite(value: object) -> object:
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {key: _finite(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _mae(frame: pd.DataFrame, prediction: str = "value") -> float | None:
    clean = frame.dropna(subset=["target_mg_sulfur", prediction])
    if clean.empty:
        return None
    return float((clean["target_mg_sulfur"] - clean[prediction]).abs().mean())


def _correlation(frame: pd.DataFrame, prediction: str = "value") -> float | None:
    clean = frame.dropna(subset=["target_mg_sulfur", prediction])
    if len(clean) < 3:
        return None
    value = clean["target_mg_sulfur"].corr(clean[prediction])
    return float(value) if pd.notna(value) else None


def _flatline_runs(annotated: pd.DataFrame, minimum_minutes: float) -> pd.DataFrame:
    runs = (
        annotated.groupby("run_id", sort=False)
        .agg(
            start=("run_start", "first"),
            end=("run_end", "first"),
            value=("value", "first"),
            points=("run_points", "first"),
            duration_min=("run_duration_min", "first"),
        )
        .reset_index(drop=True)
    )
    return runs.loc[runs["duration_min"] >= minimum_minutes].sort_values(
        "duration_min", ascending=False
    )


def _lag_sweep(lims: pd.DataFrame, pak: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    base = lims.loc[lims["target_mg_sulfur"] <= 100].copy()
    for lag_min in range(0, 361, 10):
        query = base.assign(query_time=base["sample_timestamp"] - pd.Timedelta(minutes=lag_min))
        joined = _asof(query, pak, "query_time")
        healthy = joined.loc[joined["flatline_age_min"] < 60]
        standard = healthy.loc[healthy["sample_timestamp"].dt.hour.eq(10)]
        rows.append(
            {
                "lag_min": lag_min,
                "all_n": len(healthy),
                "all_mae": _mae(healthy),
                "all_corr": _correlation(healthy),
                "at_10_n": len(standard),
                "at_10_mae": _mae(standard),
                "at_10_corr": _correlation(standard),
            }
        )
    return pd.DataFrame(rows)


def _yearly_best_lags(lims: pd.DataFrame, pak: pd.DataFrame) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for year, group in lims.groupby(lims["sample_timestamp"].dt.year):
        sweep = _lag_sweep(group, pak)
        if sweep["all_mae"].notna().any():
            best = sweep.loc[sweep["all_mae"].idxmin()]
            result.append(
                {
                    "year": int(year),
                    "best_lag_min": int(best["lag_min"]),
                    "n": int(best["all_n"]),
                    "mae": float(best["all_mae"]),
                    "correlation": _finite(best["all_corr"]),
                }
            )
    return result


def _jump_analysis(annotated: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame]:
    values = annotated["value"]
    absolute_delta = values.diff().abs()
    nonzero = absolute_delta.loc[absolute_delta > 0]
    quantiles = {
        str(q): float(nonzero.quantile(q))
        for q in (0.50, 0.90, 0.95, 0.99, 0.999, 1.0)
    }
    threshold = float(nonzero.quantile(0.999))
    previous = values.shift(1)
    following = values.shift(-1)
    isolated = (
        (values.sub(previous).abs() >= threshold)
        & (values.sub(following).abs() >= threshold)
        & (previous.sub(following).abs() <= float(nonzero.quantile(0.95)))
    )
    events = annotated.loc[absolute_delta >= threshold, ["date", "value"]].copy()
    events["previous_value"] = previous.loc[events.index]
    events["next_value"] = following.loc[events.index]
    events["absolute_delta"] = absolute_delta.loc[events.index]
    events["isolated_reversal"] = isolated.loc[events.index]
    events = events.sort_values("absolute_delta", ascending=False)
    return (
        {
            "nonzero_delta_count": len(nonzero),
            "absolute_delta_quantiles_mg_kg": quantiles,
            "candidate_threshold_q999_mg_kg": threshold,
            "candidate_events": len(events),
            "isolated_reversals": int(events["isolated_reversal"].sum()),
        },
        events,
    )


def _telemetry_context(
    timestamp: pd.Timestamp,
    source: pd.DataFrame,
    tags: list[str],
) -> dict[str, object]:
    query = pd.DataFrame({"query_time": [timestamp]})
    joined = _asof(query, source[["date", *tags]], "query_time").iloc[0]
    context: dict[str, object] = {"telemetry_timestamp": _finite(joined["date"])}
    for tag in tags:
        value = joined[tag]
        numeric = source[tag].dropna()
        percentile = float((numeric <= value).mean()) if pd.notna(value) and len(numeric) else None
        context[tag] = {"value": _finite(value), "empirical_percentile": percentile}
    return context


def _extreme_context(
    lims: pd.DataFrame,
    pak: pd.DataFrame,
    avt: pd.DataFrame,
    hyd: pd.DataFrame,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    avt_tags = [tag for tag in ("F7", "F8", "F9", "F30", "F32", "W70") if tag in avt]
    hyd_tags = [
        tag
        for tag in ("T11", "F26", "F17", "T23", "T6", "W7", "P13", "P24", "F15")
        if tag in hyd
    ]
    for row in lims.loc[lims["target_mg_sulfur"] > 100].itertuples(index=False):
        timestamp = row.sample_timestamp
        pak_now = _asof(
            pd.DataFrame({"query_time": [timestamp]}), pak, "query_time"
        ).iloc[0]
        nearby = lims.loc[
            lims["sample_timestamp"].between(
                timestamp - pd.Timedelta(hours=24), timestamp + pd.Timedelta(hours=24)
            ),
            ["sample_timestamp", "target_mg_sulfur"],
        ]
        result.append(
            {
                "sample_timestamp": timestamp.isoformat(),
                "target_mg_sulfur": float(row.target_mg_sulfur),
                "pak": {
                    "timestamp": _finite(pak_now["date"]),
                    "value": _finite(pak_now["value"]),
                    "flatline_age_min": _finite(pak_now["flatline_age_min"]),
                    "run_duration_min": _finite(pak_now["run_duration_min"]),
                },
                "nearby_lims_24h": _records(nearby),
                "avt": _telemetry_context(timestamp, avt, avt_tags),
                "hyd": _telemetry_context(timestamp, hyd, hyd_tags),
            }
        )
    return result


def _flatline_error_segments(lims: pd.DataFrame, pak: pd.DataFrame) -> list[dict[str, object]]:
    joined = _asof(
        lims.loc[lims["target_mg_sulfur"] <= 100].assign(
            query_time=lims.loc[lims["target_mg_sulfur"] <= 100, "sample_timestamp"]
        ),
        pak,
        "query_time",
    )
    rows: list[dict[str, object]] = []
    for threshold in (30, 60, 120, 360, 1_440):
        stale = joined["flatline_age_min"] >= threshold
        rows.append(
            {
                "threshold_min": threshold,
                "stale_lims_samples": int(stale.sum()),
                "healthy_lims_samples": int((~stale).sum()),
                "stale_mae": _mae(joined.loc[stale]),
                "healthy_mae": _mae(joined.loc[~stale]),
            }
        )
    return rows


def _long_run_telemetry_context(
    runs: pd.DataFrame,
    avt: pd.DataFrame,
    hyd: pd.DataFrame,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for run in runs.head(10).itertuples(index=False):
        item: dict[str, object] = {
            "start": run.start.isoformat(),
            "end": run.end.isoformat(),
            "value": float(run.value),
            "duration_hours": float(run.duration_min / 60.0),
        }
        for name, frame in (("avt", avt), ("hyd", hyd)):
            segment = frame.loc[frame["date"].between(run.start, run.end)]
            value_columns = [column for column in segment if column != "date"]
            if segment.empty:
                item[name] = None
                continue
            constant_share = float(
                np.mean([segment[column].nunique(dropna=True) <= 1 for column in value_columns])
            )
            zero_delta_shares = [
                float(segment[column].diff().eq(0).mean()) for column in value_columns
            ]
            code_counts = {
                str(code): int(segment[value_columns].eq(code).sum(axis=1).max())
                for code in (240, 251, 252, 307)
            }
            item[name] = {
                "rows": len(segment),
                "constant_channel_share": constant_share,
                "median_zero_delta_share": float(np.median(zero_delta_shares)),
                "max_simultaneous_code_count": code_counts,
            }
        result.append(item)
    return result


def analyze(workspace_root: Path) -> dict[str, object]:
    lims = load_lims_sulfur(workspace_root / "ЛИМСы 01.01.2023 - н.в_ (2).xlsx")
    pak_sources = load_pak(workspace_root / "Выгрузка ПАК 01.01.2023 - н.в_.xlsx")
    pak_sulfur = next(item.frame for item in pak_sources if item.name == "pak_mg_sulfur")
    pak = _run_annotations(pak_sulfur)
    avt = load_telemetry_csv(workspace_root / "data/data/avt_tags.csv", "avt").frame
    hyd = load_telemetry_csv(workspace_root / "data/data/242000_tags.csv", "hyd").frame

    long_runs = _flatline_runs(pak, minimum_minutes=60)
    jump_summary, jump_events = _jump_analysis(pak)
    sweep = _lag_sweep(lims, pak)
    best_all = sweep.loc[sweep["all_mae"].idxmin()]
    best_10 = sweep.loc[sweep["at_10_mae"].idxmin()]

    return {
        "generated_from": {
            "lims_rows": len(lims),
            "pak_rows": len(pak),
            "avt_rows": len(avt),
            "hyd_rows": len(hyd),
        },
        "target": {
            "above_100_count": int((lims["target_mg_sulfur"] > 100).sum()),
            "extreme_context": _extreme_context(lims, pak, avt, hyd),
        },
        "pak_flatlines": {
            "runs_ge_1h": len(long_runs),
            "runs_ge_6h": int((long_runs["duration_min"] >= 360).sum()),
            "runs_ge_24h": int((long_runs["duration_min"] >= 1_440).sum()),
            "top_runs": _records(long_runs.head(20)),
            "lims_error_by_threshold": _flatline_error_segments(lims, pak),
            "telemetry_context_top_runs": _long_run_telemetry_context(long_runs, avt, hyd),
        },
        "pak_jumps": {
            **jump_summary,
            "top_events": _records(jump_events.head(30)),
        },
        "timestamp_lag_sensitivity": {
            "scope": "LIMS target <=100; PAK flatline age <60 min; backward as-of within 10 min",
            "best_all_samples": _records(pd.DataFrame([best_all]))[0],
            "best_samples_at_10": _records(pd.DataFrame([best_10]))[0],
            "best_by_year": _yearly_best_lags(lims, pak),
            "top_10_by_mae": _records(sweep.nsmallest(10, "all_mae")),
        },
    }


def _markdown(report: dict[str, object]) -> str:
    target = report["target"]
    flat = report["pak_flatlines"]
    jumps = report["pak_jumps"]
    lag = report["timestamp_lag_sensitivity"]
    lines = [
        "# Диагностика ЛИМС / ПАК / телеметрии",
        "",
        "Отчёт сформирован воспроизводимым скриптом `scripts/analyze_signal_anomalies.py`.",
        "",
        "## Краткие результаты",
        "",
        f"- ЛИМС-значений выше 100 мг/кг: {target['above_100_count']}.",
        f"- Flatline ПАК ≥1 ч: {flat['runs_ge_1h']}; ≥6 ч: {flat['runs_ge_6h']}; ≥24 ч: {flat['runs_ge_24h']}.",
        f"- Порог сильного скачка по q99.9 ненулевых соседних изменений: {jumps['candidate_threshold_q999_mg_kg']:.6g} мг/кг.",
        f"- Событий выше этого порога: {jumps['candidate_events']}; изолированных возвратных выбросов: {jumps['isolated_reversals']}.",
        f"- Лучший простой лаг на всех пригодных пробах: {lag['best_all_samples']['lag_min']} мин, MAE={lag['best_all_samples']['all_mae']:.4f}.",
        f"- Лучший простой лаг для проб в 10:00: {lag['best_samples_at_10']['lag_min']} мин, MAE={lag['best_samples_at_10']['at_10_mae']:.4f}.",
        "",
        "## Интерпретация",
        "",
        "Числа в этом отчёте диагностические. Статистический лаг не доказывает физический лаг, а совпадение flatline с необычной телеметрией не доказывает останов без журнала событий.",
        "Полный контекст экстремальных ЛИМС-точек, длинных flatline и скачков сохранён в соседнем JSON.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = analyze(args.workspace_root.resolve())
    (args.output_dir / "signal_anomaly_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "signal_anomaly_report.md").write_text(
        _markdown(report), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
