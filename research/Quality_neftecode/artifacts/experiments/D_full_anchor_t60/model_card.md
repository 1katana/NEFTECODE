# QualityAgent model card

- Created: 2026-09-18T20:16:29.526761+00:00
- Target: target_mg_sulfur
- Sulfur limit: 10.0 mg/kg
- Model variant: full
- Regression mode: direct
- Regression target maximum: None
- Features: 661
- Calibration: sigmoid, blocked time-series OOF

## Test metrics

- MAE: 1.9020
- Median AE: 1.3286
- RMSE: 2.6993
- PR-AUC: 0.4170
- Recall: 0.7500
- Precision: 0.2857
- Brier: 0.1595

This artifact estimates observed quality. It is not a causal candidate-action model.
