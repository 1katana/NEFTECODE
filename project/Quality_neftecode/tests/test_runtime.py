from __future__ import annotations

from pathlib import Path

import pytest

from quality_agent.runtime import RuntimeConfig, check_runtime_bundle

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pinned_runtime_bundle_is_ready_for_shadow() -> None:
    runtime = RuntimeConfig.from_yaml(PROJECT_ROOT / "configs" / "runtime_shadow.yaml")

    result = check_runtime_bundle(runtime)

    assert result["status"] == "READY_FOR_SHADOW"
    assert result["automatic_promotion"] is False
    assert result["primary"]["model_variant"] == "full"
    assert result["fallback"]["model_variant"] == "telemetry_only"
    assert result["point_policy"] == "pak_passthrough"
    assert result["candidate_effect"]["response_time_hours"] == 1.0
    assert set(result["candidate_effect"]["sulfur_sensitivity"]) == {
        "hyd_t6",
        "hyd_f9",
        "hyd_p13",
    }


def test_runtime_rejects_non_shadow_mode(tmp_path) -> None:
    config = tmp_path / "runtime.yaml"
    config.write_text(
        "\n".join(
            [
                "mode: production",
                f"primary_artifacts: {PROJECT_ROOT / 'artifacts'}",
                f"telemetry_fallback_artifacts: {PROJECT_ROOT / 'artifacts'}",
                "point_policy: pak_passthrough",
                "shadow_log: shadow.jsonl",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Only shadow runtime mode is approved"):
        RuntimeConfig.from_yaml(config)
