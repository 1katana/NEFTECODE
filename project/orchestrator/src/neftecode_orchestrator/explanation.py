from __future__ import annotations

from typing import Any

from .contracts import OrchestratorInput, ScenarioEvaluation
from .enums import ComponentStatus, Decision, ReliabilityRisk
from .policy import PolicyOutcome
from .reason_codes import ReasonCode

REASON_TEXT = {
    ReasonCode.RECOMMEND_TOP_RANKED_SAFE_CANDIDATE.value: (
        "выбран первый безопасный сценарий из ranking оптимизатора"
    ),
    ReasonCode.KEEP_CURRENT_MODE_SAFE.value: "текущий режим прошёл проверку безопасности",
    ReasonCode.KEEP_NO_FEASIBLE_CHANGE.value: "допустимых изменений режима не найдено",
    ReasonCode.KEEP_TOP_CANDIDATE_IS_NO_CHANGE.value: (
        "лучшим вариантом признано сохранение текущего режима"
    ),
    ReasonCode.KEEP_CONFIDENCE_BELOW_RECOMMENDATION.value: (
        "уверенности достаточно для сохранения режима, но недостаточно для изменения"
    ),
    ReasonCode.KEEP_RECOMMENDATION_GUARD.value: (
        "рекомендация изменения заблокирована защитным правилом"
    ),
    ReasonCode.REFUSE_CONTRACT_INVALID.value: "входные данные не соответствуют контракту",
    ReasonCode.REFUSE_REQUIRED_QUALITY_MISSING.value: (
        "агент качества не вернул обязательный прогноз или вероятность нарушения"
    ),
    ReasonCode.REFUSE_REQUIRED_RELIABILITY_MISSING.value: (
        "агент надёжности не смог оценить режим по обязательным данным"
    ),
    ReasonCode.REFUSE_LOW_DATA_CONFIDENCE.value: "доверие к входным данным недостаточно",
    ReasonCode.REFUSE_CURRENT_UNSAFE_NO_FEASIBLE.value: (
        "текущий режим небезопасен, а допустимых альтернатив не найдено"
    ),
    ReasonCode.REFUSE_SCENARIO_INCOMPLETE.value: (
        "выбранный сценарий не содержит обязательной оценки качества"
    ),
    ReasonCode.REFUSE_INCONSISTENT_NO_CHANGE.value: (
        "текущий режим признан небезопасным, но NO_CHANGE попал на первое место ranking"
    ),
    ReasonCode.REFUSE_RECOMMENDATION_GUARD.value: (
        "рекомендация изменения заблокирована защитным правилом"
    ),
}


