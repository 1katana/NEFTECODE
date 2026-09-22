from __future__ import annotations

import pandas as pd
from neftecode_orchestrator.enums import InputSource

from neftecode_integration.data_upload import HISTORY_POINTS, evaluation_request_from_processed


def test_processed_table_is_adapted_to_a_historical_evaluation_window() -> None:
    timestamps = pd.date_range("2026-09-22T08:00:00Z", periods=40, freq="10min")
    final = pd.DataFrame(
        {
            "timestamp": timestamps,
            "avt_t1": range(40),
            "hyd_t6": [360.0] * 40,
            "hyd_f9": [218.0] * 40,
            "hyd_p13": [3.9] * 40,
            "24_2000_mg_sulfur_value": [8.0] * 40,
            "24_2000_mg_sulfur_src": ["pak"] * 40,
        }
    )

    request = evaluation_request_from_processed(final, run_id="upload-contract-test")

    assert request.input_source is InputSource.HISTORICAL
    assert request.run_id == "upload-contract-test"
    assert len(request.history) == HISTORY_POINTS
    assert request.process_state.timestamp.isoformat() == "2026-09-22T14:30:00+00:00"
    assert request.process_state.telemetry["hyd_t6"] == 360.0
    assert request.process_state.current_controls == {
        "hyd_t6": 360.0,
        "hyd_f9": 218.0,
        "hyd_p13": 3.9,
    }
    assert request.process_state.quality["24_2000_mg_sulfur"] == {
        "value": 8.0,
        "source": "pak",
    }
