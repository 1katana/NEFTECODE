from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    median_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)

from .calibrate import CalibrationMethod, ProbabilityCalibrator
from .feature_pipeline import FeatureSchema
from .features import FeatureConfig

ModelVariant = Literal["full", "telemetry_only"]
RegressionMode = Literal["direct", "pak_residual"]
ResidualScaleMode = Literal["none", "blocked_oof_mae"]
CalibrationPolicy = Literal["always", "chronological_holdout"]
PAK_CURRENT_FEATURE = "pak_mg_sulfur_value__current"


@dataclass(frozen=True)
class TrainingConfig:
    iterations: int = 2_000
    learning_rate: float = 0.05
    depth: int = 6
    early_stopping_rounds: int = 150
    cv_splits: int = 4
    random_seed: int = 42
    thread_count: int = -1
    calibration_method: CalibrationMethod = "sigmoid"
    calibration_policy: CalibrationPolicy = "always"
    cv_gap_hours: float = 6.0
    model_variant: ModelVariant = "full"
    regression_target_max: float | None = None
    regression_mode: RegressionMode = "direct"
    residual_scale_mode: ResidualScaleMode = "none"

    def validate(self) -> None:
        if self.model_variant not in {"full", "telemetry_only"}:
            raise ValueError(f"Unsupported model_variant: {self.model_variant!r}")
        if self.cv_gap_hours < 0:
            raise ValueError("cv_gap_hours must be non-negative")
        if self.regression_target_max is not None and self.regression_target_max <= 0:
            raise ValueError("regression_target_max must be positive")
        if self.regression_mode not in {"direct", "pak_residual"}:
            raise ValueError(f"Unsupported regression_mode: {self.regression_mode!r}")
        if self.regression_mode == "pak_residual" and self.model_variant != "full":
            raise ValueError("pak_residual regression requires the full PAK feature variant")
        if self.residual_scale_mode not in {"none", "blocked_oof_mae"}:
            raise ValueError(f"Unsupported residual_scale_mode: {self.residual_scale_mode!r}")
        if self.residual_scale_mode != "none" and self.regression_mode != "pak_residual":
            raise ValueError("Residual scaling requires pak_residual regression")
        if self.calibration_policy not in {"always", "chronological_holdout"}:
            raise ValueError(f"Unsupported calibration_policy: {self.calibration_policy!r}")


