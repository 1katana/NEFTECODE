from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .policy import DecisionPolicy, PolicyConfig
from .service import OrchestratorService
from .trace import JsonlTraceSink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Neftecode final-decision orchestrator"
    )
    parser.add_argument("input", type=Path, help="Path to OrchestratorInput JSON")
    parser.add_argument("--trace", type=Path, help="Optional JSONL trace destination")
    parser.add_argument("--policy", type=Path, help="Optional PolicyConfig JSON")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with args.input.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    policy = None
    if args.policy:
        policy = DecisionPolicy(
            PolicyConfig.model_validate_json(args.policy.read_text(encoding="utf-8"))
        )
    sink = JsonlTraceSink(args.trace) if args.trace else None
    decision = OrchestratorService(policy=policy, trace_sink=sink).decide_payload(
        payload
    )
    print(decision.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
