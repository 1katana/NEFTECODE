from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from quality_agent.agent import QualityAgent
from quality_agent.calibrate import ProbabilityCalibrator
from quality_agent.feature_pipeline import FeatureSchema
from quality_agent.features import FeatureConfig
from quality_agent.train import (
    TrainingConfig,
    _absolute_regression_predictions,
    _fit_probability_calibration,
    _prepare_regression_data,
    _regression_subset,
    _select_residual_scale,
    _variant_feature_columns,
    train_all,
)


def test_sigmoid_calibrator_returns_bounded_probabilities() -> None:
    raw = np.asarray([0.05, 0.15, 0.2, 0.6, 0.8, 0.9])
    target = np.asarray([0, 0, 0, 1, 1, 1])
    calibrated = ProbabilityCalibrator("sigmoid").fit(raw, target).transform(raw)
    assert np.all((calibrated >= 0.0) & (calibrated <= 1.0))
    assert np.all(np.diff(calibrated) >= 0.0)


def test_training_policies_keep_classifier_rows_and_drop_pak_for_fallback() -> None:
    features = pd.DataFrame({"hyd_T5__current": [1.0, 2.0, 3.0]})
    target = pd.Series([8.0, 120.0, 12.0])
    reduced_x, reduced_y, excluded = _regression_subset(features, target, 100.0)
    assert excluded == 1
    assert reduced_y.tolist() == [8.0, 12.0]
    assert len(reduced_x) == 2

    schema = FeatureSchema(
        schema_version="test",
        target_column="target_mg_sulfur",
        classification_target_column="target_violation_gt_10",
        all_feature_columns=("hyd_T5__current", "pak_mg_sulfur_value__current"),
        baseline_feature_columns=("hyd_T5__current", "pak_mg_sulfur_value__current"),
        forbidden_model_inputs=("target_mg_sulfur",),
    )
    assert _variant_feature_columns(schema, "telemetry_only") == ["hyd_T5__current"]


def test_residual_regression_uses_pak_baseline_and_excludes_missing_pak() -> None:
    features = pd.DataFrame(
        {
            "hyd_T5__current": [1.0, 2.0, 3.0],
            "pak_mg_sulfur_value__current": [7.0, np.nan, 11.0],
        }
    )
    target = pd.Series([8.0, 9.0, 12.5])

    selected_x, residual, exclusions = _prepare_regression_data(
        features,
        target,
        target_max=None,
        mode="pak_residual",
    )

    assert residual.tolist() == [1.0, 1.5]
    assert exclusions == {"target_max": 0, "missing_pak": 1, "total": 1}
    absolute = _absolute_regression_predictions(
        np.asarray([1.0, 1.5]),
        selected_x,
        "pak_residual",
        residual_scale=0.5,
    )
    assert absolute.tolist() == [7.5, 11.75]


def test_residual_regression_rejects_telemetry_only_variant() -> None:
    with np.testing.assert_raises(ValueError):
        TrainingConfig(model_variant="telemetry_only", regression_mode="pak_residual").validate()


def test_residual_scale_is_selected_only_from_oof_residuals() -> None:
    scale, metrics = _select_residual_scale(
        np.asarray([1.0, 2.0, -1.0]),
        np.asarray([2.0, 4.0, -2.0]),
    )
    assert scale == 0.5
    assert metrics["selected_correction_mae"] == 0.0
    assert metrics["full_correction_mae"] > metrics["selected_correction_mae"]


def test_calibration_policy_selects_without_test_data() -> None:
    raw = np.asarray([0.05, 0.15, 0.8, 0.9, 0.1, 0.2, 0.75, 0.85])
    target = pd.Series([0, 0, 1, 1, 0, 0, 1, 1])
    timestamps = pd.Series(pd.date_range("2026-01-01", periods=8, freq="1D"))
    folds = [{"validation_start_timestamp": timestamps.iloc[4].isoformat()}]

    _, applied, selected, audit = _fit_probability_calibration(
        raw,
        target,
        timestamps,
        folds,
        TrainingConfig(calibration_policy="chronological_holdout"),
    )

    assert audit["selection_uses_test"] is False
    assert audit["selected_output"] in {"raw", "sigmoid"}
    assert isinstance(applied, bool)
    assert len(selected) == len(raw)


