from __future__ import annotations

from pathlib import Path

from .agent import QualityAgent
from .contracts import CandidateAction, ProcessState, QualityAssessment
from .features import FeatureConfig


class MultiTargetQualityAgent:
    """Compatibility wrapper; only the agreed sulfur target is implemented."""

    SUPPORTED_TARGETS = frozenset({"mg_sulfur"})

    def __init__(
        self,
        artifacts_root: str | Path,
        targets: list[str] | None = None,
        base_config: FeatureConfig | None = None,
    ):
        self.targets = targets or ["mg_sulfur"]
        unsupported = sorted(set(self.targets) - self.SUPPORTED_TARGETS)
        if unsupported:
            raise ValueError(f"Unsupported quality targets: {unsupported}")
        root = Path(artifacts_root)
        target_dir = root / "mg_sulfur"
        artifacts = target_dir if target_dir.exists() else root
        self.agents = {"mg_sulfur": QualityAgent(artifacts, base_config or FeatureConfig())}

    def predict(
        self,
        state: ProcessState,
        candidate: CandidateAction | None = None,
    ) -> dict[str, QualityAssessment]:
        return {target: self.agents[target].predict(state, candidate) for target in self.targets}
