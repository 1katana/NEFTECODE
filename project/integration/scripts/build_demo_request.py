from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quality_agent.feature_pipeline import FeatureSchema
from quality_agent.runtime import RuntimeConfig


def build_state(schema: FeatureSchema, timestamp: datetime, step: int) -> dict:
    telemetry: dict[str, float] = {}
    for source, signals in schema.required_signals.items():
        if source not in {"avt", "hyd"}:
            continue
        for number, signal in enumerate(sorted(signals), start=1):
            telemetry[f"{source}_{signal.lower()}"] = 50.0 + number + step * 0.01
    return {
        "timestamp": timestamp.isoformat(),
        "quality": {
            "mg_sulfur": 8.0 + (step % 3) * 0.02,
            "source": "pak",
            "pak_d15": 845.0 + (step % 2) * 0.01,
            "blending": {
                "grade": "SUMMER",
                "components": [
                    {
                        "name": "hydrotreated",
                        "share_pct": 80.0,
                        "share_control": "blend_hydrotreated_share_pct",
                        "use_hydrotreated_sulfur": True,
                        "t95_c": 350.0,
                        "density_kg_m3": 835.0,
                        "cetane_number": 50.0,
                        "relative_cost": 1.0,
                    },
                    {
                        "name": "low_sulfur_tank",
                        "share_pct": 20.0,
                        "share_control": "blend_low_sulfur_share_pct",
                        "sulfur_mg_kg": 2.0,
                        "t95_c": 345.0,
                        "density_kg_m3": 825.0,
                        "cetane_number": 55.0,
                        "relative_cost": 1.08,
                    },
                ],
                "additive_pct": 0.0,
                "additive_control": "cetane_additive_pct",
                "cetane_gain_per_pct": 1.5,
                "additive_relative_cost": 100.0,
            },
        },
        "telemetry": telemetry,
        "data_quality": {"missing": [], "stale": [], "flatline": [], "outlier": []},
        "data_confidence": "HIGH",
        "current_controls": {
            "hyd_t6": 362.7,
            "hyd_f9": 218.7,
            "hyd_p13": 3.918,
            "blend_hydrotreated_share_pct": 80.0,
            "blend_low_sulfur_share_pct": 20.0,
            "cetane_additive_pct": 0.0,
        },
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Build a deterministic fail-closed demo request")
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "integration" / "runtime" / "demo_request.json",
    )
    arguments = parser.parse_args()
    runtime = RuntimeConfig.from_yaml(
        project_root / "Quality_neftecode" / "configs" / "runtime_shadow.yaml"
    )
    schema = FeatureSchema.load(runtime.primary_artifacts / "feature_schema.json")
    start = datetime(2026, 9, 20, tzinfo=UTC)
    states = [build_state(schema, start + timedelta(minutes=10 * step), step) for step in range(37)]
    payload = {
        "run_id": "demo-integrated-shadow-001",
        "input_source": "SYNTHETIC",
        "process_state": states[-1],
        "history": states[:-1],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(arguments.output.resolve())


if __name__ == "__main__":
    main()
