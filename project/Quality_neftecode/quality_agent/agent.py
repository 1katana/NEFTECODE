from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from catboost import CatBoostClassifier, CatBoostRegressor

from .calibrate import ProbabilityCalibrator
from .confidence import compute_data_confidence
from .contracts import CandidateAction, DataConfidence, ProcessState, QualityAssessment
from .counterfactual import CandidateEffectConfig, apply_candidate_effect
from .feature_pipeline import FeatureSchema, InMemoryHistoryProvider, OnlineFeaturePipeline
from .features import FeatureConfig
from .state_adapter import ingest_process_state


class ArtifactError(RuntimeError):
    pass


class QualityAgent:
    def __init__(
        self,
        artifacts_dir: str | Path,
        config: FeatureConfig | None = None,
        history: InMemoryHistoryProvider | None = None,
        candidate_effect_config: CandidateEffectConfig | None = None,
    ):
        self.config = config or FeatureConfig()
        self.artifacts_dir = Path(artifacts_dir)
        schema_path = self.artifacts_dir / "feature_schema.json"
        if not schema_path.exists():
            raise ArtifactError(f"Missing artifact: {schema_path}")
        self.manifest = self._validate_manifest(schema_path)
        self.regression_mode = str(self.manifest.get("regression_mode", "direct"))
        if self.regression_mode not in {"direct", "pak_residual"}:
            raise ArtifactError(f"Unsupported regression mode: {self.regression_mode!r}")
        self.residual_scale = float(self.manifest.get("residual_scale", 1.0))
        if not 0.0 <= self.residual_scale <= 1.0:
            raise ArtifactError("Residual scale must be in [0, 1]")
        self.schema = FeatureSchema.load(schema_path)
        self.history = history or InMemoryHistoryProvider()
        self.feature_pipeline = OnlineFeaturePipeline(self.schema, self.history)
        self.candidate_effect_config = candidate_effect_config or CandidateEffectConfig()

        self.reg = self._load_regressor("sulfur_reg.cbm")
        self.clf = self._load_classifier("sulfur_clf.cbm")
        self.reg_lo = self._load_optional_regressor("sulfur_reg_lo.cbm")
        self.reg_hi = self._load_optional_regressor("sulfur_reg_hi.cbm")
        apply_calibrator = bool(self.manifest.get("apply_calibrator", True))
        self.calibrator = (
            ProbabilityCalibrator.load(self.artifacts_dir / "calibrator.pkl")
            if apply_calibrator and (self.artifacts_dir / "calibrator.pkl").exists()
            else None
        )
        self.violation_warning_threshold = self._load_operating_threshold()

    def _validate_manifest(self, schema_path: Path) -> dict:
        manifest_path = self.artifacts_dir / "training_manifest.json"
        if not manifest_path.exists():
            raise ArtifactError(f"Missing artifact: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual_hash = hashlib.sha256(schema_path.read_bytes()).hexdigest()
        if manifest.get("schema_sha256") != actual_hash:
            raise ArtifactError("feature_schema.json hash does not match training_manifest.json")
        missing = [
            name
            for name in manifest.get("artifacts", [])
            if not (self.artifacts_dir / name).exists()
        ]
        if missing:
            raise ArtifactError(f"Incomplete model bundle: {missing}")
        return manifest

    def _load_operating_threshold(self) -> float:
        path = self.artifacts_dir / "operating_thresholds.json"
        if not path.exists():
            return self.config.violation_warning_threshold
        payload = json.loads(path.read_text(encoding="utf-8"))
        threshold = float(payload["violation_probability"])
        if not 0.0 <= threshold <= 1.0:
            raise ArtifactError("Operating probability threshold must be in [0, 1]")
        return threshold

    def _required(self, name: str) -> Path:
        path = self.artifacts_dir / name
        if not path.exists():
            raise ArtifactError(f"Missing artifact: {path}")
        return path

    def _load_regressor(self, name: str) -> CatBoostRegressor:
        model = CatBoostRegressor()
        model.load_model(str(self._required(name)))
        return model

    def _load_classifier(self, name: str) -> CatBoostClassifier:
        model = CatBoostClassifier()
        model.load_model(str(self._required(name)))
        return model

    def _load_optional_regressor(self, name: str) -> CatBoostRegressor | None:
        path = self.artifacts_dir / name
        if not path.exists():
            return None
        model = CatBoostRegressor()
        model.load_model(str(path))
        return model

    @staticmethod
    def _insufficient(warnings: list[str]) -> QualityAssessment:
        return QualityAssessment(
            quality_prediction=None,
            prediction_lower=None,
            prediction_upper=None,
            violation_probability=None,
            data_confidence=DataConfidence.UNKNOWN,
            warnings=sorted(set(warnings)),
        )

    def predict(
        self,
        state: ProcessState,
        candidate: CandidateAction | None = None,
    ) -> QualityAssessment:
        adapter_warnings = list(ingest_process_state(self.history, state))
        return self.predict_from_history(state, candidate, adapter_warnings)

    def predict_from_history(
        self,
        state: ProcessState,
        candidate: CandidateAction | None = None,
        adapter_warnings: list[str] | tuple[str, ...] = (),
    ) -> QualityAssessment:
        """Predict after the caller has already appended the state to shared history."""
        adapter_warnings = list(adapter_warnings)
        vector = self.feature_pipeline.build(state.timestamp)

        confidence = compute_data_confidence(state, vector.diagnostics, self.config)
        if confidence is DataConfidence.UNKNOWN:
            warnings = [*adapter_warnings, "INSUFFICIENT_INPUT"]
            if not vector.diagnostics.has_complete_history:
                warnings.append("INSUFFICIENT_HISTORY")
            if vector.diagnostics.missing_sources:
                warnings.extend(
                    f"MISSING_SOURCE:{source}" for source in vector.diagnostics.missing_sources
                )
            insufficient = self._insufficient(warnings)
            if candidate is not None and not candidate.is_no_change:
                return apply_candidate_effect(
                    insufficient,
                    state,
                    candidate,
                    self.candidate_effect_config,
                )
            return insufficient

        columns = list(self.schema.baseline_feature_columns)
        features = vector.as_frame(columns)
        pak_baseline = None
        if self.regression_mode == "pak_residual":
            pak_baseline = float(features["pak_mg_sulfur_value__current"].iloc[0])
            if not np.isfinite(pak_baseline):
                insufficient = self._insufficient(
                    [*adapter_warnings, "PAK_REQUIRED_FOR_RESIDUAL_MODEL"]
                )
                if candidate is not None and not candidate.is_no_change:
                    return apply_candidate_effect(
                        insufficient,
                        state,
                        candidate,
                        self.candidate_effect_config,
                    )
                return insufficient
        prediction = float(self.reg.predict(features)[0])
        if pak_baseline is not None:
            prediction = pak_baseline + self.residual_scale * prediction
        raw_probability = float(self.clf.predict_proba(features)[0, 1])
        probability = (
            float(self.calibrator.transform(np.asarray([raw_probability]))[0])
            if self.calibrator
            else raw_probability
        )

        lower = upper = None
        if self.reg_lo is not None and self.reg_hi is not None:
            lower = float(self.reg_lo.predict(features)[0])
            upper = float(self.reg_hi.predict(features)[0])
            if pak_baseline is not None:
                lower = pak_baseline + self.residual_scale * lower
                upper = pak_baseline + self.residual_scale * upper
            lower, prediction, upper = sorted((lower, prediction, upper))

        warnings = list(adapter_warnings)
        if confidence is DataConfidence.LOW:
            warnings.append("LOW_DATA_CONFIDENCE")
        if probability >= self.violation_warning_threshold:
            warnings.append("HIGH_VIOLATION_PROBABILITY")

        assessment = QualityAssessment(
            quality_prediction=round(prediction, 3),
            prediction_lower=None if lower is None else round(lower, 3),
            prediction_upper=None if upper is None else round(upper, 3),
            violation_probability=round(probability, 4),
            data_confidence=confidence,
            warnings=sorted(set(warnings)),
        )
        if candidate is not None and not candidate.is_no_change:
            return apply_candidate_effect(
                assessment,
                state,
                candidate,
                self.candidate_effect_config,
            )
        return assessment
