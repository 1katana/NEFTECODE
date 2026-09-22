from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import RLock

from neftecode_orchestrator.contracts import (
    OptimizationResult,
    ProcessState,
    QualityAssessment,
    ReliabilityAssessment,
    SafetyResult,
)
from neftecode_orchestrator.enums import (
    AssessmentSource,
    DataConfidence,
    InputSource,
    OptimizationStatus,
    QualityProduct,
    ReliabilityRisk,
)
from quality_agent.blending import assess_commercial_blend
from quality_agent.contracts import (
    CandidateAction as QualityCandidateAction,
)
from quality_agent.contracts import (
    ProcessState as QualityProcessState,
)
from quality_agent.runtime import RuntimeConfig, create_shadow_router
from quality_agent.state_adapter import ingest_process_state

from .models import OptimizationProjection


class LocalQualityAdapter:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        *,
        product: QualityProduct = QualityProduct.UNKNOWN,
    ) -> None:
        self.runtime_config = runtime_config
        self.router = create_shadow_router(runtime_config)
        self.product = product
        self._router_lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quality-agent")

    async def evaluate_current(
        self,
        state: ProcessState,
        history: list[ProcessState],
    ) -> QualityAssessment:
        quality_history = [
            QualityProcessState.model_validate(item.model_dump(mode="python")) for item in history
        ]
        quality_state = QualityProcessState.model_validate(state.model_dump(mode="python"))
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            self._executor,
            self._evaluate_sync,
            quality_state,
            quality_history,
        )
        return self._to_contract(result, quality_state)

    def _evaluate_sync(
        self,
        state: QualityProcessState,
        history: list[QualityProcessState],
    ):
        with self._router_lock:
            if history or state.data_quality.get("replace_history") is True:
                self.router.history.clear()
            for historical_state in history:
                ingest_process_state(self.router.history, historical_state)
            return self.router.predict(state)

    def evaluate_candidate_sync(
        self,
        state: ProcessState,
        candidate: QualityCandidateAction,
    ) -> QualityAssessment:
        quality_state = QualityProcessState.model_validate(state.model_dump(mode="python"))
        with self._router_lock:
            result = self.router.predict(
                quality_state,
                candidate,
                ingest_state=False,
            )
        return self._to_contract(result, quality_state, candidate)

    def _to_contract(
        self,
        result,
        state: QualityProcessState,
        candidate: QualityCandidateAction | None = None,
    ) -> QualityAssessment:
        if self.product is QualityProduct.COMMERCIAL_DIESEL:
            result = assess_commercial_blend(result, state, candidate)
        payload = result.model_dump(mode="python")
        payload.update(
            {
                "product": result.product
                if self.product is QualityProduct.COMMERCIAL_DIESEL
                else self.product,
                "source": AssessmentSource.REAL,
                "model_version": self.router.primary.manifest.get("training_id"),
            }
        )
        return QualityAssessment.model_validate(payload)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)


class DemoReliabilityAdapter:
    """Replace with the colleague-owned ReliabilityAgent adapter."""

    async def evaluate_current(self, state: ProcessState) -> ReliabilityAssessment:
        confidence = state.data_confidence
        if isinstance(confidence, float):
            confidence_score = confidence
        else:
            confidence_score = {
                DataConfidence.HIGH: 1.0,
                DataConfidence.MEDIUM: 0.6,
                DataConfidence.LOW: 0.2,
                DataConfidence.UNKNOWN: 0.0,
            }[DataConfidence(confidence)]
        risk_score = round(0.1 + 0.8 * (1.0 - confidence_score), 4)
        if risk_score >= 0.7:
            risk = ReliabilityRisk.HIGH
        elif risk_score >= 0.35:
            risk = ReliabilityRisk.MEDIUM
        else:
            risk = ReliabilityRisk.LOW
        return ReliabilityAssessment(
            reliability_risk=risk,
            risk_score=risk_score,
            data_confidence=state.data_confidence,
            warnings=["DEMO_RELIABILITY_STUB"],
            risk_factors=[] if risk is ReliabilityRisk.LOW else ["LOW_INPUT_CONFIDENCE"],
            source=AssessmentSource.MOCK,
            model_version="demo-reliability-v1",
        )


class DemoSafetyAdapter:
    """Conservative demo adapter; replace with the colleague-owned Safety block."""

    async def evaluate_current(
        self,
        state: ProcessState,
        quality: QualityAssessment | None,
        reliability: ReliabilityAssessment | None,
    ) -> SafetyResult:
        del state
        violations: list[str] = []
        if quality is None or quality.quality_prediction is None:
            violations.append("QUALITY_UNAVAILABLE")
        else:
            if quality.quality_prediction > 10.0:
                violations.append("SULFUR_POINT_LIMIT")
            if quality.violation_probability is not None and quality.violation_probability >= 0.5:
                violations.append("SULFUR_VIOLATION_RISK")
        if reliability is None:
            violations.append("RELIABILITY_UNAVAILABLE")
        elif reliability.reliability_risk is ReliabilityRisk.HIGH:
            violations.append("RELIABILITY_HIGH")
        return SafetyResult(
            constraint_passed=not violations,
            violations=violations,
            rejection_reason=", ".join(violations) if violations else None,
        )


class DemoNoChangeOptimizer:
    """Honest placeholder: it never fabricates a changing candidate."""

    async def optimize(
        self,
        state: ProcessState,
        input_source: InputSource,
        quality: QualityAssessment,
        reliability: ReliabilityAssessment,
    ) -> OptimizationProjection:
        safety = await DemoSafetyAdapter().evaluate_current(state, quality, reliability)
        return OptimizationProjection(
            optimization=OptimizationResult(
                status=OptimizationStatus.NO_FEASIBLE_SOLUTION,
                ranked_candidates=[],
                reasons=["DEMO_OPTIMIZER_NO_CANDIDATES"],
                input_source=input_source,
                uses_mock_assessments=True,
            ),
            scenarios=[],
            current_safety=safety,
        )
