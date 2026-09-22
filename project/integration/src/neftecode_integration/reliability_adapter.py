from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from neftecode_orchestrator.contracts import ProcessState, ReliabilityAssessment
from neftecode_orchestrator.enums import AssessmentSource, DataConfidence, ReliabilityRisk
from reliability_agent import ReliabilityAgent
from reliability_agent.agent import canonical_tag
from reliability_agent.config import RAW_FEATURES


class LocalReliabilityAdapter:
    """Translate the shared state and candidate into the local regime assessor."""

    def __init__(self, policy: Path) -> None:
        self.agent = ReliabilityAgent(policy=policy)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reliability-agent")

    @staticmethod
    def _supported_tag(tag: str) -> bool:
        try:
            return canonical_tag(tag) in RAW_FEATURES
        except ValueError:
            return False

    @classmethod
    def _state(cls, state: ProcessState) -> dict[str, Any]:
        telemetry = {
            tag: value for tag, value in state.telemetry.items() if cls._supported_tag(tag)
        }
        data_quality: dict[str, Any] = {}
        for tag, value in state.data_quality.items():
            if isinstance(value, dict) and cls._supported_tag(tag):
                data_quality[tag] = {
                    key: item
                    for key, item in value.items()
                    if key in {"flag_missing", "flag_stale", "flag_outlier", "age_min", "flatline_min"}
                }
            elif tag.endswith(("_flag_missing", "_flag_stale", "_flag_outlier")):
                stem = tag.rsplit("_flag_", 1)[0]
                if cls._supported_tag(stem):
                    data_quality[tag] = value
        for list_name, field, field_value in (
            ("missing", "flag_missing", True),
            ("not_yet_available", "flag_missing", True),
            ("stale", "flag_stale", True),
            ("outlier", "flag_outlier", True),
        ):
            marked = state.data_quality.get(list_name, [])
            if isinstance(marked, list):
                for tag in marked:
                    if isinstance(tag, str) and cls._supported_tag(tag):
                        data_quality.setdefault(tag, {})[field] = field_value
        return {
            "timestamp": state.timestamp.isoformat(),
            "telemetry": telemetry,
            "data_quality": data_quality,
        }

    @staticmethod
    def _assessment(result: dict[str, Any], *, candidate: bool = False) -> ReliabilityAssessment:
        risk = ReliabilityRisk(result["reliability_risk"])
        return ReliabilityAssessment(
            reliability_risk=risk,
            risk_score=result["risk_score"],
            data_confidence=DataConfidence(result["data_confidence"]),
            warnings=list(result["warnings"]),
            risk_factors=list(result["risk_factors"]),
            partial_risk_score=result["partial_risk_score"],
            candidate_controls_supported=result["candidate_controls_supported"],
            technology_limits_configured=result["technology_limits_configured"],
            assets=dict(result["assets"]),
            observation_issues=dict(result["observation_issues"]),
            score_meaning=result["score_meaning"],
            source=AssessmentSource.UNKNOWN if candidate else AssessmentSource.REAL,
            model_version=result["model_version"],
        )

    @classmethod
    def _with_upstream_quality(
        cls, assessment: ReliabilityAssessment, state: ProcessState
    ) -> ReliabilityAssessment:
        warnings = list(assessment.warnings)
        flatline = state.data_quality.get("flatline", [])
        if isinstance(flatline, list):
            warnings.extend(
                f"UPSTREAM_FLATLINE_DURATION_UNKNOWN:{tag}"
                for tag in flatline
                if isinstance(tag, str) and cls._supported_tag(tag)
            )
        if state.data_quality.get("telemetry_available") is False:
            warnings.append("UPSTREAM_TELEMETRY_UNAVAILABLE")
        if len(warnings) == len(assessment.warnings):
            return assessment
        return assessment.model_copy(
            update={
                "data_confidence": DataConfidence.LOW,
                "warnings": list(dict.fromkeys(warnings)),
            }
        )

    async def evaluate_current(self, state: ProcessState) -> ReliabilityAssessment:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(self._executor, self.agent.assess, self._state(state))
        return self._with_upstream_quality(self._assessment(result), state)

    def evaluate_candidate_sync(
        self, state: ProcessState, candidate_id: str, changes: dict[str, float]
    ) -> ReliabilityAssessment:
        unsupported = [tag for tag in changes if not self._supported_tag(tag)]
        missing = [tag for tag in changes if self._supported_tag(tag) and state.telemetry.get(tag) is None]
        if unsupported or missing:
            return ReliabilityAssessment(
                reliability_risk=ReliabilityRisk.UNKNOWN,
                risk_score=None,
                data_confidence=DataConfidence.LOW,
                warnings=[
                    *(f"UNSUPPORTED_RELIABILITY_CANDIDATE_TAG:{tag}" for tag in unsupported),
                    *(f"CANDIDATE_SOURCE_SIGNAL_MISSING:{tag}" for tag in missing),
                    "CANDIDATE_IS_STATIC_PROXY_NOT_CAUSAL_RESPONSE",
                ],
                candidate_controls_supported=False,
                source=AssessmentSource.UNKNOWN,
                model_version=self.agent.artifact["version"],
            )
        result = self.agent.assess(
            self._state(state),
            {"candidate_id": candidate_id, "mode": "absolute", "changes": changes},
        )
        return self._with_upstream_quality(self._assessment(result, candidate=True), state)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def metadata(self) -> dict[str, Any]:
        return {
            "model_version": self.agent.artifact["version"],
            "technology_limits_configured": bool(self.agent.policy["technology_bounds"]),
            "confirmed_controls": len(self.agent.policy["controls"]),
            "assessment_meaning": "historical_regime_risk_proxy",
        }