def _read_split(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    if "sample_timestamp" not in frame.columns:
        raise ValueError(f"{path} misses sample_timestamp")
    frame["sample_timestamp"] = pd.to_datetime(frame["sample_timestamp"], errors="raise")
    frame = frame.sort_values("sample_timestamp", kind="stable").reset_index(drop=True)
    if frame["sample_timestamp"].duplicated().any():
        raise ValueError(f"{path} contains duplicate sample timestamps")
    return frame


def _validate_chronology(train: pd.DataFrame, validation: pd.DataFrame, test: pd.DataFrame) -> None:
    if train.empty or validation.empty or test.empty:
        raise ValueError("Train, validation and test splits must be non-empty")
    if train["sample_timestamp"].max() >= validation["sample_timestamp"].min():
        raise ValueError("Train and validation overlap or are not chronological")
    if validation["sample_timestamp"].max() >= test["sample_timestamp"].min():
        raise ValueError("Validation and test overlap or are not chronological")
    sample_ids = [
        set(frame["sample_id"])
        for frame in (train, validation, test)
        if "sample_id" in frame.columns
    ]
    if len(sample_ids) == 3 and (
        sample_ids[0] & sample_ids[1]
        or sample_ids[0] & sample_ids[2]
        or sample_ids[1] & sample_ids[2]
    ):
        raise ValueError("Sample leakage between chronological splits")


def _split_xy(
    frame: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
) -> tuple[pd.DataFrame, pd.Series]:
    missing = sorted(set(feature_columns + [target_column]) - set(frame.columns))
    if missing:
        raise ValueError(f"Training data misses schema columns: {missing[:10]}")
    features = frame[feature_columns].copy()
    target = frame[target_column].astype(float)
    if np.isinf(features.to_numpy(dtype=float)).any():
        raise ValueError("Infinite feature values are forbidden")
    if not np.isfinite(target).all():
        raise ValueError("Target contains non-finite values")
    return features, target


def _variant_feature_columns(schema: FeatureSchema, variant: ModelVariant) -> list[str]:
    columns = list(schema.baseline_feature_columns)
    if variant == "telemetry_only":
        columns = [column for column in columns if not column.startswith("pak_")]
    if not columns:
        raise ValueError(f"Model variant {variant!r} has no feature columns")
    return columns


def _regression_subset(
    features: pd.DataFrame,
    target: pd.Series,
    target_max: float | None,
) -> tuple[pd.DataFrame, pd.Series, int]:
    if target_max is None:
        return features, target, 0
    include = target <= target_max
    excluded = int((~include).sum())
    if include.sum() < 2:
        raise ValueError("Regression sensitivity policy leaves fewer than two rows")
    return features.loc[include], target.loc[include], excluded


def _prepare_regression_data(
    features: pd.DataFrame,
    target: pd.Series,
    target_max: float | None,
    mode: RegressionMode,
) -> tuple[pd.DataFrame, pd.Series, dict[str, int]]:
    selected_x, selected_target, target_max_excluded = _regression_subset(
        features,
        target,
        target_max,
    )
    missing_pak_excluded = 0
    if mode == "pak_residual":
        if PAK_CURRENT_FEATURE not in selected_x:
            raise ValueError(f"pak_residual regression requires {PAK_CURRENT_FEATURE}")
        valid_pak = selected_x[PAK_CURRENT_FEATURE].notna()
        missing_pak_excluded = int((~valid_pak).sum())
        selected_x = selected_x.loc[valid_pak]
        selected_target = selected_target.loc[valid_pak] - selected_x[PAK_CURRENT_FEATURE]
        if len(selected_x) < 2:
            raise ValueError("pak_residual policy leaves fewer than two rows")
    return (
        selected_x,
        selected_target,
        {
            "target_max": target_max_excluded,
            "missing_pak": missing_pak_excluded,
            "total": target_max_excluded + missing_pak_excluded,
        },
    )


def _absolute_regression_predictions(
    model_prediction: np.ndarray,
    features: pd.DataFrame,
    mode: RegressionMode,
    residual_scale: float = 1.0,
) -> np.ndarray:
    prediction = np.asarray(model_prediction, dtype=float)
    if mode == "direct":
        return prediction
    if PAK_CURRENT_FEATURE not in features:
        raise ValueError(f"pak_residual inference requires {PAK_CURRENT_FEATURE}")
    return residual_scale * prediction + features[PAK_CURRENT_FEATURE].to_numpy(dtype=float)


def _class_weights(target: pd.Series | np.ndarray) -> list[float]:
    values = np.asarray(target, dtype=int)
    negatives = int((values == 0).sum())
    positives = int((values == 1).sum())
    if negatives == 0 or positives == 0:
        raise ValueError("Classifier training requires both classes")
    return [1.0, negatives / positives]


def _regressor(
    config: TrainingConfig,
    loss_function: str,
    iterations: int | None = None,
) -> CatBoostRegressor:
    return CatBoostRegressor(
        iterations=iterations or config.iterations,
        learning_rate=config.learning_rate,
        depth=config.depth,
        loss_function=loss_function,
        random_seed=config.random_seed,
        thread_count=config.thread_count,
        verbose=False,
        allow_writing_files=False,
    )


def _classifier(
    config: TrainingConfig,
    target: pd.Series | np.ndarray,
    iterations: int | None = None,
) -> CatBoostClassifier:
    return CatBoostClassifier(
        iterations=iterations or config.iterations,
        learning_rate=config.learning_rate,
        depth=config.depth,
        loss_function="Logloss",
        random_seed=config.random_seed,
        thread_count=config.thread_count,
        verbose=False,
        allow_writing_files=False,
        class_weights=_class_weights(target),
    )


def _best_iteration(model, fallback: int) -> int:
    best = int(model.get_best_iteration())
    return fallback if best < 0 else best + 1


def _fit_pilot_models(
    regression_train_x: pd.DataFrame,
    regression_train_y: pd.Series,
    regression_validation_x: pd.DataFrame,
    regression_validation_y: pd.Series,
    classifier_train_x: pd.DataFrame,
    classifier_train_y: pd.Series,
    classifier_validation_x: pd.DataFrame,
    classifier_validation_y: pd.Series,
    config: TrainingConfig,
) -> dict[str, int]:
    model_specs = {
        "regression": (
            _regressor(config, "MAE"),
            regression_train_y,
            regression_validation_y,
        ),
        "quantile_low": (
            _regressor(config, "Quantile:alpha=0.1"),
            regression_train_y,
            regression_validation_y,
        ),
        "quantile_high": (
            _regressor(config, "Quantile:alpha=0.9"),
            regression_train_y,
            regression_validation_y,
        ),
    }
    best_iterations: dict[str, int] = {}
    for name, (model, target, validation_target) in model_specs.items():
        model.fit(
            regression_train_x,
            target,
            eval_set=(regression_validation_x, validation_target),
            early_stopping_rounds=config.early_stopping_rounds,
        )
        best_iterations[name] = _best_iteration(model, config.iterations)

    classifier = _classifier(config, classifier_train_y)
    classifier.fit(
        classifier_train_x,
        classifier_train_y,
        eval_set=(classifier_validation_x, classifier_validation_y),
        early_stopping_rounds=config.early_stopping_rounds,
    )
    best_iterations["classifier"] = _best_iteration(classifier, config.iterations)
    return best_iterations


def _blocked_oof_probabilities(
    features: pd.DataFrame,
    risk_target: pd.Series,
    timestamps: pd.Series,
    classifier_iterations: int,
    config: TrainingConfig,
) -> tuple[np.ndarray, list[dict]]:
    probabilities = np.full(len(features), np.nan, dtype=float)
    folds: list[dict] = []
    start = timestamps.min()
    end = timestamps.max()
    boundaries = pd.date_range(start, end, periods=config.cv_splits + 2)
    for fold_number in range(1, config.cv_splits + 1):
        validation_start = boundaries[fold_number]
        validation_end = boundaries[fold_number + 1]
        cutoff = validation_start - pd.Timedelta(hours=config.cv_gap_hours)
        train_indices = np.flatnonzero((timestamps < cutoff).to_numpy())
        if fold_number == config.cv_splits:
            validation_mask = timestamps.between(
                validation_start,
                validation_end,
                inclusive="both",
            )
        else:
            validation_mask = timestamps.between(
                validation_start,
                validation_end,
                inclusive="left",
            )
        validation_indices = np.flatnonzero(validation_mask.to_numpy())
        if not len(train_indices) or not len(validation_indices):
            continue
        fold_target = risk_target.iloc[train_indices]
        if fold_target.nunique() < 2:
            continue
        model = _classifier(config, fold_target, classifier_iterations)
        model.fit(features.iloc[train_indices], fold_target)
        probabilities[validation_indices] = model.predict_proba(features.iloc[validation_indices])[
            :, 1
        ]
        folds.append(
            {
                "fold": fold_number,
                "train_rows": len(train_indices),
                "validation_rows": len(validation_indices),
                "train_end_index": int(train_indices[-1]),
                "validation_start_index": int(validation_indices[0]),
                "validation_end_index": int(validation_indices[-1]),
                "gap_hours": config.cv_gap_hours,
                "train_end_timestamp": timestamps.iloc[train_indices[-1]].isoformat(),
                "validation_start_timestamp": validation_start.isoformat(),
                "validation_end_timestamp": validation_end.isoformat(),
                "validation_violations": int(risk_target.iloc[validation_indices].sum()),
            }
        )
    return probabilities, folds


def _blocked_oof_residual_corrections(
    features: pd.DataFrame,
    target: pd.Series,
    timestamps: pd.Series,
    regression_iterations: int,
    config: TrainingConfig,
) -> tuple[np.ndarray, list[dict]]:
    corrections = np.full(len(features), np.nan, dtype=float)
    folds: list[dict] = []
    boundaries = pd.date_range(timestamps.min(), timestamps.max(), periods=config.cv_splits + 2)
    for fold_number in range(1, config.cv_splits + 1):
        validation_start = boundaries[fold_number]
        validation_end = boundaries[fold_number + 1]
        cutoff = validation_start - pd.Timedelta(hours=config.cv_gap_hours)
        train_indices = np.flatnonzero((timestamps < cutoff).to_numpy())
        validation_mask = timestamps.between(
            validation_start,
            validation_end,
            inclusive="both" if fold_number == config.cv_splits else "left",
        )
        validation_indices = np.flatnonzero(validation_mask.to_numpy())
        if not len(train_indices) or not len(validation_indices):
            continue

        train_x, train_residual, train_exclusions = _prepare_regression_data(
            features.iloc[train_indices],
            target.iloc[train_indices],
            config.regression_target_max,
            "pak_residual",
        )
        validation_x, _, validation_exclusions = _prepare_regression_data(
            features.iloc[validation_indices],
            target.iloc[validation_indices],
            config.regression_target_max,
            "pak_residual",
        )
        model = _regressor(config, "MAE", regression_iterations)
        model.fit(train_x, train_residual)
        validation_prediction = model.predict(validation_x)
        corrections[validation_x.index.to_numpy(dtype=int)] = validation_prediction
        validation_actual_residual = (
            target.loc[validation_x.index] - validation_x[PAK_CURRENT_FEATURE]
        ).to_numpy(dtype=float)
        diagnostic_scale, diagnostic_metrics = _select_residual_scale(
            validation_actual_residual,
            np.asarray(validation_prediction, dtype=float),
        )
        folds.append(
            {
                "fold": fold_number,
                "train_rows": len(train_x),
                "validation_rows": len(validation_x),
                "train_exclusions": train_exclusions,
                "validation_exclusions": validation_exclusions,
                "gap_hours": config.cv_gap_hours,
                "train_end_timestamp": timestamps.iloc[train_indices[-1]].isoformat(),
                "validation_start_timestamp": validation_start.isoformat(),
                "validation_end_timestamp": validation_end.isoformat(),
                "diagnostic_only": {
                    "fold_optimal_scale": diagnostic_scale,
                    **diagnostic_metrics,
                },
            }
        )
    return corrections, folds


def _select_residual_scale(
    actual_residual: np.ndarray,
    predicted_residual: np.ndarray,
) -> tuple[float, dict[str, float]]:
    valid = np.isfinite(actual_residual) & np.isfinite(predicted_residual)
    if not valid.any():
        raise ValueError("No finite blocked OOF residual predictions")
    actual = actual_residual[valid]
    predicted = predicted_residual[valid]
    candidates = np.linspace(0.0, 1.0, 101)
    scored = [
        (float(mean_absolute_error(actual, scale * predicted)), float(scale))
        for scale in candidates
    ]
    best_mae, best_scale = min(scored, key=lambda item: (item[0], item[1]))
    return best_scale, {
        "rows": int(valid.sum()),
        "pak_no_correction_mae": float(mean_absolute_error(actual, np.zeros_like(actual))),
        "full_correction_mae": float(mean_absolute_error(actual, predicted)),
        "selected_correction_mae": best_mae,
    }


def _fit_final_models(
    regression_features: pd.DataFrame,
    regression_target: pd.Series,
    classifier_features: pd.DataFrame,
    classifier_target: pd.Series,
    best_iterations: dict[str, int],
    config: TrainingConfig,
) -> tuple[
    CatBoostRegressor,
    CatBoostRegressor,
    CatBoostRegressor,
    CatBoostClassifier,
]:
    regression = _regressor(config, "MAE", best_iterations["regression"])
    quantile_low = _regressor(config, "Quantile:alpha=0.1", best_iterations["quantile_low"])
    quantile_high = _regressor(config, "Quantile:alpha=0.9", best_iterations["quantile_high"])
    classifier = _classifier(config, classifier_target, best_iterations["classifier"])
    regression.fit(regression_features, regression_target)
    quantile_low.fit(regression_features, regression_target)
    quantile_high.fit(regression_features, regression_target)
    classifier.fit(classifier_features, classifier_target)
    return regression, quantile_low, quantile_high, classifier


def _expected_calibration_error(
    target: np.ndarray,
    probability: np.ndarray,
    bins: int = 10,
) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    error = 0.0
    for lower, upper in pairwise(edges):
        include = (probability >= lower) & (
            probability <= upper if upper == 1.0 else probability < upper
        )
        if not include.any():
            continue
        error += include.mean() * abs(target[include].mean() - probability[include].mean())
    return float(error if len(target) else np.nan)


def _select_operating_threshold(
    target: np.ndarray,
    probability: np.ndarray,
) -> tuple[float, float]:
    candidates = np.unique(np.r_[0.05, np.arange(0.1, 0.91, 0.05), 0.95])
    scored = [
        (
            float(f1_score(target, probability >= threshold, zero_division=0)),
            float(threshold),
        )
        for threshold in candidates
    ]
    best_f1, best_threshold = max(scored, key=lambda item: (item[0], -item[1]))
    return best_threshold, best_f1


def _regression_metrics(target: pd.Series, prediction: np.ndarray) -> dict[str, float]:
    return {
        "MAE": float(mean_absolute_error(target, prediction)),
        "median_AE": float(median_absolute_error(target, prediction)),
        "RMSE": float(np.sqrt(mean_squared_error(target, prediction))),
        "R2": float(r2_score(target, prediction)),
    }


def _classification_metrics(
    target: np.ndarray,
    probability: np.ndarray,
    threshold: float,
) -> dict[str, float]:
    predicted = probability >= threshold
    return {
        "ROC_AUC": float(roc_auc_score(target, probability)),
        "PR_AUC": float(average_precision_score(target, probability)),
        "precision": float(precision_score(target, predicted, zero_division=0)),
        "recall": float(recall_score(target, predicted, zero_division=0)),
        "F1": float(f1_score(target, predicted, zero_division=0)),
        "Brier": float(brier_score_loss(target, probability)),
        "ECE_10": _expected_calibration_error(target, probability),
        "threshold": threshold,
    }


def _fit_probability_calibration(
    oof_raw: np.ndarray,
    risk_target: pd.Series,
    timestamps: pd.Series,
    folds: list[dict],
    config: TrainingConfig,
) -> tuple[ProbabilityCalibrator, bool, np.ndarray, dict[str, object]]:
    valid = np.isfinite(oof_raw)
    raw = oof_raw[valid]
    target = risk_target.to_numpy(dtype=int)[valid]
    if np.unique(target).size < 2:
        raise ValueError("Blocked CV produced insufficient classes for calibration")

    final_calibrator = ProbabilityCalibrator(method=config.calibration_method).fit(raw, target)
    if config.calibration_policy == "always":
        selected = final_calibrator.transform(raw)
        return (
            final_calibrator,
            True,
            selected,
            {
                "policy": "always",
                "selected_output": config.calibration_method,
                "selection_uses_test": False,
            },
        )

    if not folds:
        raise ValueError("Chronological calibration selection requires blocked folds")
    holdout_start = pd.Timestamp(folds[-1]["validation_start_timestamp"])
    valid_timestamps = timestamps.loc[valid]
    fit_mask = (valid_timestamps < holdout_start).to_numpy()
    evaluation_mask = ~fit_mask
    if np.unique(target[fit_mask]).size < 2 or np.unique(target[evaluation_mask]).size < 2:
        raise ValueError("Calibration holdout must contain both classes in fit and evaluation")

    selector = ProbabilityCalibrator(method=config.calibration_method).fit(
        raw[fit_mask], target[fit_mask]
    )
    calibrated_evaluation = selector.transform(raw[evaluation_mask])
    raw_evaluation = raw[evaluation_mask]
    evaluation_target = target[evaluation_mask]
    raw_brier = float(brier_score_loss(evaluation_target, raw_evaluation))
    calibrated_brier = float(brier_score_loss(evaluation_target, calibrated_evaluation))
    apply_calibrator = calibrated_brier < raw_brier
    selected_output = config.calibration_method if apply_calibrator else "raw"
    selected = final_calibrator.transform(raw) if apply_calibrator else raw
    return (
        final_calibrator,
        apply_calibrator,
        selected,
        {
            "policy": "chronological_holdout",
            "selected_output": selected_output,
            "selection_uses_test": False,
            "fit_rows": int(fit_mask.sum()),
            "evaluation_rows": int(evaluation_mask.sum()),
            "holdout_start": holdout_start.isoformat(),
            "raw": {
                "Brier": raw_brier,
                "ECE_10": _expected_calibration_error(evaluation_target, raw_evaluation),
            },
            config.calibration_method: {
                "Brier": calibrated_brier,
                "ECE_10": _expected_calibration_error(
                    evaluation_target,
                    calibrated_evaluation,
                ),
            },
        },
    )


def _segmented_test_metrics(
    test: pd.DataFrame,
    target: pd.Series,
    prediction: np.ndarray,
    probability: np.ndarray,
    sulfur_limit: float,
    threshold: float,
) -> dict[str, dict]:
    masks: dict[str, np.ndarray] = {
        "target_le_100": target.to_numpy() <= 100.0,
        "target_gt_100": target.to_numpy() > 100.0,
    }
    flatline_column = "pak_mg_sulfur_value__flatline_age_min"
    if flatline_column in test:
        age = test[flatline_column].to_numpy(dtype=float)
        masks.update(
            {
                "pak_ok_lt_30m": np.isfinite(age) & (age < 30.0),
                "pak_suspect_30_to_60m": np.isfinite(age) & (age >= 30.0) & (age < 60.0),
                "pak_flatline_ge_60m": np.isfinite(age) & (age >= 60.0),
                "pak_health_unknown": ~np.isfinite(age),
            }
        )

    risk = (target > sulfur_limit).astype(int).to_numpy()
    result: dict[str, dict] = {}
    for name, mask in masks.items():
        if not mask.any():
            continue
        regression_mask = mask & np.isfinite(prediction)
        segment: dict[str, object] = {
            "rows": int(mask.sum()),
            "violations": int(risk[mask].sum()),
            "regression_rows": int(regression_mask.sum()),
        }
        if regression_mask.any():
            segment["regression"] = _regression_metrics(
                target.loc[regression_mask],
                prediction[regression_mask],
            )
        if np.unique(risk[mask]).size == 2:
            segment["classifier"] = _classification_metrics(
                risk[mask], probability[mask], threshold
            )
        result[name] = segment
    return result


def _naive_baselines(
    development_target: pd.Series,
    test: pd.DataFrame,
    target_column: str,
    sulfur_limit: float,
) -> dict:
    test_target = test[target_column].astype(float)
    median_prediction = np.full(len(test), float(development_target.median()))
    prevalence = float((development_target > sulfur_limit).mean())
    result = {
        "train_median_regression": _regression_metrics(test_target, median_prediction),
        "development_prevalence": prevalence,
        "prevalence_brier": float(
            brier_score_loss(
                (test_target > sulfur_limit).astype(int),
                np.full(len(test), prevalence),
            )
        ),
    }
    pak_column = "pak_mg_sulfur_value__current"
    if pak_column in test:
        valid = test[pak_column].notna()
        result["pak_current_regression"] = _regression_metrics(
            test_target.loc[valid],
            test.loc[valid, pak_column].to_numpy(dtype=float),
        )
    return result


def _schema_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_variant_schema(
    source_path: str | Path,
    output_path: Path,
    feature_columns: list[str],
    variant: ModelVariant,
    regression_mode: RegressionMode,
) -> str:
    payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
    payload["baseline_feature_columns"] = feature_columns
    payload["model_variant"] = variant
    payload["regression_mode"] = regression_mode
    suffixes = []
    if variant != "full":
        suffixes.append(variant.replace("_", "-"))
    if regression_mode != "direct":
        suffixes.append(regression_mode.replace("_", "-"))
    if suffixes:
        payload["schema_version"] = f"{payload['schema_version']}-{'-'.join(suffixes)}"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(payload["schema_version"])


def _write_model_card(path: Path, metrics: dict) -> None:
    regression = metrics["test"]["regression"]
    classifier = metrics["test"]["classifier_calibrated"]
    content = f"""# QualityAgent model card

- Created: {metrics["created_at_utc"]}
- Target: {metrics["target_column"]}
- Sulfur limit: {metrics["sulfur_limit"]} mg/kg
- Model variant: {metrics["model_variant"]}
- Regression mode: {metrics["regression_policy"].get("mode", "direct")}
- Residual scale: {metrics["regression_policy"].get("residual_scale", 1.0)}
- Regression target maximum: {metrics["regression_policy"]["target_max"]}
- Features: {metrics["features"]["count"]}
- Probability output: {metrics["calibration"].get("selected_output", metrics["calibration"]["method"])}
- Calibration selection: {metrics["calibration"].get("policy", "always")}, blocked time-series OOF
- Regression test rows: {metrics["test"].get("regression_evaluable_rows", metrics["rows"]["test"])} / {metrics["rows"]["test"]}

## Test metrics

- MAE: {regression["MAE"]:.4f}
- Median AE: {regression["median_AE"]:.4f}
- RMSE: {regression["RMSE"]:.4f}
- PR-AUC: {classifier["PR_AUC"]:.4f}
- Recall: {classifier["recall"]:.4f}
- Precision: {classifier["precision"]:.4f}
- Brier: {classifier["Brier"]:.4f}

This artifact estimates observed quality. It is not a causal candidate-action model.
"""
    path.write_text(content, encoding="utf-8")


def train_all(
    train_csv: str,
    val_csv: str,
    test_csv: str,
    feature_config: FeatureConfig,
    out_dir: str = "artifacts",
    schema_path: str | None = None,
    training_config: TrainingConfig | None = None,
) -> dict:
    if not schema_path:
        raise ValueError("feature_schema.json is required; implicit feature selection is forbidden")
    training_config = training_config or TrainingConfig()
    training_config.validate()
    schema = FeatureSchema.load(schema_path)
    feature_columns = _variant_feature_columns(schema, training_config.model_variant)
    target_column = schema.target_column

    train = _read_split(train_csv)
    validation = _read_split(val_csv)
    test = _read_split(test_csv)
    _validate_chronology(train, validation, test)

    train_x, train_y = _split_xy(train, feature_columns, target_column)
    validation_x, validation_y = _split_xy(validation, feature_columns, target_column)
    test_x, test_y = _split_xy(test, feature_columns, target_column)

    regression_train_x, regression_train_y, regression_train_exclusions = _prepare_regression_data(
        train_x,
        train_y,
        training_config.regression_target_max,
        training_config.regression_mode,
    )
    (
        regression_validation_x,
        regression_validation_y,
        regression_validation_exclusions,
    ) = _prepare_regression_data(
        validation_x,
        validation_y,
        training_config.regression_target_max,
        training_config.regression_mode,
    )
    train_risk = (train_y > feature_config.sulfur_limit).astype(int)
    validation_risk = (validation_y > feature_config.sulfur_limit).astype(int)

    best_iterations = _fit_pilot_models(
        regression_train_x,
        regression_train_y,
        regression_validation_x,
        regression_validation_y,
        train_x,
        train_risk,
        validation_x,
        validation_risk,
        training_config,
    )
    development = pd.concat([train, validation], ignore_index=True)
    development_x, development_y = _split_xy(development, feature_columns, target_column)
    development_risk = (development_y > feature_config.sulfur_limit).astype(int)
    residual_scale = 1.0
    residual_scale_selection: dict[str, object] | None = None
    if training_config.residual_scale_mode == "blocked_oof_mae":
        oof_residual, residual_folds = _blocked_oof_residual_corrections(
            development_x,
            development_y,
            development["sample_timestamp"],
            best_iterations["regression"],
            training_config,
        )
        actual_residual = (development_y - development_x[PAK_CURRENT_FEATURE]).to_numpy(dtype=float)
        residual_scale, residual_oof_metrics = _select_residual_scale(
            actual_residual,
            oof_residual,
        )
        residual_scale_selection = {
            "method": "minimum MAE on blocked OOF residual predictions",
            "grid": {"minimum": 0.0, "maximum": 1.0, "step": 0.01},
            "selected_scale": residual_scale,
            "metrics": residual_oof_metrics,
            "folds": residual_folds,
        }
    oof_raw, folds = _blocked_oof_probabilities(
        development_x,
        development_risk,
        development["sample_timestamp"],
        best_iterations["classifier"],
        training_config,
    )
    calibration_mask = np.isfinite(oof_raw)
    calibrator, apply_calibrator, oof_selected, calibration_selection = (
        _fit_probability_calibration(
            oof_raw,
            development_risk,
            development["sample_timestamp"],
            folds,
            training_config,
        )
    )
    operating_threshold, oof_f1 = _select_operating_threshold(
        development_risk.to_numpy()[calibration_mask],
        oof_selected,
    )

    (
        regression_development_x,
        regression_development_y,
        regression_development_exclusions,
    ) = _prepare_regression_data(
        development_x,
        development_y,
        training_config.regression_target_max,
        training_config.regression_mode,
    )
    regression, quantile_low, quantile_high, classifier = _fit_final_models(
        regression_development_x,
        regression_development_y,
        development_x,
        development_risk,
        best_iterations,
        training_config,
    )
    prediction = _absolute_regression_predictions(
        regression.predict(test_x),
        test_x,
        training_config.regression_mode,
        residual_scale=residual_scale,
    )
    lower = _absolute_regression_predictions(
        quantile_low.predict(test_x),
        test_x,
        training_config.regression_mode,
        residual_scale=residual_scale,
    )
    upper = _absolute_regression_predictions(
        quantile_high.predict(test_x),
        test_x,
        training_config.regression_mode,
        residual_scale=residual_scale,
    )
    interval_lower = np.minimum(lower, upper)
    interval_upper = np.maximum(lower, upper)
    raw_probability = classifier.predict_proba(test_x)[:, 1]
    calibrated_probability = calibrator.transform(raw_probability)
    selected_probability = calibrated_probability if apply_calibrator else raw_probability
    test_risk = (test_y > feature_config.sulfur_limit).astype(int).to_numpy()

    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifact_schema_path = output / "feature_schema.json"
    artifact_schema_version = _write_variant_schema(
        schema_path,
        artifact_schema_path,
        feature_columns,
        training_config.model_variant,
        training_config.regression_mode,
    )
    regression.save_model(str(output / "sulfur_reg.cbm"))
    quantile_low.save_model(str(output / "sulfur_reg_lo.cbm"))
    quantile_high.save_model(str(output / "sulfur_reg_hi.cbm"))
    classifier.save_model(str(output / "sulfur_clf.cbm"))
    calibrator.save(output / "calibrator.pkl")

    created_at_utc = datetime.now(timezone.utc).isoformat()
    training_id = f"{output.name}:{created_at_utc}"
    metrics = {
        "training_id": training_id,
        "created_at_utc": created_at_utc,
        "target_column": target_column,
        "sulfur_limit": feature_config.sulfur_limit,
        "schema_version": artifact_schema_version,
        "schema_sha256": _schema_digest(artifact_schema_path),
        "model_variant": training_config.model_variant,
        "regression_policy": {
            "mode": training_config.regression_mode,
            "residual_scale_mode": training_config.residual_scale_mode,
            "residual_scale": residual_scale,
            "residual_scale_selection": residual_scale_selection,
            "target_max": training_config.regression_target_max,
            "train_rows_excluded": regression_train_exclusions["total"],
            "validation_rows_excluded": regression_validation_exclusions["total"],
            "development_rows_excluded": regression_development_exclusions["total"],
            "train_exclusions": regression_train_exclusions,
            "validation_exclusions": regression_validation_exclusions,
            "development_exclusions": regression_development_exclusions,
            "classifier_keeps_all_valid_targets": True,
        },
        "rows": {
            "train": len(train),
            "validation": len(validation),
            "development": len(development),
            "regression_development": len(regression_development_y),
            "test": len(test),
        },
        "features": {"count": len(feature_columns), "columns": feature_columns},
        "training_config": asdict(training_config),
        "best_iterations": best_iterations,
        "calibration": {
            "method": training_config.calibration_method,
            "policy": training_config.calibration_policy,
            "applied": apply_calibrator,
            "selected_output": calibration_selection["selected_output"],
            "selection": calibration_selection,
            "oof_rows": int(calibration_mask.sum()),
            "oof_violations": int(development_risk.to_numpy()[calibration_mask].sum()),
            "oof_F1_at_selected_threshold": oof_f1,
            "folds": folds,
        },
        "operating_threshold": operating_threshold,
        "test": {
            "regression_evaluable_rows": int(np.isfinite(prediction).sum()),
            "regression": _regression_metrics(
                test_y.loc[np.isfinite(prediction)],
                prediction[np.isfinite(prediction)],
            ),
            "interval": {
                "coverage_80": float(
                    np.mean(
                        (
                            test_y.loc[np.isfinite(prediction)]
                            >= interval_lower[np.isfinite(prediction)]
                        )
                        & (
                            test_y.loc[np.isfinite(prediction)]
                            <= interval_upper[np.isfinite(prediction)]
                        )
                    )
                ),
                "average_width": float(
                    np.mean(
                        interval_upper[np.isfinite(prediction)]
                        - interval_lower[np.isfinite(prediction)]
                    )
                ),
            },
            "classifier_raw": _classification_metrics(
                test_risk,
                raw_probability,
                operating_threshold,
            ),
            "classifier_calibrated": _classification_metrics(
                test_risk,
                calibrated_probability,
                operating_threshold,
            ),
            "classifier_selected": _classification_metrics(
                test_risk,
                selected_probability,
                operating_threshold,
            ),
            "segments": _segmented_test_metrics(
                test,
                test_y,
                prediction,
                selected_probability,
                feature_config.sulfur_limit,
                operating_threshold,
            ),
        },
        "naive_baselines": _naive_baselines(
            development_y,
            test,
            target_column,
            feature_config.sulfur_limit,
        ),
        "limitations": [
            "LIMS timestamp is provisionally treated as sample collection time and must be confirmed for production.",
            "Three target values above 100 mg/kg remain under domain review; compare the configured sensitivity run.",
            "This bundle estimates observed quality and is not candidate-action causal inference.",
        ],
    }
    (output / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "operating_thresholds.json").write_text(
        json.dumps(
            {
                "violation_probability": operating_threshold,
                "selection": "maximum F1 on blocked OOF predictions",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "training_manifest.json").write_text(
        json.dumps(
            {
                "training_id": training_id,
                "created_at_utc": created_at_utc,
                "schema_version": artifact_schema_version,
                "schema_sha256": metrics["schema_sha256"],
                "model_variant": training_config.model_variant,
                "regression_target_max": training_config.regression_target_max,
                "regression_mode": training_config.regression_mode,
                "residual_scale": residual_scale,
                "apply_calibrator": apply_calibrator,
                "artifacts": [
                    "sulfur_reg.cbm",
                    "sulfur_reg_lo.cbm",
                    "sulfur_reg_hi.cbm",
                    "sulfur_clf.cbm",
                    "calibrator.pkl",
                    "feature_schema.json",
                    "metrics.json",
                    "operating_thresholds.json",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_model_card(output / "model_card.md", metrics)
    return metrics
