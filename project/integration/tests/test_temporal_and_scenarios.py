from __future__ import annotations

from datetime import datetime

from neftecode_orchestrator.contracts import ProcessState

from neftecode_integration.app import DEFAULT_DEMO_REQUEST, DEFAULT_SCENARIOS
from neftecode_integration.scenarios import ScenarioCatalog
from neftecode_integration.temporal import hide_future_lims


def test_lims_is_hidden_until_four_hours_after_sample() -> None:
    early = ProcessState(
        timestamp="2026-09-20T13:59:59Z",
        quality={
            "mg_sulfur": {
                "value": 7.0,
                "source": "lims",
                "sample_timestamp": "2026-09-20T10:00:00Z",
            }
        },
        telemetry={},
        data_quality={},
        data_confidence="HIGH",
    )
    available = early.model_copy(
        update={"timestamp": datetime.fromisoformat("2026-09-20T14:00:00+00:00")}
    )

    hidden = hide_future_lims(early)
    visible = hide_future_lims(available)

    assert "mg_sulfur" not in hidden.quality
    assert hidden.data_quality["not_yet_available"] == ["lims:mg_sulfur"]
    assert "mg_sulfur" in visible.quality


def test_catalog_contains_all_editable_scenarios() -> None:
    catalog = ScenarioCatalog(DEFAULT_SCENARIOS, DEFAULT_DEMO_REQUEST)
    expected = {
        "feed_sulfur_increase",
        "summer_product",
        "winter_product",
        "q21_outlier_307",
        "stale_pak",
        "startup_shutdown",
        "insufficient_data",
        "impossible_quality_passport",
        "blending_vs_additive",
    }

    assert set(catalog.scenarios) == expected
    assert catalog.build("insufficient_data").history == []
    assert catalog.build("winter_product").process_state.quality["blending"]["grade"] == ("WINTER")
    feed = catalog.build("feed_sulfur_increase")
    assert feed.process_state.quality["mg_sulfur"] == 12.2
    assert [item.quality["mg_sulfur"] for item in feed.history[-3:]] == [12.0, 12.1, 12.2]
