# QualityAgent model card

- Created: 2026-09-18T20:05:56.923155+00:00
- Target: target_mg_sulfur
- Sulfur limit: 10.0 mg/kg
- Model variant: telemetry_only
- Regression target maximum: None
- Features: 644
- Calibration: sigmoid, blocked time-series OOF

## Test metrics

- MAE: 1.5888
- Median AE: 1.0441
- RMSE: 2.4140
- PR-AUC: 0.5897
- Recall: 0.6667
- Precision: 0.6400
- Brier: 0.1294

This artifact estimates observed quality. It is not a causal candidate-action model.
