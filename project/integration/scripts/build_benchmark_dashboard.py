"""Rebuild the offline benchmark dashboard from saved metrics and live API runs."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from neftecode_integration.app import DEFAULT_CONFIG, create_app
from neftecode_integration.settings import IntegrationSettings

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "integration" / "dashboard"
QUALITY_ARTIFACTS = ROOT / "Quality_neftecode" / "artifacts" / "experiments"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _quality_benchmarks() -> dict[str, Any]:
    primary = _read_json(QUALITY_ARTIFACTS / "H_full_pak_residual_oof_calibration/metrics.json")
    fallback = _read_json(QUALITY_ARTIFACTS / "C_telemetry_only/metrics.json")
    test = pd.read_csv(
        ROOT / "Quality_neftecode/data/processed/split_test.csv",
        usecols=["target_violation_gt_10"],
    )
    test_rows = len(test)
    violations = int(test["target_violation_gt_10"].sum())
    if test_rows != primary["rows"]["test"] or test_rows != fallback["rows"]["test"]:
        raise ValueError("Quality test split count disagrees with model reports")
    h_rows = primary["test"]["regression_evaluable_rows"]
    if h_rows is None or h_rows <= 0 or h_rows > test_rows:
        raise ValueError("Invalid primary regression sample count")
    return {
        "test_rows": test_rows,
        "test_violations": violations,
        "test_prevalence": violations / test_rows,
        "primary": {
            "name": "H · ПАК + residual",
            "mae": primary["test"]["regression"]["MAE"],
            "rmse": primary["test"]["regression"]["RMSE"],
            "regression_rows": h_rows,
            "interval_coverage_80": primary["test"]["interval"]["coverage_80"],
            "pr_auc": primary["test"]["classifier_selected"]["PR_AUC"],
            "brier_selected": primary["test"]["classifier_selected"]["Brier"],
            "brier_raw": primary["test"]["classifier_raw"]["Brier"],
            "prediction_policy": "PAK passthrough in current runtime; H supplies risk and interval",
        },
        "pak_baseline": {
            "name": "Текущий ПАК",
            "mae": primary["naive_baselines"]["pak_current_regression"]["MAE"],
            "rmse": primary["naive_baselines"]["pak_current_regression"]["RMSE"],
            "rows": h_rows,
        },
        "fallback": {
            "name": "C · только телеметрия",
            "mae": fallback["test"]["regression"]["MAE"],
            "rmse": fallback["test"]["regression"]["RMSE"],
            "rows": fallback["rows"]["test"],
            "interval_coverage_80": fallback["test"]["interval"]["coverage_80"],
            "pr_auc": fallback["test"]["classifier_calibrated"]["PR_AUC"],
        },
        "primary_training_id": primary["training_id"],
        "fallback_training_id": fallback["training_id"],
    }


def _reliability_benchmarks() -> dict[str, Any]:
    report = _read_json(ROOT / "reliability_agent/artifacts/training_report.json")
    assets = []
    for code, group in report["groups"].items():
        validation = group["validation"]
        test = group["test"]
        if not (0 <= validation["high_fraction"] <= 1 and 0 <= test["high_fraction"] <= 1):
            raise ValueError(f"Invalid HIGH fraction for {code}")
        if (
            test["scored_rows"]
            + test["unavailable_rows"]
            + test["low_load_rows_with_complete_data"]
            != test["rows"]
        ):
            raise ValueError(f"Inconsistent test row accounting for {code}")
        assets.append(
            {
                "code": code,
                "name": {
                    "avt_p3": "П-3",
                    "avt_k10": "К-10",
                    "avt_k2": "К-2",
                    "hyd_regime": "24-2000",
                }[code],
                "validation_high_rate": validation["high_fraction"],
                "test_high_rate": test["high_fraction"],
                "validation_scored_rows": validation["scored_rows"],
                "test_scored_rows": test["scored_rows"],
                "test_unavailable_rows": test["unavailable_rows"],
                "test_low_load_rows": test["low_load_rows_with_complete_data"],
            }
        )
    return {
        "assets": assets,
        "source_rows": report["source_rows"],
        "test_start": report["test_start"],
        "train_end_exclusive": report["train_end_exclusive"],
        "validation_end_exclusive": report["validation_end_exclusive"],
        "meaning": "Share of HIGH alerts among assessed snapshots; not failure accuracy",
    }


def _compact_run(run: dict[str, Any], *, name: str, kind: str) -> dict[str, Any]:
    assembled = run["assembled_input"]
    quality = assembled["current_quality"]["data"] or {}
    reliability = assembled["current_reliability"]["data"] or {}
    optimization = assembled["optimization"]["data"] or {}
    return {
        "name": name,
        "kind": kind,
        "source": optimization.get("input_source"),
        "decision": run["decision"]["decision"],
        "reason_codes": run["decision"]["reason_codes"],
        "quality_prediction": quality.get("quality_prediction"),
        "quality_warnings": quality.get("warnings", []),
        "reliability_risk": reliability.get("reliability_risk"),
        "reliability_score": reliability.get("risk_score"),
        "reliability_confidence": reliability.get("data_confidence"),
        "ranked_candidates": len(optimization.get("ranked_candidates", [])),
    }


def _pipeline_benchmarks() -> dict[str, Any]:
    historical_request = _read_json(ROOT / "integration/examples/historical_20260515_1000.json")
    evidence = _read_json(ROOT / "integration/examples/historical_20260515_1000_evidence.json")
    illustrative_request = _read_json(ROOT / "integration/examples/illustrative_blend_20260515_1200.json")
    illustrative_evidence = _read_json(
        ROOT / "integration/examples/illustrative_blend_20260515_1200_evidence.json"
    )
    if historical_request["input_source"] != "HISTORICAL":
        raise ValueError("Historical case source marker changed")
    if "blending" in historical_request["process_state"]["quality"]:
        raise ValueError("Historical case must not contain an assumed blending recipe")
    if illustrative_request["input_source"] != "SYNTHETIC" or not illustrative_evidence[
        "not_an_operational_recipe"
    ]:
        raise ValueError("Illustrative blend must remain explicitly synthetic")
    with TemporaryDirectory() as temporary:
        base = IntegrationSettings.from_yaml(DEFAULT_CONFIG)
        settings = replace(
            base,
            trace_path=Path(temporary) / "trace.jsonl",
            quality_shadow_log_path=Path(temporary) / "shadow.jsonl",
        )
        with TestClient(create_app(settings=settings)) as client:
            health = client.get("/api/v1/health")
            health.raise_for_status()
            listing = client.get("/api/v1/scenarios")
            listing.raise_for_status()
            runs = []
            for scenario in listing.json():
                scenario_id = scenario["scenario_id"]
                response = client.post(f"/api/v1/scenarios/{scenario_id}/evaluate")
                response.raise_for_status()
                runs.append(_compact_run(response.json(), name=scenario["title"], kind="synthetic"))
            response = client.post("/api/v1/evaluate", json=historical_request)
            response.raise_for_status()
            historical = _compact_run(
                response.json(), name="Исторический срез · 15 мая 10:00", kind="historical"
            )
            runs.append(historical)
            response = client.post("/api/v1/evaluate", json=illustrative_request)
            response.raise_for_status()
            illustrative = _compact_run(
                response.json(), name="Расчётная смесь · 15 мая 12:00", kind="illustrative"
            )
            runs.append(illustrative)
            blockers = health.json()["integration"]["production_blockers"]
    return {
        "runs": runs,
        "decision_counts": dict(Counter(run["decision"] for run in runs)),
        "production_blockers": blockers,
        "illustrative_assumption": illustrative_evidence["assumed_part"],
        "historical_evidence": {
            "pak_sulfur": historical_request["process_state"]["quality"]["mg_sulfur"],
            "pak_d15": historical_request["process_state"]["quality"]["pak_d15"],
            "lims_sulfur_withheld": evidence["reference_lims"]["sulfur_mg_kg"],
            "lims_split": evidence["reference_lims"]["calendar_split"],
            "observations": evidence["observation_count"],
            "pak_series": [
                {
                    "time": state["timestamp"][11:16],
                    "sulfur": state["quality"]["mg_sulfur"],
                }
                for state in [*historical_request["history"], historical_request["process_state"]]
            ],
        },
    }


def main() -> None:
    data = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "quality": _quality_benchmarks(),
        "reliability": _reliability_benchmarks(),
        "pipeline": _pipeline_benchmarks(),
        "sources": [
            "Quality_neftecode/artifacts/experiments/H_full_pak_residual_oof_calibration/metrics.json",
            "Quality_neftecode/artifacts/experiments/C_telemetry_only/metrics.json",
            "Quality_neftecode/data/processed/split_test.csv",
            "reliability_agent/artifacts/training_report.json",
            "integration/scenarios/catalog.yaml",
            "integration/examples/historical_20260515_1000.json",
            "integration/examples/historical_20260515_1000_evidence.json",
            "integration/examples/illustrative_blend_20260515_1200.json",
            "integration/examples/illustrative_blend_20260515_1200_evidence.json",
            "neftecode_optimizer/docs/recipe_and_controls_audit.md",
        ],
    }
    DASHBOARD.mkdir(parents=True, exist_ok=True)
    (DASHBOARD / "benchmark_data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    template = (DASHBOARD / "template.html").read_text(encoding="utf-8")
    if template.count("/* BENCHMARK_DATA */ null") != 1:
        raise ValueError("Dashboard template must contain one data placeholder")
    embedded = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    (DASHBOARD / "benchmark.html").write_text(
        template.replace("/* BENCHMARK_DATA */ null", embedded), encoding="utf-8"
    )
    print(DASHBOARD / "benchmark.html")
    print(DASHBOARD / "benchmark_data.json")


if __name__ == "__main__":
    main()
