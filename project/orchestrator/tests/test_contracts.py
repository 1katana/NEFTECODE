from __future__ import annotations

import unittest

from neftecode_orchestrator.contracts import (
    ComponentResult,
    OptimizationResult,
    OrchestratorInput,
    QualityAssessment,
    SafetyResult,
)
from neftecode_orchestrator.enums import ComponentStatus, OptimizationStatus
from neftecode_orchestrator.stubs import make_no_change_input, make_recommend_input
from pydantic import ValidationError


class ContractTests(unittest.TestCase):
    def test_safety_passed_cannot_contain_violations(self) -> None:
        with self.assertRaises(ValidationError):
            SafetyResult(constraint_passed=True, violations=["SULFUR_LIMIT"])

    def test_quality_probability_must_be_between_zero_and_one(self) -> None:
        with self.assertRaises(ValidationError):
            QualityAssessment(
                quality_prediction=8.0,
                violation_probability=1.2,
                data_confidence="HIGH",
            )

    def test_failed_component_cannot_contain_business_data(self) -> None:
        with self.assertRaises(ValidationError):
            ComponentResult[SafetyResult](
                status=ComponentStatus.ERROR,
                data=SafetyResult(constraint_passed=True, violations=[]),
                error_code="REMOTE_ERROR",
            )

    def test_no_feasible_result_cannot_contain_candidates(self) -> None:
        data = make_recommend_input()
        ranked = data.optimization.data.ranked_candidates
        with self.assertRaises(ValidationError):
            OptimizationResult(
                status=OptimizationStatus.NO_FEASIBLE_SOLUTION,
                ranked_candidates=ranked,
                reasons=["ALL_REJECTED"],
            )

    def test_ranked_candidate_must_be_safe(self) -> None:
        data = make_recommend_input()
        payload = data.model_dump(mode="python")
        payload["scenarios"][0]["constraint_passed"] = False
        payload["scenarios"][0]["violations"] = ["SULFUR_LIMIT"]
        with self.assertRaises(ValidationError):
            OrchestratorInput.model_validate(payload)

    def test_candidate_ranks_must_be_contiguous(self) -> None:
        data = make_recommend_input()
        payload = data.model_dump(mode="python")
        payload["optimization"]["data"]["ranked_candidates"][0]["rank"] = 2
        with self.assertRaises(ValidationError):
            OrchestratorInput.model_validate(payload)

    def test_no_change_safety_must_match_current_safety(self) -> None:
        payload = make_no_change_input().model_dump(mode="python")
        payload["current_safety"]["data"] = {
            "constraint_passed": False,
            "violations": ["SULFUR_LIMIT"],
            "rejection_reason": "SULFUR_LIMIT",
        }
        with self.assertRaises(ValidationError):
            OrchestratorInput.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
