from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from neftecode_orchestrator.contracts import FinalDecision, OrchestratorInput
from quality_agent.shadow import ShadowPromotionGates, evaluate_shadow_readiness

from .adapters import LocalQualityAdapter
from .coordinator import IntegrationCoordinator
from .data_upload import UploadContractError, process_uploaded_files
from .factory import build_coordinator
from .models import (
    EvaluationRequest,
    EvaluationResponse,
    HealthResponse,
    LimsObservation,
    UploadEvaluationResponse,
)
from .optimizer_adapter import LocalOptimizerAdapter
from .reliability_adapter import LocalReliabilityAdapter
from .scenarios import ScenarioCatalog
from .settings import IntegrationSettings

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"
DEFAULT_SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios" / "catalog.yaml"
DEFAULT_DEMO_REQUEST = Path(__file__).resolve().parents[2] / "runtime" / "demo_request.json"
DEFAULT_EXAMPLES = {
    "historical_20260515_1000": (
        "Исторический срез · без рецептуры",
        Path(__file__).resolve().parents[2] / "examples/historical_20260515_1000.json",
    ),
    "illustrative_blend_20260515_1200": (
        "Расчётная смесь · реальные измерения + допущение 80/20",
        Path(__file__).resolve().parents[2] / "examples/illustrative_blend_20260515_1200.json",
    ),
}

AvtTagsUpload = Annotated[UploadFile, File(description="CSV телеметрии АВТ")]
HydroTagsUpload = Annotated[UploadFile, File(description="CSV телеметрии 24-2000")]
LimsUpload = Annotated[UploadFile, File(description="XLSX лабораторных измерений ЛИМС")]
TagsUpload = Annotated[UploadFile, File(description="XLSX справочника тегов")]
PakUpload = Annotated[
    UploadFile | None,
    File(description="Необязательный XLSX поточного анализатора ПАК/ВАК"),
]


def _load_gates(path: Path) -> ShadowPromotionGates:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    values = payload.get("promotion_gates", payload)
    if not isinstance(values, dict):
        raise TypeError("promotion_gates must be a mapping")
    gates = ShadowPromotionGates(**values)
    gates.validate()
    return gates


