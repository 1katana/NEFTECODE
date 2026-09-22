"""The dataset adapter is for retrospective contract checks, not ML validation."""

import csv
import io
from zipfile import ZipFile

import pytest
from optimization import (
    ControlConfig,
    Optimizer,
    iter_historical_cases,
)


def dataset_zip(tmp_path, *, rows=None, columns=None, member="split_test_v2.csv"):
    columns = columns or [
        "timestamp",
        "telemetry_timestamp",
        "telemetry_age_min",
        "telemetry_available",
        "telemetry_within_source_range",
        "tele_hyd_t11_current",
        "tele_hyd_p8_current",
        "tele_hyd_t11_lag_30m",
        "previous_lims_mg_sulfur",
        "target_mg_sulfur",
        "target_mg_sulfur_flag_basic_invalid",
        "target_mg_sulfur_flag_robust_outlier",
    ]
    rows = (
        rows
        if rows is not None
        else [
            {
                "timestamp": "2026-05-01 12:00:00",
                "telemetry_timestamp": "2026-05-01 11:50:00",
                "telemetry_age_min": "10",
                "telemetry_available": "True",
                "telemetry_within_source_range": "True",
                "tele_hyd_t11_current": "365",
                "tele_hyd_p8_current": "0.18",
                "tele_hyd_t11_lag_30m": "360",
                "previous_lims_mg_sulfur": "7",
                "target_mg_sulfur": "9",
                "target_mg_sulfur_flag_basic_invalid": "False",
                "target_mg_sulfur_flag_robust_outlier": "True",
            }
        ]
    )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    path = tmp_path / "datasets.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(member, output.getvalue())
    return path


def test_historical_target_and_derived_features_never_enter_agent_state(tmp_path):
    (case,) = iter_historical_cases(dataset_zip(tmp_path))

    assert case.observed_hydro2_sulfur_mg_kg == 9
    assert case.state.values == {
        "tele_hyd_p8_current": 0.18,
        "tele_hyd_t11_current": 365,
    }
    assert case.state.metadata["time_semantics"] == "LIMS_SAMPLE_COLLECTION"
    assert case.state.source == "HISTORICAL"
    assert case.state.metadata["telemetry_age_min"] == 10
    assert case.state.metadata["telemetry_available"] is True
    assert case.state.metadata["telemetry_within_source_range"] is True
    assert case.sulfur_flag_basic_invalid is False
    assert case.sulfur_flag_robust_outlier is True
    assert "target_mg_sulfur" not in case.state.model_dump_json()
    assert "previous_lims_mg_sulfur" not in case.state.model_dump_json()


def test_replay_can_call_optimizer_without_leaking_hydro2_label(tmp_path):
    class QualityMock:
        is_mock = True

        def predict(self, state, candidate):
            assert set(state.values) == {"tele_hyd_p8_current", "tele_hyd_t11_current"}
            assert "target_mg_sulfur" not in state.metadata
            return {
                "product": "COMMERCIAL_DIESEL",
                "quality_prediction": 8,
                "prediction_lower": 7,
                "prediction_upper": 9,
                "violation_probability": 0.05,
                "data_confidence": "HIGH",
                "source": "MOCK",
            }

    class ReliabilityMock:
        is_mock = True

        def evaluate(self, state, candidate):
            return {
                "reliability_risk": "LOW",
                "risk_score": 0.1,
                "data_confidence": "HIGH",
                "source": "MOCK",
            }

    optimizer = Optimizer(
        quality_agent=QualityMock(),
        reliability_agent=ReliabilityMock(),
        control_config=ControlConfig(),
    )
    (case,) = iter_historical_cases(dataset_zip(tmp_path))
    result = optimizer.search(case.state)
    assert result.status == "KEEP"
    assert result.input_source == "HISTORICAL"
    assert result.uses_mock_assessments
    assert case.observed_hydro2_sulfur_mg_kg == 9


def test_adapter_rejects_invalid_split_limit_and_missing_member(tmp_path):
    path = dataset_zip(tmp_path)
    with pytest.raises(ValueError, match="unknown historical split"):
        list(iter_historical_cases(path, split="other"))
    with pytest.raises(ValueError, match="positive integer"):
        list(iter_historical_cases(path, limit=0))
    with pytest.raises(ValueError, match="missing split_val_v2.csv"):
        list(iter_historical_cases(path, split="val"))


def test_adapter_rejects_nonfinite_telemetry(tmp_path):
    path = dataset_zip(
        tmp_path,
        rows=[
            {
                "timestamp": "2026-05-01 12:00:00",
                "telemetry_timestamp": "2026-05-01 11:50:00",
                "telemetry_age_min": "10",
                "telemetry_available": "True",
                "telemetry_within_source_range": "True",
                "tele_hyd_t11_current": "nan",
                "tele_hyd_p8_current": "0.18",
                "tele_hyd_t11_lag_30m": "",
                "previous_lims_mg_sulfur": "",
                "target_mg_sulfur": "",
                "target_mg_sulfur_flag_basic_invalid": "",
                "target_mg_sulfur_flag_robust_outlier": "",
            }
        ],
    )
    with pytest.raises(ValueError, match="non-finite tele_hyd_t11_current"):
        list(iter_historical_cases(path))


def test_adapter_rejects_future_telemetry(tmp_path):
    path = dataset_zip(
        tmp_path,
        rows=[
            {
                "timestamp": "2026-05-01 12:00:00",
                "telemetry_timestamp": "2026-05-01 12:10:00",
                "telemetry_age_min": "0",
                "telemetry_available": "True",
                "telemetry_within_source_range": "True",
                "tele_hyd_t11_current": "365",
                "tele_hyd_p8_current": "0.18",
                "tele_hyd_t11_lag_30m": "",
                "previous_lims_mg_sulfur": "",
                "target_mg_sulfur": "",
                "target_mg_sulfur_flag_basic_invalid": "",
                "target_mg_sulfur_flag_robust_outlier": "",
            }
        ],
    )
    with pytest.raises(ValueError, match="future telemetry"):
        list(iter_historical_cases(path))


def test_explicitly_unavailable_telemetry_is_rejected_before_agent_calls(tmp_path):
    rows = [
        {
            "timestamp": "2026-05-01 12:00:00",
            "telemetry_timestamp": "",
            "telemetry_age_min": "",
            "telemetry_available": "False",
            "telemetry_within_source_range": "",
            "tele_hyd_t11_current": "",
            "tele_hyd_p8_current": "",
            "tele_hyd_t11_lag_30m": "",
            "previous_lims_mg_sulfur": "",
            "target_mg_sulfur": "",
            "target_mg_sulfur_flag_basic_invalid": "",
            "target_mg_sulfur_flag_robust_outlier": "",
        }
    ]
    (case,) = iter_historical_cases(dataset_zip(tmp_path, rows=rows))

    class NeverCalled:
        def predict(self, state, candidate):
            raise AssertionError("quality agent should not be called")

        def evaluate(self, state, candidate):
            raise AssertionError("reliability agent should not be called")

    result = Optimizer(
        quality_agent=NeverCalled(),
        reliability_agent=NeverCalled(),
        control_config=ControlConfig(),
    ).search(case.state)
    assert result.status == "NO_FEASIBLE_SOLUTION"
    assert result.rejected_candidates[0].safety.violations == ["TELEMETRY_UNAVAILABLE"]
    assert not result.agent_failures
