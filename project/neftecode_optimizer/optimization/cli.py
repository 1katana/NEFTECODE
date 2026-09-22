"""Command-line entry point for an end-to-end mock run."""

from __future__ import annotations

import argparse
import sys
import yaml
from pathlib import Path
from typing import Sequence

from .mock_agents import (
    MockQualityAgent,
    MockReliabilityAgent,
    load_mock_agents_config,
)
from .models import ProcessState
from .optimizer import Optimizer
from .safety import load_safety_policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the optimization pipeline with explicitly marked mocks."
    )
    parser.add_argument("--state", type=Path, required=True, help="ProcessState JSON")
    parser.add_argument(
        "--control-config", type=Path, required=True, help="Confirmed CONTROL YAML"
    )
    parser.add_argument(
        "--mock-config", type=Path, required=True, help="Mock assessments YAML"
    )
    parser.add_argument("--output", type=Path, help="Optional result JSON path")
    parser.add_argument("--max-candidates", type=int, default=100)
    parser.add_argument("--max-changed-controls", type=int, default=2)
    parser.add_argument("--safety-policy", type=Path, help="SafetyPolicy YAML")
    return parser


def run(args: argparse.Namespace) -> str:
    state = ProcessState.model_validate_json(args.state.read_text(encoding="utf-8"))
    mocks = load_mock_agents_config(args.mock_config)
    optimizer = Optimizer(
        quality_agent=MockQualityAgent(mocks.quality),
        reliability_agent=MockReliabilityAgent(mocks.reliability),
        control_config=args.control_config,
        max_candidates=args.max_candidates,
        max_changed_controls=args.max_changed_controls,
        safety_policy=(
            load_safety_policy(args.safety_policy)
            if getattr(args, "safety_policy", None)
            else None
        ),
    )
    result = optimizer.search(state)
    payload = result.model_dump_json(indent=2)
    if args.output:
        # Refuse to overwrite an input or a previous result.
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload + "\n")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(run(args))
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"Input/output error: {error}", file=sys.stderr)
        return 2
    return 0