def create_app(
    coordinator: IntegrationCoordinator | None = None,
    settings: IntegrationSettings | None = None,
) -> FastAPI:
    resolved_settings = settings or IntegrationSettings.from_yaml(DEFAULT_CONFIG)
    resolved_coordinator = coordinator or build_coordinator(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        quality = resolved_coordinator.quality
        if isinstance(quality, LocalQualityAdapter):
            quality.close()
        optimization = resolved_coordinator.optimization
        if isinstance(optimization, LocalOptimizerAdapter):
            optimization.close()
        reliability = resolved_coordinator.reliability
        if isinstance(reliability, LocalReliabilityAdapter):
            reliability.close()

    app = FastAPI(
        title="Neftecode Integration API",
        version="0.1.0",
        description="Hackathon composition root. Authentication is intentionally disabled.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.state.coordinator = resolved_coordinator
    app.state.settings = resolved_settings
    app.state.scenarios = ScenarioCatalog(DEFAULT_SCENARIOS, DEFAULT_DEMO_REQUEST)

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        quality = resolved_coordinator.quality
        runtime: dict = {"status": "UNAVAILABLE"}
        if isinstance(quality, LocalQualityAdapter):
            primary = quality.router.primary.manifest
            fallback = quality.router.telemetry_fallback.manifest
            runtime = {
                "status": "READY_FOR_SHADOW",
                "primary_training_id": primary.get("training_id"),
                "fallback_training_id": fallback.get("training_id"),
                "point_policy": quality.router.point_policy,
                "shadow_log": str(quality.runtime_config.shadow_log),
            }
        return HealthResponse(
            status="READY_FOR_SHADOW_WITH_BLOCKERS",
            runtime=runtime,
            integration=resolved_coordinator.metadata(),
        )

    @app.post("/api/v1/evaluate", response_model=EvaluationResponse)
    async def evaluate(request: EvaluationRequest) -> EvaluationResponse:
        return await resolved_coordinator.evaluate(request)

    @app.post("/api/v1/data-upload/evaluate", response_model=UploadEvaluationResponse)
    async def upload_test_data(
        avt_tags: AvtTagsUpload,
        hydro_tags: HydroTagsUpload,
        lims_xlsx: LimsUpload,
        tags_xlsx: TagsUpload,
        pak_xlsx: PakUpload = None,
    ) -> UploadEvaluationResponse:
        """Run the canonical preprocessing script over user test data and evaluate it.

        Multipart field names are the processing/upload contract. Files live only
        for the duration of this request; the API retains the calculation result
        under its ``run_id`` just like ``POST /evaluate``.
        """
        uploads = {
            "avt_tags": (avt_tags.filename, avt_tags.size, avt_tags.file),
            "hydro_tags": (hydro_tags.filename, hydro_tags.size, hydro_tags.file),
            "lims_xlsx": (lims_xlsx.filename, lims_xlsx.size, lims_xlsx.file),
            "tags_xlsx": (tags_xlsx.filename, tags_xlsx.size, tags_xlsx.file),
            "pak_xlsx": (
                pak_xlsx.filename if pak_xlsx else None,
                pak_xlsx.size if pak_xlsx else None,
                pak_xlsx.file if pak_xlsx else None,
            ),
        }
        try:
            request, processing = await asyncio.to_thread(process_uploaded_files, uploads)
        except UploadContractError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(
                status_code=422,
                detail=f"Не удалось обработать загруженные данные: {type(error).__name__}: {error}",
            ) from error
        result = await resolved_coordinator.evaluate(request)
        return UploadEvaluationResponse(
            **result.model_dump(mode="python"),
            processing=processing.model_dump(mode="json"),
        )

    @app.get("/api/v1/scenarios")
    async def list_scenarios() -> list[dict[str, str]]:
        return app.state.scenarios.summary()

    @app.get("/api/v1/scenarios/{scenario_id}", response_model=EvaluationRequest)
    async def get_scenario(scenario_id: str) -> EvaluationRequest:
        try:
            return app.state.scenarios.build(scenario_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/v1/scenarios/{scenario_id}/evaluate", response_model=EvaluationResponse)
    async def evaluate_scenario(scenario_id: str) -> EvaluationResponse:
        try:
            request = app.state.scenarios.build(scenario_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return await resolved_coordinator.evaluate(request)

    @app.get("/api/v1/examples")
    async def list_examples() -> list[dict[str, str]]:
        return [
            {"example_id": example_id, "title": title}
            for example_id, (title, _) in DEFAULT_EXAMPLES.items()
        ]

    @app.get("/api/v1/examples/{example_id}", response_model=EvaluationRequest)
    async def get_example(example_id: str) -> EvaluationRequest:
        if example_id not in DEFAULT_EXAMPLES:
            raise HTTPException(status_code=404, detail="example_id not found")
        return EvaluationRequest.model_validate(
            json.loads(DEFAULT_EXAMPLES[example_id][1].read_text(encoding="utf-8"))
        )

    @app.post("/api/v1/examples/{example_id}/evaluate", response_model=EvaluationResponse)
    async def evaluate_example(example_id: str) -> EvaluationResponse:
        request = await get_example(example_id)
        return await resolved_coordinator.evaluate(request)

    @app.post("/api/v1/decide", response_model=FinalDecision)
    async def decide(assembled: OrchestratorInput) -> FinalDecision:
        """Decision-only route for colleague-owned components using agreed contracts."""
        return resolved_coordinator.orchestrator.decide(assembled)

    @app.get("/api/v1/runs/{run_id}", response_model=EvaluationResponse)
    async def get_run(run_id: str) -> EvaluationResponse:
        response = resolved_coordinator.get_run(run_id)
        if response is None:
            raise HTTPException(status_code=404, detail="run_id not found")
        return response

    @app.post("/api/v1/shadow/lims", status_code=202)
    async def append_lims(observation: LimsObservation) -> dict[str, str]:
        quality = resolved_coordinator.quality
        if not isinstance(quality, LocalQualityAdapter):
            raise HTTPException(status_code=503, detail="local QualityAgent is unavailable")
        logger = quality.router.shadow_logger
        if logger is None:
            raise HTTPException(status_code=503, detail="shadow logger is disabled")
        logger.log_lims(
            sample_timestamp=observation.sample_timestamp,
            sulfur_mg_kg=observation.sulfur_mg_kg,
            sample_id=observation.sample_id,
        )
        return {"status": "accepted"}

    @app.get("/api/v1/shadow/status")
    async def shadow_status() -> dict:
        quality = resolved_coordinator.quality
        if not isinstance(quality, LocalQualityAdapter):
            raise HTTPException(status_code=503, detail="local QualityAgent is unavailable")
        logger = quality.router.shadow_logger
        if logger is None:
            raise HTTPException(status_code=503, detail="shadow logger is disabled")
        summary = logger.summary()
        readiness = evaluate_shadow_readiness(
            summary,
            _load_gates(resolved_settings.shadow_gates_config),
        )
        return {"summary": summary, "readiness": readiness}

    return app


app = create_app()
