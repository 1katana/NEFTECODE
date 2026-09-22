from __future__ import annotations

from .contracts import DataConfidence, ProcessState
from .feature_pipeline import FeatureDiagnostics
from .features import FeatureConfig

_RANK = {
    DataConfidence.UNKNOWN: 0,
    DataConfidence.LOW: 1,
    DataConfidence.MEDIUM: 2,
    DataConfidence.HIGH: 3,
}


def _upstream_confidence(value: DataConfidence | float) -> DataConfidence:
    if isinstance(value, DataConfidence):
        return value
    if value >= 0.90:
        return DataConfidence.HIGH
    if value >= 0.75:
        return DataConfidence.MEDIUM
    if value > 0:
        return DataConfidence.LOW
    return DataConfidence.UNKNOWN


def _feature_confidence(
    diagnostics: FeatureDiagnostics,
    config: FeatureConfig,
) -> DataConfidence:
    if diagnostics.missing_sources or diagnostics.coverage_ratio < config.minimum_coverage_ratio:
        return DataConfidence.UNKNOWN
    if not diagnostics.source_history_hours or any(
        hours < config.minimum_history_hours for hours in diagnostics.source_history_hours.values()
    ):
        return DataConfidence.UNKNOWN
    if diagnostics.coverage_ratio >= config.high_coverage_ratio:
        return DataConfidence.HIGH
    if diagnostics.coverage_ratio >= config.medium_coverage_ratio:
        return DataConfidence.MEDIUM
    return DataConfidence.LOW


def compute_data_confidence(
    state: ProcessState,
    diagnostics: FeatureDiagnostics,
    config: FeatureConfig | None = None,
) -> DataConfidence:
    config = config or FeatureConfig()
    upstream = _upstream_confidence(state.data_confidence)
    feature_level = _feature_confidence(diagnostics, config)
    return min((upstream, feature_level), key=lambda item: _RANK[item])
