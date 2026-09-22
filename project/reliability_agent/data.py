"""Read original CSVs; construct causal observation flags without altering files."""
import numpy as np
import pandas as pd
from .config import RAW_FEATURES, ROOT


def read_telemetry(data_dir=None):
    data_dir = ROOT / "data" / "data" if data_dir is None else __import__('pathlib').Path(data_dir)
    frames = []
    for prefix, name in [("avt", "avt_tags.csv"), ("hyd", "242000_tags.csv")]:
        tags = [s.split('_', 1)[1].upper() for s in RAW_FEATURES if s.startswith(prefix + '_')]
        df = pd.read_csv(data_dir / name, usecols=["date", *tags])
        df.index = pd.to_datetime(df.pop("date"), errors="raise")
        if df.index.has_duplicates or not df.index.is_monotonic_increasing:
            raise ValueError(f"{name}: timestamps must be unique and increasing")
        frames.append(df.rename(columns={t: prefix + '_' + t.lower() for t in tags}))
    values = pd.concat(frames, axis=1).sort_index()
    values.index.name = "timestamp"
    # Elapsed time from the start of the current exact-value run, using past
    # observations only. A timestamp gap restarts the run.
    ages = pd.DataFrame(index=values.index)
    gap = values.index.to_series().diff().ne(pd.Timedelta(10, unit="min"))
    for tag in values:
        changed = values[tag].ne(values[tag].shift()) | gap
        started = values.index.to_series().where(changed).ffill()
        ages[tag] = (values.index.to_series() - started).dt.total_seconds() / 60
    return values, ages


def snapshot(values, flatline_ages, at=None):
    when = pd.Timestamp(at) if at is not None else values.index[-1]
    if when.tzinfo is not None:
        raise ValueError("Source CSV timestamps have no timezone; use the same local naive time for --at")
    pos = values.index.searchsorted(when, side="right") - 1
    if pos < 0:
        raise ValueError("No telemetry at or before the requested timestamp")
    row, ages = values.iloc[pos], flatline_ages.iloc[pos]
    age = float((when - row.name).total_seconds() / 60)
    return {
        "timestamp": str(when), "source_timestamp": str(row.name),
        "telemetry": {t: float(v) if np.isfinite(v) else None for t, v in row.items()},
        "data_quality": {t: {"age_min": age, "flatline_min": float(ages[t]),
                              "flag_missing": not bool(np.isfinite(row[t]))} for t in row.index},
    }
