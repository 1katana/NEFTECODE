# QualityAgent model card

- Created: 2026-09-18T20:49:47.855236+00:00
- Target: target_mg_sulfur
- Sulfur limit: 10.0 mg/kg
- Model variant: full
- Regression mode: pak_residual
- Residual scale: 1.0
- Regression target maximum: None
- Features: 661
- Probability output: sigmoid
- Calibration selection: chronological_holdout, blocked time-series OOF
- Regression test rows: 101 / 112

## Test metrics

- MAE: 1.3629
- Median AE: 0.8337
- RMSE: 2.2526
- PR-AUC: 0.5981
- Recall: 0.5417
- Precision: 0.6500
- Brier: 0.1351

This artifact estimates observed quality. It is not a causal candidate-action model.
