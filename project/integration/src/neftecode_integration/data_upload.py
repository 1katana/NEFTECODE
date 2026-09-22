"""Контракт загрузки исходных данных для операторской консоли.

Здесь намеренно нет отдельной реализации предобработки: загрузка вызывает
``neftecode_processing.run_processing`` и адаптирует только его ``final`` в
строгий ``EvaluationRequest`` Integration API.
"""

from __future__ import annotations

import importlib.util
import math
import shutil
import sys
import tempfile
from datetime import UTC
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, Final
from uuid import uuid4

import pandas as pd
from neftecode_orchestrator.enums import InputSource
from pydantic import Field

from .models import ApiModel, EvaluationRequest

PROCESSING_CONTRACT_VERSION: Final = "1.0.0"
HISTORY_POINTS: Final = 36
MAX_UPLOAD_BYTES: Final = 600 * 1024 * 1024
REQUIRED_UPLOADS: Final = {
    "avt_tags": ".csv",
    "hydro_tags": ".csv",
    "lims_xlsx": ".xlsx",
    "tags_xlsx": ".xlsx",
}
OPTIONAL_UPLOADS: Final = {"pak_xlsx": ".xlsx"}
CONTROL_TAGS: Final = frozenset({"hyd_t6", "hyd_f9", "hyd_p13"})


class UploadContractError(ValueError):
    """The uploaded files do not satisfy the processing contract."""


