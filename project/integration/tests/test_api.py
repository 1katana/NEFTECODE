from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from neftecode_orchestrator.stubs import make_keep_input

from neftecode_integration.adapters import LocalQualityAdapter
from neftecode_integration.app import DEFAULT_CONFIG, create_app
from neftecode_integration.settings import IntegrationSettings


@pytest.fixture(scope="module")
def api_app(tmp_path_factory: pytest.TempPathFactory):
    temporary = tmp_path_factory.mktemp("integration-api")
    settings = replace(
        IntegrationSettings.from_yaml(DEFAULT_CONFIG),
        trace_path=temporary / "trace.jsonl",
        quality_shadow_log_path=temporary / "shadow.jsonl",
    )
    return create_app(settings=settings)


@pytest.fixture(scope="module")
def client(api_app):
    with TestClient(api_app) as test_client:
        yield test_client


def _insufficient_payload() -> dict:
    return {
        "run_id": "api-insufficient-001",
        "process_state": {
            "timestamp": "2026-09-19T10:00:00Z",
            "quality": {},
            "telemetry": {"hyd_t6": None},
            "data_quality": {
                "missing": ["pak_mg_sulfur", "avt"],
                "stale": [],
                "flatline": [],
                "outlier": [],
            },
            "data_confidence": "UNKNOWN",
            "current_controls": {},
        },
        "history": [],
    }


