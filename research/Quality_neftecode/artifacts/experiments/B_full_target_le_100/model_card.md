# QualityAgent model card

- Created: 2026-09-18T20:05:13.615740+00:00
- Target: target_mg_sulfur
- Sulfur limit: 10.0 mg/kg
- Model variant: full
- Regression target maximum: 100.0
- Features: 661
- Calibration: sigmoid, blocked time-series OOF

## Test metrics

- MAE: 1.6354
- Median AE: 1.0024
- RMSE: 2.4842
- PR-AUC: 0.5981
- Recall: 0.5417
- Precision: 0.6500
- Brier: 0.1351

This artifact estimates observed quality. It is not a causal candidate-action model.