class ExplanationBuilder:
    def build(
        self,
        data: OrchestratorInput,
        outcome: PolicyOutcome,
    ) -> tuple[str, list[str], dict[str, Any], dict[str, Any] | None]:
        warnings = self._warnings(data)
        current_summary = self._current_summary(data)

        if outcome.decision is Decision.RECOMMEND:
            assert outcome.selected_candidate is not None
            scenario = self._scenario(data, outcome.selected_candidate.candidate_id)
            predicted = self._predicted_result(scenario)
            changes = ", ".join(
                f"{tag}={value:g}"
                for tag, value in outcome.selected_candidate.changes.items()
            )
            if not changes:
                changes = ", ".join(
                    f"{tag}: delta {value:+g}"
                    for tag, value in outcome.selected_candidate.delta.items()
                )
            explanation = (
                f"Рекомендован сценарий {outcome.selected_candidate.candidate_id}: {changes}. "
                f"Прогноз качества — {self._fmt(scenario.quality_prediction)}, "
                f"вероятность нарушения — {self._fmt_probability(scenario.violation_probability)}. "
                "Сценарий прошёл Safety и занимает первое место в ranking оптимизатора."
            )
            return explanation, warnings, current_summary, predicted

        reasons = "; ".join(self._reason_text(code) for code in outcome.reason_codes)
        if outcome.decision is Decision.KEEP:
            explanation = f"Режим оставлен без изменений: {reasons}."
        else:
            explanation = f"Надёжная рекомендация не сформирована: {reasons}."
        return explanation, warnings, current_summary, None

    @staticmethod
    def _scenario(data: OrchestratorInput, candidate_id: str) -> ScenarioEvaluation:
        return next(
            item
            for item in data.scenarios
            if item.candidate.candidate_id == candidate_id
        )

    @staticmethod
    def _predicted_result(scenario: ScenarioEvaluation) -> dict[str, Any]:
        reliability = scenario.reliability_risk
        reliability_value = (
            reliability.value
            if isinstance(reliability, ReliabilityRisk)
            else reliability
        )
        return {
            "quality_prediction": scenario.quality_prediction,
            "grade": scenario.grade,
            "metrics": scenario.metrics.model_dump(mode="json")
            if scenario.metrics
            else None,
            "candidate_horizon_hours": scenario.candidate_horizon_hours,
            "violation_probability": scenario.violation_probability,
            "reliability_risk": reliability_value,
            "reliability_risk_score": scenario.reliability_risk_score,
            "reliability_source": scenario.reliability_source.value,
            "constraint_passed": scenario.constraint_passed,
            "score": scenario.score,
        }

    @staticmethod
    def _current_summary(data: OrchestratorInput) -> dict[str, Any]:
        quality = data.current_quality.data
        reliability = data.current_reliability.data
        safety = data.current_safety.data
        return {
            "quality_prediction": quality.quality_prediction if quality else None,
            "grade": quality.grade if quality else None,
            "metrics": quality.metrics.model_dump(mode="json")
            if quality and quality.metrics
            else None,
            "candidate_horizon_hours": quality.candidate_horizon_hours
            if quality
            else None,
            "violation_probability": quality.violation_probability if quality else None,
            "reliability_risk": reliability.reliability_risk.value
            if reliability and reliability.reliability_risk
            else None,
            "risk_score": reliability.risk_score if reliability else None,
            "constraint_passed": safety.constraint_passed if safety else None,
        }

    @staticmethod
    def _warnings(data: OrchestratorInput) -> list[str]:
        warnings: list[str] = []
        if (
            data.current_quality.status is ComponentStatus.OK
            and data.current_quality.data
        ):
            warnings.extend(data.current_quality.data.warnings)
        elif data.current_quality.message:
            warnings.append(data.current_quality.message)
        if (
            data.current_reliability.status is ComponentStatus.OK
            and data.current_reliability.data
        ):
            warnings.extend(data.current_reliability.data.warnings)
        elif data.current_reliability.message:
            warnings.append(data.current_reliability.message)
        if (
            data.current_safety.status is not ComponentStatus.OK
            and data.current_safety.message
        ):
            warnings.append(data.current_safety.message)
        if (
            data.optimization.status is not ComponentStatus.OK
            and data.optimization.message
        ):
            warnings.append(data.optimization.message)
        elif data.optimization.data:
            warnings.extend(data.optimization.data.warnings)
        return list(dict.fromkeys(warnings))

    @staticmethod
    def _reason_text(code: str) -> str:
        base = code.split(":", maxsplit=1)[0]
        component = code.split(":", maxsplit=1)[1] if ":" in code else None
        if base == ReasonCode.REFUSE_COMPONENT_TIMEOUT.value:
            return f"компонент {component} не ответил вовремя"
        if base == ReasonCode.REFUSE_COMPONENT_FAILURE.value:
            return f"компонент {component} завершился ошибкой"
        return REASON_TEXT.get(base, base)

    @staticmethod
    def _fmt(value: float | None) -> str:
        return "нет данных" if value is None else f"{value:g}"

    @staticmethod
    def _fmt_probability(value: float | None) -> str:
        return "нет данных" if value is None else f"{value:.1%}"
