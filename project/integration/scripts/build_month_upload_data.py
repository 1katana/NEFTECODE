"""Create a compact one-month package for the operator-console upload form."""

from __future__ import annotations

from pathlib import Path
from shutil import copy2

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "integration" / "sample_upload_data_month"
START = pd.Timestamp("2023-01-01 00:00:00")
END = pd.Timestamp("2023-01-31 23:50:00")


def _trim_csv(source: Path, target: Path) -> int:
    frame = pd.read_csv(source, low_memory=False)
    timestamp = pd.to_datetime(frame["date"], errors="coerce", format="mixed")
    month = frame.loc[timestamp.between(START, END)]
    month.to_csv(target, index=False)
    return len(month)


def _trim_paired_workbook(source: Path, target: Path, header_rows: int) -> int:
    """Keep dates per timestamp/value column pair without changing workbook layout."""
    raw = pd.read_excel(source, header=None, dtype=object)
    header = raw.iloc[:header_rows].copy()
    body = raw.iloc[header_rows:].reset_index(drop=True)
    pairs: list[tuple[int, pd.DataFrame]] = []
    for column in range(0, raw.shape[1] - 1, 2):
        timestamps = pd.to_datetime(body.iloc[:, column], errors="coerce", format="mixed")
        selected = body.loc[timestamps.between(START, END), [column, column + 1]].reset_index(
            drop=True
        )
        pairs.append((column, selected))

    rows = max((len(pair) for _, pair in pairs), default=0)
    trimmed = pd.DataFrame(index=range(rows), columns=raw.columns, dtype=object)
    for column, pair in pairs:
        if pair.empty:
            continue
        trimmed.loc[: len(pair) - 1, column] = pair.iloc[:, 0].to_numpy()
        trimmed.loc[: len(pair) - 1, column + 1] = pair.iloc[:, 1].to_numpy()
    pd.concat([header, trimmed], ignore_index=True).to_excel(target, index=False, header=False)
    return rows


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    avt_rows = _trim_csv(ROOT / "data/data/avt_tags.csv", OUTPUT / "avt_tags.csv")
    hydro_rows = _trim_csv(ROOT / "data/data/242000_tags.csv", OUTPUT / "242000_tags.csv")
    lims_rows = _trim_paired_workbook(
        ROOT / "ЛИМСы 01.01.2023 - н.в_ (2).xlsx", OUTPUT / "lims.xlsx", header_rows=3
    )
    pak_rows = _trim_paired_workbook(
        ROOT / "Выгрузка ПАК 01.01.2023 - н.в_.xlsx", OUTPUT / "pak.xlsx", header_rows=1
    )
    copy2(ROOT / "Теги_хакатон.xlsx", OUTPUT / "tags.xlsx")
    print(f"Created {OUTPUT}")
    print(f"Rows: AVT={avt_rows}, 24-2000={hydro_rows}, LIMS={lims_rows}, PAK={pak_rows}")


if __name__ == "__main__":
    main()