class ProcessingSummary(ApiModel):
    contract_version: str = PROCESSING_CONTRACT_VERSION
    source: str = "USER_UPLOADED_TEST_DATA"
    rows: int = Field(ge=1)
    history_points: int = Field(ge=0, le=HISTORY_POINTS)
    timestamp_from: str
    timestamp_to: str
    artifacts: list[str]
    warnings: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def _processing_module() -> ModuleType:
    root = Path(__file__).resolve().parents[3]
    module_path = root / "neftecode_processing.py"
    spec = importlib.util.spec_from_file_location("neftecode_processing", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load preprocessing module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    # Dataclass resolves annotations through sys.modules while this file is
    # being executed; register it before exec_module for Python 3.13 as well.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _finite(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _truthy(value: object) -> bool:
    return bool(value) if value is not None and not pd.isna(value) else False


def _timestamp(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp.isoformat().replace("+00:00", "Z")


def _quality_from_row(row: pd.Series) -> dict[str, object]:
    """Translate the stable ``*_value`` processing output to QualityAgent keys."""
    quality: dict[str, object] = {}
    for column, value in row.items():
        if not str(column).endswith("_value"):
            continue
        number = _finite(value)
        if number is None:
            continue
        base = str(column).removesuffix("_value").lower()
        source = row.get(f"{base}_src")
        payload: object = {"value": number, "source": str(source).lower()} if source else number
        if base in {"24_2000_mg_sulfur", "pak_mg_sulfur", "mg_sulfur"}:
            quality[base] = payload
        elif base in {"24_2000_d15", "pak_d15", "d15", "density"}:
            # QualityAgent receives density under its canonical PAK key.
            quality["pak_d15"] = payload
    return quality


def _state_from_row(row: pd.Series) -> dict[str, object]:
    telemetry: dict[str, float | None] = {}
    missing: list[str] = []
    stale: list[str] = []
    outlier: list[str] = []
    data_quality: dict[str, object] = {}

    for column, value in row.items():
        name = str(column).lower()
        if not name.startswith(("avt_", "hyd_")) or "_flag_" in name:
            continue
        if name.endswith(("_age_min", "_src")):
            continue
        numeric = _finite(value)
        telemetry[name] = numeric
        if numeric is None or _truthy(row.get(f"{name}_flag_missing")):
            missing.append(name)
        if _truthy(row.get(f"{name}_flag_stale")):
            stale.append(name)
        if _truthy(row.get(f"{name}_flag_outlier")):
            outlier.append(name)
        data_quality[name] = {
            "flag_missing": name in missing,
            "flag_stale": name in stale,
            "flag_outlier": name in outlier,
            "age_min": 0.0,
        }

    usable = sum(value is not None for value in telemetry.values())
    missing_ratio = 1 - usable / len(telemetry) if telemetry else 1.0
    confidence = "HIGH" if missing_ratio <= 0.05 else "MEDIUM" if missing_ratio <= 0.3 else "LOW"
    if not telemetry:
        confidence = "UNKNOWN"
    data_quality.update(
        {
            "missing": sorted(missing),
            "stale": sorted(stale),
            "outlier": sorted(outlier),
            "flatline": sorted(stale),
            "telemetry_available": bool(telemetry),
        }
    )
    return {
        "timestamp": _timestamp(row["timestamp"]),
        "quality": _quality_from_row(row),
        "telemetry": telemetry,
        "data_quality": data_quality,
        "data_confidence": confidence,
        "current_controls": {
            tag: telemetry[tag] for tag in CONTROL_TAGS if telemetry.get(tag) is not None
        },
    }


def evaluation_request_from_processed(final: pd.DataFrame, *, run_id: str | None = None) -> EvaluationRequest:
    """Build the only allowed processing → Integration API boundary payload."""
    if "timestamp" not in final.columns or final.empty:
        raise UploadContractError("Предобработка не вернула ни одной точки с timestamp.")
    frame = final.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if frame.empty:
        raise UploadContractError("В обработанных данных нет корректных timestamp.")
    window = frame.tail(HISTORY_POINTS + 1)
    states = [_state_from_row(row) for _, row in window.iterrows()]
    return EvaluationRequest(
        run_id=run_id or f"upload-{uuid4()}",
        input_source=InputSource.HISTORICAL,
        process_state=states[-1],
        history=states[:-1],
    )


def _validate_uploads(files: dict[str, tuple[str | None, int | None, BinaryIO | None]]) -> None:
    total = 0
    for field, suffix in {**REQUIRED_UPLOADS, **OPTIONAL_UPLOADS}.items():
        filename, size, _ = files.get(field, (None, None, None))
        if field in REQUIRED_UPLOADS and not filename:
            raise UploadContractError(f"Не передан обязательный файл: {field}.")
        if filename and Path(filename).suffix.lower() != suffix:
            raise UploadContractError(f"Файл {field} должен иметь расширение {suffix}.")
        total += size or 0
    if total > MAX_UPLOAD_BYTES:
        raise UploadContractError("Общий размер файлов превышает 600 МБ.")


def process_uploaded_files(
    files: dict[str, tuple[str | None, int | None, BinaryIO | None]],
) -> tuple[EvaluationRequest, ProcessingSummary]:
    """Copy browser uploads into an isolated directory and execute the pipeline."""
    _validate_uploads(files)
    runtime_dir = Path(__file__).resolve().parents[2] / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="neftecode-upload-", dir=runtime_dir) as temporary:
        workspace = Path(temporary)
        filenames = {
            "avt_tags": "avt_tags.csv",
            "hydro_tags": "242000_tags.csv",
            "lims_xlsx": "lims.xlsx",
            "pak_xlsx": "pak.xlsx",
            "tags_xlsx": "tags.xlsx",
        }
        for field, target_name in filenames.items():
            _, _, source = files.get(field, (None, None, None))
            if source is None:
                continue
            source.seek(0)
            with (workspace / target_name).open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)

        processing = _processing_module()
        paths = processing.Paths(
            avt_tags=workspace / filenames["avt_tags"],
            hydro_tags=workspace / filenames["hydro_tags"],
            lims_xlsx=workspace / filenames["lims_xlsx"],
            pak_xlsx=workspace / filenames["pak_xlsx"],
            tags_xlsx=workspace / filenames["tags_xlsx"],
        )
        data, saved = processing.run_processing(paths, workspace / "artifacts", fmt="csv")
        final = data["final"]
        request = evaluation_request_from_processed(final)
        summary = ProcessingSummary(
            rows=len(final),
            history_points=len(request.history),
            timestamp_from=_timestamp(final["timestamp"].min()),
            timestamp_to=_timestamp(final["timestamp"].max()),
            artifacts=sorted(path.name for path in saved.values()),
            warnings=(
                ["PAK_NOT_PROVIDED: расчёт останется fail-closed без поточного качества."]
                if files.get("pak_xlsx", (None, None, None))[0] is None
                else []
            ),
        )
        return request, summary
