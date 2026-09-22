"""Read historical LIMS-event snapshots without exposing targets to agents.

The v2 split tables contain model targets and past-derived features in the
same row. This adapter deliberately passes only current telemetry to the
optimizer. It is a contract/replay aid, not a counterfactual quality model.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from zipfile import ZipFile

from .models import InputSource, ProcessState

HistoricalSplit = Literal["train", "val", "test"]
_SPLIT_FILES = {
    "train": "split_train_v2.csv",
    "val": "split_val_v2.csv",
    "test": "split_test_v2.csv",
}
_REQUIRED_COLUMNS = frozenset(
    {
        "timestamp",
        "telemetry_timestamp",
        "telemetry_age_min",
        "telemetry_available",
        "target_mg_sulfur",
    }
)


@dataclass(frozen=True)
class HistoricalCase:
    """One retrospective snapshot with its hydrotreated-product label separate."""

    state: ProcessState
    split: HistoricalSplit
    row_number: int
    observed_hydro2_sulfur_mg_kg: float | None
    sulfur_flag_basic_invalid: bool | None
    sulfur_flag_robust_outlier: bool | None


def _optional_float(value: str | None, *, column: str, row_number: int) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"invalid {column} at CSV row {row_number}") from error
    if not math.isfinite(number):
        raise ValueError(f"non-finite {column} at CSV row {row_number}")
    return number


def _optional_bool(value: str | None, *, column: str, row_number: int) -> bool | None:
    if value is None or not value.strip():
        return None
    if value.lower() in {"true", "1"}:
        return True
    if value.lower() in {"false", "0"}:
        return False
    raise ValueError(f"invalid {column} at CSV row {row_number}")


def iter_historical_cases(
    dataset_zip: str | Path,
    *,
    split: HistoricalSplit = "test",
    limit: int | None = None,
) -> Iterator[HistoricalCase]:
    """Stream v2 split rows as ProcessState plus a separate retrospective label.

    No target, LIMS result, previous-LIMS feature, or engineered lag is placed
    in ProcessState. The timestamp is the LIMS sample-collection time; the
    conservative replay availability time is sample time + 4 hours.
    """
    if split not in _SPLIT_FILES:
        raise ValueError(f"unknown historical split: {split}")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer")

    member = _SPLIT_FILES[split]
    with ZipFile(dataset_zip) as archive:
        if member not in archive.namelist():
            raise ValueError(f"dataset ZIP is missing {member}")
        with archive.open(member) as raw:
            stream = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(stream)
            columns = reader.fieldnames or []
            if len(columns) != len(set(columns)):
                raise ValueError(f"{member} has duplicate column names")
            missing = _REQUIRED_COLUMNS.difference(columns)
            if missing:
                raise ValueError(f"{member} is missing columns: {sorted(missing)}")
            telemetry_columns = sorted(
                name
                for name in columns
                if name.startswith("tele_") and name.endswith("_current")
            )
            if not telemetry_columns:
                raise ValueError(f"{member} has no current telemetry columns")

            for yielded, row in enumerate(reader):
                if limit is not None and yielded >= limit:
                    break
                row_number = yielded + 2
                if None in row:
                    raise ValueError(f"extra CSV values at row {row_number}")
                try:
                    timestamp = datetime.fromisoformat(row["timestamp"])
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        f"invalid timestamp at CSV row {row_number}"
                    ) from error
                telemetry_time_raw = row["telemetry_timestamp"]
                try:
                    telemetry_time = (
                        datetime.fromisoformat(telemetry_time_raw)
                        if telemetry_time_raw
                        else None
                    )
                except ValueError as error:
                    raise ValueError(
                        f"invalid telemetry timestamp at CSV row {row_number}"
                    ) from error
                if telemetry_time is not None:
                    try:
                        is_future = telemetry_time > timestamp
                    except TypeError as error:
                        raise ValueError(
                            f"incompatible telemetry timestamp at CSV row {row_number}"
                        ) from error
                    if is_future:
                        raise ValueError(f"future telemetry at CSV row {row_number}")
                telemetry_available = _optional_bool(
                    row["telemetry_available"],
                    column="telemetry_available",
                    row_number=row_number,
                )
                if telemetry_available is True and telemetry_time is None:
                    raise ValueError(
                        f"available telemetry without timestamp at CSV row {row_number}"
                    )
                telemetry_age = _optional_float(
                    row["telemetry_age_min"],
                    column="telemetry_age_min",
                    row_number=row_number,
                )
                if telemetry_age is not None and telemetry_age < 0:
                    raise ValueError(f"negative telemetry age at CSV row {row_number}")
                values = {
                    name: _optional_float(row[name], column=name, row_number=row_number)
                    for name in telemetry_columns
                }
                state = ProcessState(
                    source=InputSource.HISTORICAL,
                    timestamp=timestamp,
                    values=values,
                    metadata={
                        "dataset_source": member,
                        "dataset_split": split,
                        "dataset_row_number": row_number,
                        "time_semantics": "LIMS_SAMPLE_COLLECTION",
                        "lims_available_at": (
                            timestamp + timedelta(hours=4)
                        ).isoformat(),
                        "lims_result_available": False,
                        "telemetry_timestamp": telemetry_time_raw or None,
                        "telemetry_age_min": telemetry_age,
                        "telemetry_available": telemetry_available,
                        "telemetry_within_source_range": _optional_bool(
                            row.get("telemetry_within_source_range"),
                            column="telemetry_within_source_range",
                            row_number=row_number,
                        ),
                    },
                )
                yield HistoricalCase(
                    state=state,
                    split=split,
                    row_number=row_number,
                    observed_hydro2_sulfur_mg_kg=_optional_float(
                        row["target_mg_sulfur"],
                        column="target_mg_sulfur",
                        row_number=row_number,
                    ),
                    sulfur_flag_basic_invalid=_optional_bool(
                        row.get("target_mg_sulfur_flag_basic_invalid"),
                        column="target_mg_sulfur_flag_basic_invalid",
                        row_number=row_number,
                    ),
                    sulfur_flag_robust_outlier=_optional_bool(
                        row.get("target_mg_sulfur_flag_robust_outlier"),
                        column="target_mg_sulfur_flag_robust_outlier",
                        row_number=row_number,
                    ),
                )