def test_health_discloses_real_adapter_modes(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY_FOR_SHADOW_WITH_BLOCKERS"
    assert body["runtime"]["status"] == "READY_FOR_SHADOW"
    assert body["integration"]["adapter_modes"]["quality"] == (
        "real_h_plus_c_shadow_with_linear_blending"
    )
    assert body["integration"]["adapter_modes"]["reliability"] == (
        "real_regime_proxy_candidate_static"
    )
    assert body["integration"]["adapter_modes"]["optimization"] == ("local_optimizer_fail_closed")
    assert body["integration"]["optimizer"]["configured_controls"] == 6
    assert body["integration"]["optimizer"]["quality_product"] == "COMMERCIAL_DIESEL"
    assert body["integration"]["reliability"]["model_version"] == "1.0.0"
    assert body["integration"]["reliability"]["technology_limits_configured"] is False
    assert "NO_CONFIRMED_CONTROL_ENVELOPES" in body["integration"]["production_blockers"]
    assert (
        "RELIABILITY_CANDIDATE_CAUSAL_MODEL_NOT_READY" in body["integration"]["production_blockers"]
    )
    assert (
        "RELIABILITY_TECHNOLOGY_LIMITS_NOT_CONFIGURED" in body["integration"]["production_blockers"]
    )


def test_evaluate_is_fail_closed_and_run_can_be_retrieved(client: TestClient) -> None:
    response = client.post("/api/v1/evaluate", json=_insufficient_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["decision"] == "REFUSE"
    assert body["assembled_input"]["current_quality"]["status"] == "OK"
    assert body["assembled_input"]["current_quality"]["data"]["quality_prediction"] is None
    reliability = body["assembled_input"]["current_reliability"]
    assert reliability["status"] == "OK"
    assert reliability["data"]["source"] == "REAL"
    assert reliability["data"]["reliability_risk"] == "UNKNOWN"
    assert reliability["data"]["risk_score"] is None
    assert "ASSESSMENT_INCOMPLETE_NOT_LOW_RISK" in reliability["data"]["warnings"]

    stored = client.get("/api/v1/runs/api-insufficient-001")
    assert stored.status_code == 200
    assert stored.json()["decision"]["trace_id"] == body["decision"]["trace_id"]


def test_evaluate_exposes_real_reliability_score_and_asset_evidence(client: TestClient) -> None:
    sample_path = DEFAULT_CONFIG.parent.parent / "reliability_agent" / "examples" / "state.json"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    response = client.post(
        "/api/v1/evaluate",
        json={
            "run_id": "api-reliability-real-001",
            "process_state": {
                "timestamp": sample["timestamp"],
                "quality": {},
                "telemetry": sample["telemetry"],
                "data_quality": sample["data_quality"],
                "data_confidence": "HIGH",
            },
        },
    )

    assert response.status_code == 200
    reliability = response.json()["assembled_input"]["current_reliability"]
    assert reliability["status"] == "OK"
    assert reliability["data"]["source"] == "REAL"
    assert reliability["data"]["risk_score"] is not None
    assert reliability["data"]["assets"]["hyd_regime"]["status"] == "assessed"


def test_historical_case_withholds_lims_and_refuses_missing_blend(client: TestClient) -> None:
    examples = DEFAULT_CONFIG.parent / "examples"
    request = json.loads((examples / "historical_20260515_1000.json").read_text(encoding="utf-8"))
    evidence = json.loads(
        (examples / "historical_20260515_1000_evidence.json").read_text(encoding="utf-8")
    )

    assert request["input_source"] == "HISTORICAL"
    assert len(request["history"]) == 36
    assert request["process_state"]["quality"]["mg_sulfur"] == pytest.approx(10.364849)
    assert evidence["reference_lims"]["sulfur_mg_kg"] == pytest.approx(11.9)
    assert all(
        "blending" not in state["quality"]
        for state in [*request["history"], request["process_state"]]
    )
    assert all(
        "lims" not in state["quality"] for state in [*request["history"], request["process_state"]]
    )

    response = client.post("/api/v1/evaluate", json=request)
    assert response.status_code == 200
    result = response.json()
    assert result["decision"]["decision"] == "REFUSE"
    quality = result["assembled_input"]["current_quality"]["data"]
    reliability = result["assembled_input"]["current_reliability"]["data"]
    assert "BLENDING_PLAN_MISSING" in quality["warnings"]
    assert reliability["risk_score"] is not None
    assert all(asset["status"] == "assessed" for asset in reliability["assets"].values())


def test_example_routes_keep_assumed_blend_separate_from_history(client: TestClient) -> None:
    listing = client.get("/api/v1/examples")
    assert listing.status_code == 200
    assert {item["example_id"] for item in listing.json()} == {
        "historical_20260515_1000",
        "illustrative_blend_20260515_1200",
    }
    historical = client.get("/api/v1/examples/historical_20260515_1000")
    illustrative = client.get("/api/v1/examples/illustrative_blend_20260515_1200")
    assert historical.json()["input_source"] == "HISTORICAL"
    assert "blending" not in historical.json()["process_state"]["quality"]
    assert illustrative.json()["input_source"] == "SYNTHETIC"
    assert illustrative.json()["process_state"]["quality"]["blending"]["components"][0][
        "share_pct"
    ] == 80
    response = client.post("/api/v1/examples/illustrative_blend_20260515_1200/evaluate")
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["decision"] == "KEEP"
    assert body["assembled_input"]["optimization"]["data"]["input_source"] == "SYNTHETIC"


def test_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/runs/does-not-exist")

    assert response.status_code == 404


def test_all_editable_scenarios_are_exposed_and_executable(client: TestClient) -> None:
    listing = client.get("/api/v1/scenarios")

    assert listing.status_code == 200
    scenario_ids = {item["scenario_id"] for item in listing.json()}
    assert scenario_ids == {
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
    results = {}
    for scenario_id in sorted(scenario_ids):
        editable = client.get(f"/api/v1/scenarios/{scenario_id}")
        evaluated = client.post(f"/api/v1/scenarios/{scenario_id}/evaluate")
        assert editable.status_code == 200, scenario_id
        assert evaluated.status_code == 200, scenario_id
        assert evaluated.json()["run_id"] == f"scenario-{scenario_id}"
        results[scenario_id] = evaluated.json()

    feed_safety = results["feed_sulfur_increase"]["assembled_input"]["current_safety"]["data"]
    assert "SULFUR_LIMIT" in feed_safety["violations"]
    q21_warnings = results["q21_outlier_307"]["assembled_input"]["current_quality"]["data"][
        "warnings"
    ]
    assert "Q21_OUTLIER_307_NOT_INGESTED" in q21_warnings
    impossible = results["impossible_quality_passport"]["assembled_input"]["current_safety"][
        "data"
    ]["violations"]
    assert {"SULFUR_LIMIT", "T95_LIMIT", "DENSITY_LIMIT", "CETANE_LIMIT"} <= set(impossible)
    insufficient = results["insufficient_data"]["assembled_input"]["current_quality"]["data"]
    assert insufficient["quality_prediction"] is None
    additive = results["blending_vs_additive"]["assembled_input"]["current_quality"]["data"][
        "metrics"
    ]
    assert additive["additive_pct"] == 2.2
    assert additive["relative_cost"] > 3.0


def test_decide_accepts_preassembled_outputs_from_colleague_components(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/decide",
        json=make_keep_input().model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "KEEP"


def test_future_history_is_rejected_by_contract(client: TestClient) -> None:
    payload = _insufficient_payload()
    payload["process_state"]["timestamp"] = "2026-09-19T10:00:00Z"
    future = dict(payload["process_state"])
    future["timestamp"] = "2026-09-19T10:10:00Z"
    payload["history"] = [future]

    response = client.post("/api/v1/evaluate", json=payload)

    assert response.status_code == 422
    assert "history cannot contain timestamps" in response.text


def _complete_state(api_app, timestamp: datetime, step: int) -> dict:
    quality_adapter = api_app.state.coordinator.quality
    assert isinstance(quality_adapter, LocalQualityAdapter)
    telemetry: dict[str, float] = {}
    for source, signals in quality_adapter.router.primary.schema.required_signals.items():
        if source not in {"avt", "hyd"}:
            continue
        for number, signal in enumerate(sorted(signals), start=1):
            telemetry[f"{source}_{signal.lower()}"] = 50.0 + number + step * 0.01
    return {
        "timestamp": timestamp.isoformat(),
        "quality": {
            "mg_sulfur": 8.0 + (step % 3) * 0.02,
            "source": "pak",
            "pak_d15": 845.0 + (step % 2) * 0.01,
            "blending": {
                "grade": "SUMMER",
                "components": [
                    {
                        "name": "hydrotreated",
                        "share_pct": 80.0,
                        "share_control": "blend_hydrotreated_share_pct",
                        "use_hydrotreated_sulfur": True,
                        "t95_c": 350.0,
                        "density_kg_m3": 835.0,
                        "cetane_number": 50.0,
                    },
                    {
                        "name": "low_sulfur_tank",
                        "share_pct": 20.0,
                        "share_control": "blend_low_sulfur_share_pct",
                        "sulfur_mg_kg": 2.0,
                        "t95_c": 345.0,
                        "density_kg_m3": 825.0,
                        "cetane_number": 55.0,
                    },
                ],
            },
        },
        "telemetry": telemetry,
        "data_quality": {"missing": [], "stale": [], "flatline": [], "outlier": []},
        "data_confidence": "HIGH",
        "current_controls": {
            "hyd_t6": 362.7,
            "hyd_f9": 218.7,
            "hyd_p13": 3.918,
            "blend_hydrotreated_share_pct": 80.0,
            "blend_low_sulfur_share_pct": 20.0,
            "cetane_additive_pct": 0.0,
        },
    }


def test_evaluate_with_six_hour_history_reaches_orchestrator(
    client: TestClient,
    api_app,
) -> None:
    start = datetime(2026, 9, 20, tzinfo=UTC)
    states = [
        _complete_state(api_app, start + timedelta(minutes=10 * step), step) for step in range(37)
    ]
    response = client.post(
        "/api/v1/evaluate",
        json={
            "run_id": "api-complete-history-001",
            "process_state": states[-1],
            "history": states[:-1],
        },
    )

    assert response.status_code == 200
    body = response.json()
    quality = body["assembled_input"]["current_quality"]
    assert quality["status"] == "OK"
    assert quality["data"]["quality_prediction"] == quality["data"]["metrics"]["sulfur_mg_kg"]
    assert quality["data"]["product"] == "COMMERCIAL_DIESEL"
    assert quality["data"]["violation_probability"] is not None
    assert body["assembled_input"]["optimization"]["data"]["status"] == ("NO_FEASIBLE_SOLUTION")
    assert body["assembled_input"]["optimization"]["data"]["input_source"] == "SYNTHETIC"
    assert body["assembled_input"]["optimization"]["data"]["uses_mock_assessments"] is False
    assert body["decision"]["decision"] == "REFUSE"
    scenarios = body["assembled_input"]["scenarios"]
    assert scenarios[0]["candidate"]["candidate_id"] == "NO_CHANGE"
    assert scenarios[0]["violations"]
