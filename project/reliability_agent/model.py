"""Shared numeric transformations for training, validation and serving."""
import numpy as np
import pandas as pd
from .config import PRESSURE_SOURCES


def pressure_consensus(values, tolerance):
    """Closest agreeing pair, never three independent risk votes."""
    a = np.asarray(values, dtype=float)
    if a.ndim == 1:
        a = a[None, :]
    n = np.isfinite(a).sum(axis=1)
    result = np.full(len(a), np.nan)
    single = n == 1
    result[single] = np.nansum(a[single], axis=1)
    distance = np.column_stack([np.abs(a[:,i]-a[:,j]) for i,j in [(0,1),(0,2),(1,2)]])
    distance[~np.isfinite(distance)] = np.inf
    best = distance.argmin(axis=1)
    for k,(i,j) in enumerate([(0,1),(0,2),(1,2)]):
        select = (n >= 2) & (best == k) & (distance[:,k] <= tolerance)
        result[select] = (a[select,i] + a[select,j]) / 2
    all_agree = (n == 3) & (distance.max(axis=1) <= tolerance)
    result[all_agree] = np.median(a[all_agree], axis=1)
    return result


def prepare_frame(values, flatline_ages, tolerance, flatline_minutes):
    x = values.where(np.isfinite(values)).mask(flatline_ages >= flatline_minutes)
    x["avt_p_k2"] = pressure_consensus(x[PRESSURE_SOURCES].to_numpy(), tolerance)
    return x


def score_components(bundle, matrix):
    """Scores measure historical atypicality; they are not failure probabilities."""
    x = np.asarray(matrix, dtype=float)
    raw = -bundle["model"].score_samples(x)
    lo, hi = bundle["anomaly_calibration"]
    anomaly = np.clip((raw-lo) / max(hi-lo, 1e-8), 0, 1)
    q = np.asarray(bundle["quantiles"])
    # q = p0.1, p5, p50, p95, p99.9 per feature. These are statistical
    # reference edges, not engineering limits. Zero through the central 90%.
    scale = np.maximum(q[:,4]-q[:,0], np.maximum(np.abs(q[:,2])*1e-6, 1e-8))
    high = (x-q[:,3]) / np.maximum(q[:,4]-q[:,3], scale*.01)
    low = (q[:,1]-x) / np.maximum(q[:,1]-q[:,0], scale*.01)
    per_tag = np.clip(np.maximum(high, low), 0, 1)
    bounds = per_tag.max(axis=1)
    return np.maximum(anomaly, bounds), anomaly, bounds, per_tag
