from __future__ import annotations

import json
from pathlib import Path

from neftecode_orchestrator.contracts import (
    CandidateAction,
    ExecutionTrace,
    FinalDecision,
    OptimizationResult,
    OrchestratorInput,
    ProcessState,
    QualityAssessment,
    ReliabilityAssessment,
    SafetyResult,
    ScenarioEvaluation,
)
from neftecode_orchestrator.stubs import (
    make_keep_input,
    make_low_confidence_input,
    make_medium_confidence_input,
    make_missing_quality_input,
    make_no_change_input,
    make_quality_timeout_input,
    make_recommend_input,
    make_refuse_input,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "process-state.schema.json": ProcessState,
    "candidate-action.schema.json": CandidateAction,
    "quality-assessment.schema.json": QualityAssessment,
    "reliability-assessment.schema.json": ReliabilityAssessment,
    "safety-result.schema.json": SafetyResult,
    "scenario-evaluation.schema.json": ScenarioEvaluation,
    "optimization-result.schema.json": OptimizationResult,
    "orchestrator-input.schema.json": OrchestratorInput,
    "final-decision.schema.json": FinalDecision,
    "execution-trace.schema.json": ExecutionTrace,
}
EXAMPLES = {
    "recommend.json": make_recommend_input(),
    "keep.json": make_keep_input(),
    "refuse.json": make_refuse_input(),
    "keep-ranked-no-change.json": make_no_change_input(),
    "keep-medium-confidence.json": make_medium_confidence_input(),
    "refuse-low-confidence.json": make_low_confidence_input(),
    "refuse-missing-quality.json": make_missing_quality_input(),
    "refuse-quality-timeout.json": make_quality_timeout_input(),
}


def main() -> None:
    schema_dir = ROOT / "schemas"
    example_dir = ROOT / "examples"
    schema_dir.mkdir(parents=True, exist_ok=True)
    example_dir.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMAS.items():
        (schema_dir / filename).write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    for filename, value in EXAMPLES.items():
        (example_dir / filename).write_text(
            value.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
