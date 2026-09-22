from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from quality_agent.feature_pipeline import SourceData, build_source_features


class DataPreparationTest(unittest.TestCase):
    def test_asof_features_never_read_the_future(self) -> None:
        source = SourceData(
            name="test",
            frame=pd.DataFrame(
                {
                    "date": pd.to_datetime(
                        [
                            "2026-01-01 00:00:00",
                            "2026-01-01 00:10:00",
                            "2026-01-01 00:20:00",
                            "2026-01-01 00:30:00",
                        ]
                    ),
                    "T1": [0.0, 10.0, 20.0, 999.0],
                }
            ),
            cadence_min=10.0,
        )
        samples = pd.Series(pd.to_datetime(["2026-01-01 00:25:00"]))

        features, age = build_source_features(source, samples)

        self.assertEqual(features.loc[0, "test_T1__current"], 20.0)
        self.assertNotIn(999.0, features.loc[0].dropna().tolist())
        self.assertEqual(age[0], 5.0)

    def test_flatline_age_is_explicit_for_pak(self) -> None:
        source = SourceData(
            name="pak_test",
            frame=pd.DataFrame(
                {
                    "date": pd.date_range("2026-01-01", periods=4, freq="10min"),
                    "value": [7.0, 7.0, 7.0, 7.0],
                }
            ),
            cadence_min=10.0,
        )
        samples = pd.Series(pd.to_datetime(["2026-01-01 00:35:00"]))

        features, _ = build_source_features(
            source,
            samples,
            include_flatline_features=True,
            mask_invalid_flatline=True,
        )

        self.assertEqual(features.loc[0, "pak_test_value__current"], 7.0)
        self.assertEqual(features.loc[0, "pak_test_value__flatline_age_min"], 35.0)
        self.assertEqual(features.loc[0, "pak_test_value__flatline_ge_30m"], 1.0)
        self.assertEqual(features.loc[0, "pak_test_value__flatline_ge_60m"], 0.0)
        self.assertEqual(features.loc[0, "pak_test_value__flatline_ge_24h"], 0.0)

    def test_invalid_pak_flatline_masks_value_features_but_keeps_health(self) -> None:
        times = pd.date_range("2024-01-01", periods=12, freq="10min")
        source = SourceData(
            "pak_test",
            pd.DataFrame({"date": times, "value": [7.0] * len(times)}),
            10.0,
        )
        samples = pd.Series([pd.Timestamp("2024-01-01 01:30:00")])

        features, _ = build_source_features(
            source,
            samples,
            include_flatline_features=True,
            mask_invalid_flatline=True,
        )

        self.assertTrue(pd.isna(features.loc[0, "pak_test_value__current"]))
        self.assertTrue(pd.isna(features.loc[0, "pak_test_value__roll_mean_60m"]))
        self.assertEqual(features.loc[0, "pak_test_value__flatline_age_min"], 90.0)
        self.assertEqual(features.loc[0, "pak_test_value__flatline_ge_60m"], 1.0)
        self.assertTrue(np.isnan(features.loc[0, "pak_test_value__lag_60m"]))

    def test_large_pak_step_is_flagged_without_masking_the_measurement(self) -> None:
        source = SourceData(
            "pak_test",
            pd.DataFrame(
                {
                    "date": pd.date_range("2026-01-01", periods=3, freq="10min"),
                    "value": [7.0, 7.2, 12.5],
                }
            ),
            10.0,
        )
        samples = pd.Series([pd.Timestamp("2026-01-01 00:20:00")])

        features, _ = build_source_features(
            source,
            samples,
            include_flatline_features=True,
            mask_invalid_flatline=True,
            jump_abs_threshold=4.0,
        )

        self.assertEqual(features.loc[0, "pak_test_value__current"], 12.5)
        self.assertAlmostEqual(features.loc[0, "pak_test_value__abs_delta_10m"], 5.3)
        self.assertEqual(features.loc[0, "pak_test_value__jump_ge_train_q999"], 1.0)


if __name__ == "__main__":
    unittest.main()
