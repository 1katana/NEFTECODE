from __future__ import annotations

import pickle
from pathlib import Path
from typing import Literal

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

CalibrationMethod = Literal["sigmoid", "isotonic"]


class ProbabilityCalibrator:
    """Calibrate classifier probabilities without changing their rank.

    Sigmoid/Platt is the default for the current small number of violations.
    Isotonic remains available only for datasets with enough calibration events.
    """

    def __init__(self, method: CalibrationMethod = "sigmoid") -> None:
        self.method = method
        self.model: LogisticRegression | IsotonicRegression | None = None

    @staticmethod
    def _logit_feature(raw_proba: np.ndarray) -> np.ndarray:
        clipped = np.clip(np.asarray(raw_proba, dtype=float), 1e-6, 1 - 1e-6)
        return np.log(clipped / (1 - clipped)).reshape(-1, 1)

    def fit(self, raw_proba: np.ndarray, y_true: np.ndarray) -> ProbabilityCalibrator:
        raw = np.asarray(raw_proba, dtype=float)
        target = np.asarray(y_true, dtype=int)
        if len(np.unique(target)) < 2:
            raise ValueError("Calibration requires both target classes")
        if self.method == "sigmoid":
            model = LogisticRegression(C=1e6, solver="lbfgs", random_state=42)
            model.fit(self._logit_feature(raw), target)
            self.model = model
        elif self.method == "isotonic":
            model = IsotonicRegression(out_of_bounds="clip")
            model.fit(raw, target)
            self.model = model
        else:
            raise ValueError(f"Unsupported calibration method: {self.method}")
        return self

    def transform(self, raw_proba: np.ndarray) -> np.ndarray:
        raw = np.asarray(raw_proba, dtype=float)
        if self.model is None:
            return raw
        if self.method == "sigmoid":
            assert isinstance(self.model, LogisticRegression)
            return self.model.predict_proba(self._logit_feature(raw))[:, 1]
        assert isinstance(self.model, IsotonicRegression)
        return self.model.predict(raw)

    def save(self, path: str | Path) -> None:
        Path(path).write_bytes(pickle.dumps(self))

    @classmethod
    def load(cls, path: str | Path) -> ProbabilityCalibrator:
        loaded = pickle.loads(Path(path).read_bytes())
        if not isinstance(loaded, cls):
            raise TypeError("Unsupported calibrator artifact")
        return loaded
