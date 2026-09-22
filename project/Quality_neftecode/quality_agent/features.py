from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FeatureConfig:
    sulfur_limit: float = 10.0
    high_coverage_ratio: float = 0.90
    medium_coverage_ratio: float = 0.75
    minimum_coverage_ratio: float = 0.50
    minimum_history_hours: float = 6.0
    violation_warning_threshold: float = 0.50

    @classmethod
    def from_yaml(cls, path: str | Path) -> FeatureConfig:
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})
