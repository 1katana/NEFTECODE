from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from .counterfactual import CandidateEffectConfig
from .features import FeatureConfig
from .router import PointPolicy, QualityAgentRouter
from .shadow import ShadowLogger

RuntimeMode = Literal["shadow"]


@dataclass(frozen=True)
class RuntimeConfig:
    mode: RuntimeMode
    primary_artifacts: Path
    telemetry_fallback_artifacts: Path
    point_policy: PointPolicy
    shadow_log: Path
    timeout_ms: int = 2_000
    include_features_in_shadow: bool = True
    candidate_effect_config: CandidateEffectConfig | None = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> RuntimeConfig:
        config_path = Path(path).resolve()
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise TypeError("Runtime config must be a mapping")
        base = config_path.parent

        def resolve(name: str) -> Path:
            value = payload.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Runtime config requires {name}")
            candidate = Path(value)
            return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()

        config = cls(
            mode=payload.get("mode", "shadow"),
            primary_artifacts=resolve("primary_artifacts"),
            telemetry_fallback_artifacts=resolve("telemetry_fallback_artifacts"),
            point_policy=payload.get("point_policy", "pak_passthrough"),
            shadow_log=resolve("shadow_log"),
            timeout_ms=int(payload.get("timeout_ms", 2_000)),
            include_features_in_shadow=bool(payload.get("include_features_in_shadow", True)),
            candidate_effect_config=(
                CandidateEffectConfig.from_yaml(
                    Path(str(payload["candidate_effect_config"])).resolve()
                    if Path(str(payload["candidate_effect_config"])).is_absolute()
                    else (base / str(payload["candidate_effect_config"])).resolve()
                )
                if payload.get("candidate_effect_config")
                else None
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode != "shadow":
            raise ValueError("Only shadow runtime mode is approved")
        if self.point_policy not in {"model", "pak_passthrough"}:
            raise ValueError(f"Unsupported point_policy: {self.point_policy!r}")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        for name, path in {
            "primary_artifacts": self.primary_artifacts,
            "telemetry_fallback_artifacts": self.telemetry_fallback_artifacts,
        }.items():
            if not path.is_dir():
                raise ValueError(f"{name} directory does not exist: {path}")


def create_shadow_router(
    runtime: RuntimeConfig,
    feature_config: FeatureConfig | None = None,
) -> QualityAgentRouter:
    runtime.validate()
    logger = ShadowLogger(
        runtime.shadow_log,
        include_features=runtime.include_features_in_shadow,
    )
    return QualityAgentRouter(
        runtime.primary_artifacts,
        runtime.telemetry_fallback_artifacts,
        feature_config,
        point_policy=runtime.point_policy,
        shadow_logger=logger,
        candidate_effect_config=runtime.candidate_effect_config,
    )


def check_runtime_bundle(runtime: RuntimeConfig) -> dict[str, Any]:
    router = create_shadow_router(runtime)
    primary = router.primary.manifest
    fallback = router.telemetry_fallback.manifest
    errors: list[str] = []
    if primary.get("model_variant") != "full":
        errors.append("PRIMARY_VARIANT_NOT_FULL")
    if fallback.get("model_variant") != "telemetry_only":
        errors.append("FALLBACK_VARIANT_NOT_TELEMETRY_ONLY")
    if runtime.point_policy != "pak_passthrough":
        errors.append("POINT_POLICY_NOT_CONSERVATIVE")
    return {
        "status": "READY_FOR_SHADOW" if not errors else "INVALID",
        "mode": runtime.mode,
        "automatic_promotion": False,
        "point_policy": runtime.point_policy,
        "timeout_ms": runtime.timeout_ms,
        "candidate_effect": {
            "response_time_hours": router.primary.candidate_effect_config.response_time_hours,
            "sulfur_sensitivity": router.primary.candidate_effect_config.sulfur_sensitivity,
        },
        "shadow_log": str(runtime.shadow_log),
        "primary": {
            "path": str(runtime.primary_artifacts),
            "training_id": primary.get("training_id"),
            "schema_version": primary.get("schema_version"),
            "schema_sha256": primary.get("schema_sha256"),
            "model_variant": primary.get("model_variant"),
            "regression_mode": primary.get("regression_mode"),
            "residual_scale": primary.get("residual_scale"),
            "apply_calibrator": primary.get("apply_calibrator"),
        },
        "fallback": {
            "path": str(runtime.telemetry_fallback_artifacts),
            "training_id": fallback.get("training_id"),
            "schema_version": fallback.get("schema_version"),
            "schema_sha256": fallback.get("schema_sha256"),
            "model_variant": fallback.get("model_variant"),
            "regression_mode": fallback.get("regression_mode"),
        },
        "errors": errors,
        "warnings": ["NO_PRODUCTION_CHAMPION", "FUTURE_HOLDOUT_REQUIRED"],
    }
