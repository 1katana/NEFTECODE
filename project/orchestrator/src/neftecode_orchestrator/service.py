from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from .contracts import ExecutionTrace, FinalDecision, OrchestratorInput
from .enums import Decision
from .explanation import ExplanationBuilder
from .policy import DecisionPolicy
from .reason_codes import ReasonCode
from .trace import NullTraceSink, TraceSink


class OrchestratorService:
    def __init__(
        self,
        policy: DecisionPolicy | None = None,
        explanation_builder: ExplanationBuilder | None = None,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self.policy = policy or DecisionPolicy()
        self.explanation_builder = explanation_builder or ExplanationBuilder()
        self.trace_sink = trace_sink or NullTraceSink()

    def decide(self, data: OrchestratorInput) -> FinalDecision:
        started_at = datetime.now(timezone.utc)
        trace_id = str(uuid4())
        outcome = self.policy.decide(data)
        explanation, warnings, current_summary, predicted = (
            self.explanation_builder.build(data, outcome)
        )
        decision = FinalDecision(
            schema_version="1.0.0",
            run_id=data.run_id,
            timestamp=data.process_state.timestamp,
            decision=outcome.decision,
            reason_codes=list(outcome.reason_codes),
            selected_candidate=outcome.selected_candidate,
            current_state_summary=current_summary,
            predicted_result=predicted,
            warnings=warnings,
            explanation=explanation,
            trace_id=trace_id,
        )
        snapshot = data.model_dump(mode="json")
        trace = ExecutionTrace(
            trace_id=trace_id,
            run_id=data.run_id,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            input_digest=self._digest(snapshot),
            component_statuses={
                "quality": data.current_quality.status,
                "reliability": data.current_reliability.status,
                "safety": data.current_safety.status,
                "optimizer": data.optimization.status,
            },
            scenario_count=len(data.scenarios),
            safe_scenario_count=sum(item.constraint_passed for item in data.scenarios),
            input_snapshot=snapshot,
            decision=decision,
        )
        try:
            self.trace_sink.write(trace)
        except Exception as error:  # noqa: BLE001 - trace must not change the decision
            decision.warnings.append(f"TRACE_WRITE_FAILED: {error}")
        return decision

    def decide_payload(self, payload: dict[str, Any]) -> FinalDecision:
        try:
            data = OrchestratorInput.model_validate(payload)
        except ValidationError as error:
            return self._invalid_contract_decision(payload, error)
        return self.decide(data)

    def _invalid_contract_decision(
        self,
        payload: dict[str, Any],
        error: ValidationError,
    ) -> FinalDecision:
        now = datetime.now(timezone.utc)
        trace_id = str(uuid4())
        run_id = payload.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            run_id = f"invalid-{uuid4()}"
        timestamp = self._payload_timestamp(payload) or now
        details = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)
        ]
        decision = FinalDecision(
            schema_version="1.0.0",
            run_id=run_id,
            timestamp=timestamp,
            decision=Decision.REFUSE,
            reason_codes=[ReasonCode.REFUSE_CONTRACT_INVALID.value],
            selected_candidate=None,
            current_state_summary={},
            predicted_result=None,
            warnings=details,
            explanation=(
                "Надёжная рекомендация не сформирована: входные данные не соответствуют "
                "контракту оркестратора."
            ),
            trace_id=trace_id,
        )
        snapshot = self._json_safe(payload)
        trace = ExecutionTrace(
            trace_id=trace_id,
            run_id=run_id,
            started_at=now,
            finished_at=datetime.now(timezone.utc),
            input_digest=self._digest(snapshot),
            component_statuses={},
            scenario_count=0,
            safe_scenario_count=0,
            input_snapshot=snapshot,
            decision=decision,
        )
        try:
            self.trace_sink.write(trace)
        except Exception as trace_error:  # noqa: BLE001 - trace must not change the decision
            decision.warnings.append(f"TRACE_WRITE_FAILED: {trace_error}")
        return decision

    @staticmethod
    def _payload_timestamp(payload: dict[str, Any]) -> datetime | None:
        raw = payload.get("process_state")
        if not isinstance(raw, dict):
            return None
        value = raw.get("timestamp")
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(payload, ensure_ascii=False, default=str))

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
