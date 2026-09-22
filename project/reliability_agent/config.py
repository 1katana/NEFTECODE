from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "reliability_agent" / "artifacts" / "model.joblib"
VERSION = "1.0.0"

# Tags are local to each unit. Hydro signals deliberately have no unverified
# physical descriptions. No process controls or engineering limits are invented.
GROUPS = {
    "avt_p3": {
        "name": "АВТ: режим печи П-3",
        "features": ["avt_t55", "avt_f31", "avt_t33", "avt_f65"],
        "critical": ["avt_t55", "avt_f31"], "load": "avt_f31",
    },
    "avt_k10": {
        "name": "АВТ: режим К-10",
        "features": ["avt_p51", "avt_l43", "avt_f31", "avt_t55", "avt_t48", "avt_t49", "avt_f35", "avt_f36", "avt_f46"],
        "critical": ["avt_p51", "avt_l43", "avt_f31"], "load": "avt_f31",
    },
    "avt_k2": {
        "name": "АВТ: режим К-2",
        "features": ["avt_p_k2", "avt_f65", "avt_t33", "avt_t20", "avt_f12", "avt_f14", "avt_f19", "avt_f64"],
        "critical": ["avt_p_k2", "avt_f65"], "load": "avt_f65",
    },
    "hyd_regime": {
        "name": "24-2000: статистическая оценка режима",
        "features": ["hyd_f2", "hyd_p3", "hyd_t5", "hyd_t6", "hyd_p8", "hyd_t11", "hyd_f15", "hyd_p24", "hyd_f26"],
        "critical": ["hyd_f26", "hyd_t5", "hyd_p3"], "load": "hyd_f26",
        "interpretation": "statistical_only_unverified_tag_mapping",
    },
}
PRESSURE_SOURCES = ["avt_p22", "avt_p23", "avt_p67"]
RAW_FEATURES = sorted({t for g in GROUPS.values() for t in g["features"] if t != "avt_p_k2"} | set(PRESSURE_SOURCES))
DEFAULT_POLICY = {
    "stale_minutes": 60,
    "flatline_minutes": 720,
    "minimum_feature_coverage": 0.8,
    "medium_score": 0.35,
    "high_score": 0.7,
    "anomaly_zero_quantile": 0.90,
    "anomaly_high_quantile": 0.995,
    "controls": {},
    "technology_bounds": {},
}
