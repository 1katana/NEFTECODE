from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from quality_agent.contracts import DataConfidence, ProcessState
from quality_agent.feature_pipeline import (
    FeatureSchema,
    InMemoryHistoryProvider,
    OnlineFeaturePipeline,
    SourceData,
    build_source_features,
)
from quality_agent.state_adapter import adapt_process_state

BASELINE_COLUMNS = (
    "hyd_T6__current",
    "hyd_T6__roll_mean_60m",
    "hyd_T6__roll_std_60m",
    "hyd_T6__trend_60m",
    "hyd_T6__roll_mean_240m",
    "hyd_T6__roll_std_240m",
    "hyd_T6__trend_240m",
)


def _schema() -> FeatureSchema:
    return FeatureSchema(
        schema_version="test-v1",
        target_column="target_mg_sulfur",
        classification_target_column="target_violation_gt_10",
        all_feature_columns=BASELINE_COLUMNS,
        baseline_feature_columns=BASELINE_COLUMNS,
        forbidden_model_inputs=("target_mg_sulfur",),
    )


def test_online_and_batch_feature_vectors_match() -> None:
    timestamps = pd.date_range("2026-01-01", periods=37, freq="10min")
    source = SourceData(
        name="hyd",
        frame=pd.DataFrame({"date": timestamps, "T6": np.arange(37, dtype=float)}),
        cadence_min=10.0,
    )
    sample_timestamp = timestamps[-1]
    batch, _ = build_source_features(source, pd.Series([sample_timestamp]))

    history = InMemoryHistoryProvider(retention_hours=7.0, cadence_min=10.0)
    for timestamp, value in zip(timestamps, range(37), strict=True):
        history.append("hyd", timestamp, {"T6": value})
    online = OnlineFeaturePipeline(_schema(), history).build(sample_timestamp)

    assert online.diagnostics.has_complete_history
    for column in BASELINE_COLUMNS:
        assert np.isclose(online.values[column], batch.loc[0, column], equal_nan=True)


def test_lims_quality_is_not_ingested_as_pak() -> None:
    state = ProcessState(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quality={"mg_sulfur": 8.0, "source": "lims"},
        telemetry={"hyd_t6": 342.0, "avt_t1": 130.0},
        data_quality={"missing": [], "stale": [], "outlier": []},
        data_confidence=DataConfidence.HIGH,
        current_controls={},
    )

    adapted = adapt_process_state(state)

    assert "pak_mg_sulfur" not in adapted.sources
    assert "LIMS_VALUE_NOT_USED_AS_FEATURE" in adapted.warnings


def test_state_adapter_maps_orchestrator_names_to_training_names() -> None:
    state = ProcessState(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quality={"mg_sulfur": 8.0, "source": "pak", "pak_d15": 845.0},
        telemetry={"hyd_t6": 340.0, "avt_t1": 130.0},
        data_quality={"missing": [], "stale": [], "outlier": []},
        data_confidence=DataConfidence.HIGH,
        current_controls={"hyd_t6": 342.0},
    )

    adapted = adapt_process_state(state)

    assert adapted.sources["hyd"]["T6"] == 342.0
    assert adapted.sources["avt"]["T1"] == 130.0
    assert adapted.sources["pak_mg_sulfur"]["value"] == 8.0
    assert adapted.sources["pak_d15"]["value"] == 845.0


def test_q21_sentinel_307_is_not_ingested() -> None:
    state = ProcessState(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quality={},
        telemetry={"hyd_q21": 307.0},
        data_quality={},
        data_confidence=DataConfidence.HIGH,
    )

    adapted = adapt_process_state(state)

    assert "hyd" not in adapted.sources
    assert "Q21_OUTLIER_307_NOT_INGESTED" in adapted.warnings


def test_downstream_blend_controls_are_not_reported_as_unmapped_telemetry() -> None:
    state = ProcessState(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quality={},
        telemetry={},
        current_controls={
            "blend_hydrotreated_share_pct": 80.0,
            "blend_low_sulfur_share_pct": 20.0,
            "cetane_additive_pct": 0.0,
        },
        data_quality={},
        data_confidence=DataConfidence.HIGH,
    )

    adapted = adapt_process_state(state)

    assert not [warning for warning in adapted.warnings if warning.startswith("UNMAPPED_")]
