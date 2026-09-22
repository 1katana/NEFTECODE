from datetime import datetime, timezone

import pytest
from optimization import CandidateGenerator, ControlConfig, ProcessState
from pydantic import ValidationError


def config() -> ControlConfig:
    return ControlConfig.model_validate(
        {
            "controls": {
                "confirmed_a": {
                    "basis": "CONFIRMED_OPERATING",
                    "min": 0,
                    "max": 10,
                    "step": 2,
                    "max_delta": 2,
                    "unit": "u",
                },
                "confirmed_b": {
                    "basis": "CONFIRMED_OPERATING",
                    "min": 0,
                    "max": 20,
                    "step": 5,
                    "max_delta": 5,
                    "unit": "u",
                },
            }
        }
    )


def state(**values: float) -> ProcessState:
    return ProcessState(
        source="LIVE", timestamp=datetime.now(timezone.utc), values=values
    )


def test_keep_is_always_present_and_unknown_tags_are_not_changed() -> None:
    candidates = CandidateGenerator(config()).generate(
        state(confirmed_a=5, confirmed_b=10, unknown=99)
    )

    assert candidates[0].candidate_id == "KEEP"
    assert candidates[0].changes == {}
    assert all("unknown" not in candidate.changes for candidate in candidates)


def test_configured_horizon_is_copied_to_every_candidate() -> None:
    raw = config().model_dump(by_alias=True)
    raw["candidate_horizon_hours"] = 2.0
    candidates = CandidateGenerator(ControlConfig.model_validate(raw)).generate(
        state(confirmed_a=5, confirmed_b=10)
    )

    assert {candidate.horizon_hours for candidate in candidates} == {2.0}


def test_generated_values_respect_bounds_and_max_delta() -> None:
    candidates = CandidateGenerator(config()).generate(
        state(confirmed_a=1, confirmed_b=20)
    )

    for candidate in candidates:
        for tag, proposed in candidate.changes.items():
            spec = config().controls[tag]
            current = 1 if tag == "confirmed_a" else 20
            assert spec.minimum <= proposed <= spec.maximum
            assert abs(proposed - current) <= spec.max_delta


def test_generator_explores_all_step_multiples_up_to_max_delta() -> None:
    control = ControlConfig.model_validate(
        {
            "controls": {
                "a": {
                    "basis": "CONFIRMED_OPERATING",
                    "min": 0,
                    "max": 10,
                    "step": 1,
                    "max_delta": 3,
                    "unit": "u",
                }
            }
        }
    )
    candidates = CandidateGenerator(control).generate(state(a=5))
    assert [(item.changes.get("a"), item.deltas.get("a")) for item in candidates] == [
        (None, None),
        (4, -1),
        (6, 1),
        (3, -2),
        (7, 2),
        (2, -3),
        (8, 3),
    ]


def test_grid_respects_bounds_and_reports_search_truncation() -> None:
    control = ControlConfig.model_validate(
        {
            "controls": {
                "a": {
                    "basis": "CONFIRMED_OPERATING",
                    "min": 0,
                    "max": 10,
                    "step": 1,
                    "max_delta": 5,
                    "unit": "u",
                }
            }
        }
    )
    report = CandidateGenerator(control, max_candidates=4).generate_with_report(
        state(a=1)
    )
    assert [item.changes.get("a") for item in report.candidates] == [None, 0, 2, 3]
    assert report.truncated


def test_multi_step_combinations_are_generated_without_filling_fake_controls() -> None:
    control = ControlConfig.model_validate(
        {
            "controls": {
                tag: {
                    "basis": "CONFIRMED_OPERATING",
                    "min": 0,
                    "max": 10,
                    "step": 1,
                    "max_delta": 2,
                    "unit": "u",
                }
                for tag in ("a", "b")
            }
        }
    )
    report = CandidateGenerator(control, max_candidates=30).generate_with_report(
        state(a=5, b=5)
    )
    assert len(report.candidates) == 25  # KEEP + 8 single + 16 paired actions
    assert not report.truncated
    assert any(item.changes == {"a": 3, "b": 7} for item in report.candidates)


def test_combinations_are_bounded_and_reproducible() -> None:
    generator = CandidateGenerator(config(), max_changed_controls=2, max_candidates=6)
    process_state = state(confirmed_a=5, confirmed_b=10)

    first = generator.generate(process_state)
    second = generator.generate(process_state)

    assert first == second
    assert len(first) == 6
    assert all(len(candidate.changes) <= 2 for candidate in first)


def test_non_finite_process_values_are_rejected_not_imputed() -> None:
    with pytest.raises(ValidationError):
        state(confirmed_a=float("nan"))


def test_control_range_basis_cannot_be_omitted() -> None:
    raw = config().model_dump(by_alias=True)
    del raw["controls"]["confirmed_a"]["basis"]
    with pytest.raises(ValidationError):
        ControlConfig.model_validate(raw)


def test_state_source_cannot_be_omitted() -> None:
    with pytest.raises(ValidationError):
        ProcessState.model_validate(
            {"timestamp": datetime.now(timezone.utc), "values": {}}
        )
