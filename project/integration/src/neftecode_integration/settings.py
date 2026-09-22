from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from neftecode_orchestrator.enums import QualityProduct


@dataclass(frozen=True)
class IntegrationSettings:
    quality_runtime_config: Path
    shadow_gates_config: Path
    trace_path: Path
    quality_shadow_log_path: Path
    optimizer_control_config: Path
    optimizer_safety_policy: Path
    reliability_policy: Path
    component_timeout_ms: int
    optimization_timeout_ms: int
    max_candidates: int
    max_changed_controls: int
    quality_product: QualityProduct
    cors_origins: tuple[str, ...]
    adapter_modes: dict[str, str]

    @classmethod
    def from_yaml(cls, path: str | Path) -> IntegrationSettings:
        config_path = Path(path).resolve()
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise TypeError("Integration config must be a mapping")
        base = config_path.parent

        def resolve(name: str) -> Path:
            value = payload.get(name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"Integration config requires {name}")
            candidate = Path(value)
            return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()

        modes = payload.get("adapter_modes", {})
        if not isinstance(modes, dict):
            raise TypeError("adapter_modes must be a mapping")
        origins = payload.get("cors_origins", [])
        if not isinstance(origins, list) or not all(isinstance(item, str) for item in origins):
            raise TypeError("cors_origins must be a list of strings")
        settings = cls(
            quality_runtime_config=resolve("quality_runtime_config"),
            shadow_gates_config=resolve("shadow_gates_config"),
            trace_path=resolve("trace_path"),
            quality_shadow_log_path=resolve("quality_shadow_log_path"),
            optimizer_control_config=resolve("optimizer_control_config"),
            optimizer_safety_policy=resolve("optimizer_safety_policy"),
            reliability_policy=resolve("reliability_policy"),
            component_timeout_ms=int(payload.get("component_timeout_ms", 2_000)),
            optimization_timeout_ms=int(payload.get("optimization_timeout_ms", 15_000)),
            max_candidates=int(payload.get("max_candidates", 100)),
            max_changed_controls=int(payload.get("max_changed_controls", 2)),
            quality_product=QualityProduct(payload.get("quality_product", "UNKNOWN")),
            cors_origins=tuple(origins),
            adapter_modes={str(key): str(value) for key, value in modes.items()},
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.component_timeout_ms <= 0:
            raise ValueError("component_timeout_ms must be positive")
        if self.optimization_timeout_ms <= 0:
            raise ValueError("optimization_timeout_ms must be positive")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        if self.max_changed_controls < 1:
            raise ValueError("max_changed_controls must be positive")
        for path in (
            self.quality_runtime_config,
            self.shadow_gates_config,
            self.optimizer_control_config,
            self.optimizer_safety_policy,
            self.reliability_policy,
        ):
            if not path.is_file():
                raise ValueError(f"Required config does not exist: {path}")
        required_modes = {"quality", "reliability", "safety", "optimization"}
        missing = required_modes - self.adapter_modes.keys()
        if missing:
            raise ValueError(f"Missing adapter modes: {sorted(missing)}")

    def public_metadata(self) -> dict[str, Any]:
        return {
            "component_timeout_ms": self.component_timeout_ms,
            "optimization_timeout_ms": self.optimization_timeout_ms,
            "max_candidates": self.max_candidates,
            "max_changed_controls": self.max_changed_controls,
            "quality_product": self.quality_product.value,
            "adapter_modes": self.adapter_modes,
        }