def _training_frame(start: str, rows: int) -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=rows, freq="1h")
    signal = np.tile([8.0, 12.0], rows // 2 + 1)[:rows]
    target = signal + np.tile([0.2, -0.2], rows // 2 + 1)[:rows]
    return pd.DataFrame(
        {
            "sample_id": [f"sample-{timestamp.isoformat()}" for timestamp in timestamps],
            "sample_timestamp": timestamps,
            "target_mg_sulfur": target,
            "target_violation_gt_10": (target > 10).astype(int),
            "hyd_T5__current": signal,
            "pak_mg_sulfur_value__current": signal,
        }
    )


def test_training_smoke_writes_complete_bundle(tmp_path: Path) -> None:
    train = _training_frame("2025-01-01", 60)
    validation = _training_frame("2025-01-04", 30)
    test = _training_frame("2025-01-06", 20)
    paths = {}
    for name, frame in (("train", train), ("validation", validation), ("test", test)):
        path = tmp_path / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path

    schema_path = tmp_path / "feature_schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "schema_version": "smoke-v1",
                "target": {
                    "regression": "target_mg_sulfur",
                    "classification": "target_violation_gt_10",
                },
                "all_feature_columns": [
                    "hyd_T5__current",
                    "pak_mg_sulfur_value__current",
                ],
                "baseline_feature_columns": [
                    "hyd_T5__current",
                    "pak_mg_sulfur_value__current",
                ],
                "forbidden_model_inputs": [
                    "target_mg_sulfur",
                    "target_violation_gt_10",
                ],
            }
        ),
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts"

    metrics = train_all(
        str(paths["train"]),
        str(paths["validation"]),
        str(paths["test"]),
        FeatureConfig(),
        str(artifacts),
        str(schema_path),
        TrainingConfig(
            iterations=8,
            depth=2,
            early_stopping_rounds=3,
            cv_splits=2,
            thread_count=1,
        ),
    )

    assert metrics["features"]["count"] == 2
    assert metrics["calibration"]["method"] == "sigmoid"
    assert metrics["regression_policy"]["mode"] == "direct"
    for fold in metrics["calibration"]["folds"]:
        train_end = pd.Timestamp(fold["train_end_timestamp"])
        validation_start = pd.Timestamp(fold["validation_start_timestamp"])
        assert validation_start - train_end >= pd.Timedelta(hours=6)
    expected = {
        "sulfur_reg.cbm",
        "sulfur_reg_lo.cbm",
        "sulfur_reg_hi.cbm",
        "sulfur_clf.cbm",
        "calibrator.pkl",
        "feature_schema.json",
        "metrics.json",
        "operating_thresholds.json",
        "training_manifest.json",
        "model_card.md",
    }
    assert expected.issubset({path.name for path in artifacts.iterdir()})
    agent = QualityAgent(artifacts)
    assert agent.schema.schema_version == "smoke-v1"

    residual_artifacts = tmp_path / "residual-artifacts"
    residual_metrics = train_all(
        str(paths["train"]),
        str(paths["validation"]),
        str(paths["test"]),
        FeatureConfig(),
        str(residual_artifacts),
        str(schema_path),
        TrainingConfig(
            iterations=8,
            depth=2,
            early_stopping_rounds=3,
            cv_splits=2,
            thread_count=1,
            regression_mode="pak_residual",
        ),
    )
    residual_agent = QualityAgent(residual_artifacts)
    assert residual_metrics["regression_policy"]["mode"] == "pak_residual"
    assert residual_metrics["test"]["regression_evaluable_rows"] == len(test)
    assert residual_agent.regression_mode == "pak_residual"
    assert residual_agent.residual_scale == 1.0
    assert residual_agent.schema.schema_version == "smoke-v1-pak-residual"
