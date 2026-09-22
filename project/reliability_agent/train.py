import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest

from .config import DEFAULT_ARTIFACT, DEFAULT_POLICY, GROUPS, PRESSURE_SOURCES, VERSION
from .data import read_telemetry
from .model import prepare_frame, score_components


def train(data_dir=None, output=DEFAULT_ARTIFACT):
    values, flat = read_telemetry(data_dir)
    train_mask = values.index < pd.Timestamp("2026-01-01")
    val_mask = (values.index >= pd.Timestamp("2026-01-01")) & (values.index < pd.Timestamp("2026-05-01"))
    test_mask = values.index >= pd.Timestamp("2026-05-01")
    p = values.loc[train_mask, PRESSURE_SOURCES].mask(flat.loc[train_mask, PRESSURE_SOURCES] >= DEFAULT_POLICY['flatline_minutes'])
    disagreement = (p.iloc[:,0] - p.iloc[:,1]).abs().dropna()
    tolerance = float(max(abs(p.stack().median()) * .01, disagreement.quantile(.90) * 5, 1e-6))
    x = prepare_frame(values, flat, tolerance, DEFAULT_POLICY['flatline_minutes'])
    artifact = {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "sklearn_version": sklearn.__version__, "policy": DEFAULT_POLICY.copy(),
                "pressure_tolerance": tolerance, "groups": {},
                "score_meaning": "historical_regime_risk_proxy_not_failure_probability"}
    report = {"source_rows": len(values), "first": str(values.index.min()), "last": str(values.index.max()),
              "train_end_exclusive": "2026-01-01", "validation_end_exclusive": "2026-05-01",
              "test_start": "2026-05-01", "pressure_consensus_tolerance": tolerance,
              "algorithm": "IsolationForest + transparent reference-tail and configured-limit rules",
              "reference_policy": "Complete, non-flatlined, active-load observations; broad median +/- 20 IQR filter for reference only. Excluded points are retained for inference; no failure labels inferred.",
              "metrics_note": "HIGH/MEDIUM rates below are alert rates, not precision, recall or failure probabilities.",
              "groups": {}}
    for name, spec in GROUPS.items():
        cols = spec['features']
        z = x[cols]
        complete = z.notna().all(axis=1)
        feed_median = float(x.loc[train_mask & complete, spec['load']].median())
        load_floor = max(0, .25 * feed_median)
        active = x[spec['load']] > load_floor
        base = z.loc[train_mask & complete & active]
        med = base.median()
        iqr = base.quantile(.75) - base.quantile(.25)
        spread = np.maximum(iqr.to_numpy(), np.maximum(med.abs().to_numpy()*.001, 1e-8))
        reference = (np.abs(z.to_numpy()-med.to_numpy()) <= spread*20).all(axis=1)
        fit = z.loc[train_mask & complete & active & reference]
        calibration = z.loc[val_mask & complete & active & reference]
        if len(fit) < 1000 or len(calibration) < 100:
            raise ValueError(f"{name}: insufficient reference history ({len(fit)}, {len(calibration)})")
        sample = fit.sample(n=min(30000, len(fit)), random_state=42).sort_index()
        model = IsolationForest(n_estimators=128, max_samples=1024, random_state=42, n_jobs=2)
        model.fit(sample.to_numpy())
        anomaly = -model.score_samples(calibration.to_numpy())
        q = fit.quantile([.001, .05, .5, .95, .999]).to_numpy().T
        bundle = {"spec": spec, "model": model, "quantiles": q.tolist(),
                  "load_floor": load_floor, "fill_values": fit.median().to_list(),
                  "anomaly_calibration": np.quantile(anomaly, [.90, .995]).tolist()}
        artifact['groups'][name] = bundle
        metrics = {"train_reference_rows": len(fit), "fit_sample_rows": len(sample),
                   "calibration_reference_rows": len(calibration), "load_floor_model_only": load_floor,
                   "reference_bounds": {c: {'p001':float(q[i,0]),'p50':float(q[i,2]),'p999':float(q[i,4])} for i,c in enumerate(cols)}}
        for split, mask in [('validation', val_mask), ('test', test_mask)]:
            valid = mask & complete & active
            scores, _, _, _ = score_components(bundle, z.loc[valid].to_numpy())
            metrics[split] = {
                "rows": int(mask.sum()), "scored_rows": int(valid.sum()),
                "unavailable_rows": int((mask & ~complete).sum()),
                "low_load_rows_with_complete_data": int((mask & complete & ~active).sum()),
                "median_score": float(np.median(scores)) if len(scores) else None,
                "high_fraction": float((scores >= .7).mean()) if len(scores) else None,
                "medium_fraction": float(((scores >= .35) & (scores < .7)).mean()) if len(scores) else None,
            }
        report['groups'][name] = metrics
        print(f"{name}: fit={len(fit)}, calibration={len(calibration)}, test={metrics['test']['scored_rows']}", flush=True)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Only write after every group fitted successfully.
    joblib.dump(artifact, output, compress=3)
    report['artifact_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
    report['artifact_version'] = VERSION
    (output.parent / 'training_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
