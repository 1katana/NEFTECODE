# QualityAgent model card

- Created: 2026-09-18T20:17:14.464173+00:00
- Target: target_mg_sulfur
- Sulfur limit: 10.0 mg/kg
- Model variant: full
- Regression mode: direct
- Regression target maximum: None
- Features: 661
- Calibration: sigmoid, blocked time-series OOF

## Test metrics

- MAE: 1.9707
- Median AE: 1.4567
- RMSE: 2.7826
- PR-AUC: 0.3385
- Recall: 1.0000
- Precision: 0.2143
- Brier: 0.1672

This artifact estimates observed quality. It is not a causal candidate-action model.
