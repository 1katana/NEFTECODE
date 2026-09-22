"""Regression tests for boundary failures in the optimization pipeline.

All numbers and tag names in this module are unit-test fixtures.
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import pytest
import yaml
from pydantic import ValidationError

from optimization import (
    CandidateAction,
    CandidateGenerator,
    ControlConfig,
    ProcessState,
    QualityAssessment,
    ReliabilityAssessment,
    SafetyLayer,
    SafetyPolicy,
    Optimizer,
    LexicographicRanker,
    ScenarioEvaluation,
    SafetyResult,
)
from optimization.cli import main
from optimization.configuration import load_yaml_mapping


def config():
    return ControlConfig(
        controls={
            "a": {
                "basis": "CONFIRMED_OPERATING",
                "min": 0,
                "max": 10,
                "step": 1,
                "max_delta": 2,
                "unit": "test",
            },
        }
    )


def state(**values):
    return ProcessState(
        source="LIVE",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        values=values or {"a": 5},
    )


class Quality:
    def predict(self, state, candidate):
        return dict(
            product="COMMERCIAL_DIESEL",
            quality_prediction=8,
            prediction_lower=7,
            prediction_upper=9,
            violation_probability=0.05,
            data_confidence="HIGH",
            source="REAL",
        )


class Reliability:
    def evaluate(self, state, candidate):
        return dict(
            reliability_risk="LOW",
            risk_score=0.1,
            data_confidence="HIGH",
            source="REAL",
        )


def subject(**kwargs):
    return Optimizer(
        quality_agent=kwargs.pop("quality_agent", Quality()),
        reliability_agent=kwargs.pop("reliability_agent", Reliability()),
        control_config=kwargs.pop("control_config", config()),
        **kwargs,
    )


@pytest.mark.parametrize(
    "limit,expected,truncated",
    [
        (1, 1, True),
        (2, 2, True),
        (3, 3, True),
        (4, 4, True),
        (5, 5, False),
        (9, 5, False),
    ],
)
def test_search_limit_includes_keep(limit, expected, truncated):
    result = subject(max_candidates=limit).search(state())
    assert result.generated_count == expected
    assert result.search_truncated == truncated
    assert result.best_candidate.candidate.is_keep


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_search_budget(limit):
    with pytest.raises(ValueError):
        CandidateGenerator(config(), max_candidates=limit)


@pytest.mark.parametrize("value", [None, 20])
def test_keep_does_not_bypass_controls(value):
    result = subject(max_candidates=1).search(state(a=value))
    assert result.status == "NO_FEASIBLE_SOLUTION"
    assert result.rejected_candidates[0].quality is None


def test_missing_required_feature_prevents_agent_calls():
    class NeverCalled(Quality):
        def predict(self, state, candidate):
            raise AssertionError("preflight should prevent this call")

    result = subject(
        quality_agent=NeverCalled(),
        safety_policy=SafetyPolicy(required_inputs={"feed"}),
    ).search(state())
    assert not result.agent_failures
    assert len(result.rejected_candidates) == 5
    assert all(
        "MISSING_REQUIRED_INPUT:feed" in item.safety.violations
        for item in result.rejected_candidates
    )


@pytest.mark.parametrize(
    "values,code",
    [
        ({"a": 5}, "MISSING_MODEL_INPUT:feed"),
        ({"a": 5, "feed": 20}, "MODEL_BOUNDS:feed"),
    ],
)
def test_model_bounds_apply_to_unchanged_state_and_keep(values, code):
    result = subject(
        safety_policy=SafetyPolicy(model_bounds={"feed": {"min": 0, "max": 10}})
    ).search(state(**values))
    assert result.status == "NO_FEASIBLE_SOLUTION"
    assert all(code in item.safety.violations for item in result.rejected_candidates)


def test_candidate_model_bounds_allow_only_in_domain_actions():
    result = subject(
        safety_policy=SafetyPolicy(model_bounds={"a": {"min": 4, "max": 5}})
    ).search(state())
    assert len(result.ranked_candidates) == 2
    assert result.rejected_candidates[0].candidate.changes == {"a": 6}


def test_delta_cannot_lie_about_action_size():
    candidate = CandidateAction(candidate_id="bad", changes={"a": 6}, deltas={"a": 0.1})
    result = SafetyLayer(config()).check_inputs(state(), candidate)
    assert "DELTA_MISMATCH:a" in result.violations


@pytest.mark.parametrize(
    "changes",
    [
        {"quality_prediction": float("nan")},
        {"prediction_lower": 10},
        {"quality_prediction": 11},
        {"violation_probability": float("inf")},
    ],
)
def test_invalid_agent_output_fails_closed(changes):
    class Invalid(Quality):
        def predict(self, state, candidate):
            return {**super().predict(state, candidate), **changes}

    result = subject(quality_agent=Invalid()).search(state())
    assert result.status == "NO_FEASIBLE_SOLUTION"
    assert len(result.agent_failures) == 5


def test_agents_cannot_mutate_shared_state_or_candidate():
    class Mutator(Quality):
        def predict(self, state, candidate):
            state.values["a"] = 999
            candidate.changes["unknown"] = 999
            return super().predict(state, candidate)

    class Observer(Reliability):
        def evaluate(self, state, candidate):
            assert state.values["a"] == 5
            assert "unknown" not in candidate.changes
            return super().evaluate(state, candidate)

    original = state()
    result = subject(quality_agent=Mutator(), reliability_agent=Observer()).search(
        original
    )
    assert not result.agent_failures
    assert original.values == {"a": 5}
    assert result.best_candidate.candidate.is_keep


def test_invalid_model_copy_is_revalidated():
    class InvalidCopy(Quality):
        def predict(self, state, candidate):
            return QualityAssessment(**super().predict(state, candidate)).model_copy(
                update={"quality_prediction": float("nan")}
            )

    assert len(subject(quality_agent=InvalidCopy()).search(state()).agent_failures) == 5


def test_economics_only_breaks_equal_risk_ties():
    result = subject(economic_evaluator=lambda s, c: c.changes.get("a", 5) - 5).search(
        state()
    )
    assert result.best_candidate.candidate.changes == {"a": 7}

    class Risky(Quality):
        def predict(self, state, candidate):
            output = super().predict(state, candidate)
            if candidate.changes.get("a") == 6:
                output["violation_probability"] = 0.1
            return output

    result = subject(
        quality_agent=Risky(),
        economic_evaluator=lambda s, c: 1e9 if c.changes.get("a") == 6 else 0,
    ).search(state())
    assert result.best_candidate.candidate.is_keep


def test_invalid_economic_callback_is_audited():
    result = subject(economic_evaluator=lambda s, c: float("nan")).search(state())
    assert result.status == "NO_FEASIBLE_SOLUTION"
    assert all(f.agent == "economic" for f in result.agent_failures)


def test_action_size_is_normalized_by_control_envelope():
    cfg = ControlConfig(
        controls={
            "a": {
                "basis": "CONFIRMED_OPERATING",
                "min": 0,
                "max": 100,
                "step": 10,
                "max_delta": 100,
                "unit": "test-A",
            },
            "b": {
                "basis": "CONFIRMED_OPERATING",
                "min": 0,
                "max": 100,
                "step": 1,
                "max_delta": 1,
                "unit": "test-B",
            },
        }
    )
    q = QualityAssessment(**Quality().predict(None, None))
    r = ReliabilityAssessment(**Reliability().evaluate(None, None))

    def scenario(tag, delta):
        return ScenarioEvaluation(
            candidate=CandidateAction(
                candidate_id=tag, changes={tag: delta}, deltas={tag: delta}
            ),
            quality=q,
            reliability=r,
            safety=SafetyResult(constraint_passed=True),
        )

    ranked = LexicographicRanker(cfg).rank([scenario("b", 1), scenario("a", 10)])
    assert ranked[0].candidate.candidate_id == "a"
    assert ranked[0].score_components["action_size"] == 0.1


def test_hard_guards_cannot_be_disabled():
    with pytest.raises(ValidationError):
        SafetyPolicy(sulfur_limit_mg_kg=11)
    with pytest.raises(ValidationError):
        SafetyPolicy(rejected_reliability_risks=set())


def test_mock_flag_survives_reliability_failure():
    class Mock(Quality):
        is_mock = True

    class Failed(Reliability):
        def evaluate(self, state, candidate):
            raise RuntimeError("test failure")

    result = subject(quality_agent=Mock(), reliability_agent=Failed()).search(state())
    assert result.uses_mock_assessments
    assert all(f.agent == "reliability" for f in result.agent_failures)


def test_mock_rejection_policy():
    class Mock(Quality):
        def predict(self, state, candidate):
            return {**super().predict(state, candidate), "source": "MOCK"}

    result = subject(
        quality_agent=Mock(), safety_policy=SafetyPolicy(reject_mock_assessments=True)
    ).search(state())
    assert result.status == "NO_FEASIBLE_SOLUTION"
    assert all(
        "MOCK_ASSESSMENT" in s.safety.violations for s in result.rejected_candidates
    )


def test_cli_reports_missing_file_without_traceback(capsys):
    assert (
        main(
            [
                "--state",
                "missing.json",
                "--control-config",
                "missing.yaml",
                "--mock-config",
                "missing.yaml",
            ]
        )
        == 2
    )
    assert "Input/output error" in capsys.readouterr().err


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "[]",
        "controls: {}\ncontrols: {}\n",
        "controls:\n  a:\n    min: 0\n    min: 1\n",
    ],
)
def test_config_never_silently_discards_duplicate_keys(tmp_path, raw):
    path = tmp_path / "bad.yaml"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises((ValueError, yaml.YAMLError)):
        load_yaml_mapping(path)


def test_cli_wont_overwrite_input_or_existing_output(tmp_path, capsys):
    root = Path(__file__).parents[1]
    output = tmp_path / "existing.json"
    output.write_text("preserve me", encoding="utf-8")
    assert (
        main(
            [
                "--state",
                str(root / "examples/mock_state.json"),
                "--control-config",
                str(root / "examples/mock_control_config.yaml"),
                "--mock-config",
                str(root / "examples/mock_assessments.yaml"),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert output.read_text(encoding="utf-8") == "preserve me"


def test_sulfur_boundary_and_optional_upper_policy():
    q = QualityAssessment(
        product="COMMERCIAL_DIESEL",
        quality_prediction=10,
        prediction_lower=9,
        prediction_upper=11,
        violation_probability=0.1,
        data_confidence="HIGH",
    )
    r = ReliabilityAssessment(**Reliability().evaluate(None, None))
    keep = CandidateAction(candidate_id="KEEP")
    assert not SafetyLayer(config()).evaluate(state(), keep, q, r).constraint_passed
    assert (
        SafetyLayer(config(), SafetyPolicy(use_prediction_upper=False))
        .evaluate(state(), keep, q, r)
        .constraint_passed
    )


def test_unsafe_candidate_never_reaches_economics():
    calls = []

    class OffSpec(Quality):
        def predict(self, state, candidate):
            return dict(
                product="COMMERCIAL_DIESEL",
                quality_prediction=11,
                prediction_lower=10,
                prediction_upper=12,
                violation_probability=0.8,
                data_confidence="HIGH",
            )

    def economy(state, candidate):
        calls.append(candidate.candidate_id)
        return 1e9

    result = subject(quality_agent=OffSpec(), economic_evaluator=economy).search(
        state()
    )
    assert result.status == "NO_FEASIBLE_SOLUTION"
    assert calls == []


def test_large_combination_space_is_capped():
    cfg = ControlConfig(
        controls={
            f"tag{i}": spec for i, spec in enumerate([config().controls["a"]] * 30)
        }
    )
    report = CandidateGenerator(
        cfg, max_candidates=10, max_changed_controls=30
    ).generate_with_report(state(**{tag: 5 for tag in cfg.controls}))
    assert len(report.candidates) == 10
    assert report.truncated


def test_floating_point_step_is_representable_and_safe():
    cfg = ControlConfig(
        controls={
            "a": {
                "basis": "CONFIRMED_OPERATING",
                "min": 0,
                "max": 1,
                "step": 0.1,
                "max_delta": 0.1,
                "unit": "test",
            }
        }
    )
    result = subject(control_config=cfg).search(state(a=0.2))
    assert not result.rejected_candidates
    assert {c.candidate.changes.get("a", 0.2) for c in result.ranked_candidates} == {
        0.1,
        0.2,
        0.3,
    }


def test_missing_economic_gain_cannot_be_compared_to_real_gain():
    q = QualityAssessment(**Quality().predict(None, None))
    r = ReliabilityAssessment(**Reliability().evaluate(None, None))
    item = ScenarioEvaluation(
        candidate=CandidateAction(candidate_id="KEEP"),
        quality=q,
        reliability=r,
        safety=SafetyResult(constraint_passed=True),
    )
    with pytest.raises(ValueError, match="economic gain"):
        LexicographicRanker().rank(
            [item, item.model_copy(update={"production_gain": 1.0})]
        )


def test_tiny_control_limit_is_not_overridden_by_numeric_tolerance():
    cfg = ControlConfig(
        controls={
            "a": {
                "basis": "CONFIRMED_OPERATING",
                "min": 0,
                "max": 1,
                "step": 1e-20,
                "max_delta": 1e-20,
                "unit": "test",
            }
        }
    )
    candidate = CandidateAction(
        candidate_id="overshoot", changes={"a": 1e-13}, deltas={"a": 1e-13}
    )
    assert (
        "MAX_DELTA:a" in SafetyLayer(cfg).check_inputs(state(a=0), candidate).violations
    )
