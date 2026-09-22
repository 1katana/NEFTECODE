from __future__ import annotations

from statistics import NormalDist

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    CandidateAction,
    ProcessState,
    ProductQualityMetrics,
    QualityAssessment,
    QualityProduct,
)


class BlendComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    share_pct: float = Field(ge=0.0, le=100.0)
    share_control: str | None = None
    use_hydrotreated_sulfur: bool = False
    sulfur_mg_kg: float | None = Field(default=None, ge=0.0)
    t95_c: float = Field(gt=0.0)
    density_kg_m3: float = Field(gt=0.0)
    cetane_number: float = Field(gt=0.0)
    relative_cost: float = Field(default=1.0, gt=0.0)

    @model_validator(mode="after")
    def require_sulfur_source(self) -> BlendComponent:
        if not self.use_hydrotreated_sulfur and self.sulfur_mg_kg is None:
            raise ValueError("component requires sulfur_mg_kg or use_hydrotreated_sulfur")
        return self


class BlendPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade: str = Field(pattern=r"^(SUMMER|WINTER)$")
    components: list[BlendComponent] = Field(min_length=2)
    additive_pct: float = Field(default=0.0, ge=0.0)
    additive_control: str = "cetane_additive_pct"
    cetane_gain_per_pct: float = Field(default=1.5, ge=0.0)
    additive_relative_cost: float = Field(default=100.0, gt=0.0)


def _candidate_value(
    candidate: CandidateAction | None,
    control: str | None,
    default: float,
) -> float:
    if candidate is None or control is None:
        return default
    return float(candidate.changes.get(control, default))


def assess_commercial_blend(
    hydrotreated: QualityAssessment,
    state: ProcessState,
    candidate: CandidateAction | None = None,
) -> QualityAssessment:
    """Evaluate an editable linear blending scenario for commercial diesel."""

    raw_plan = state.quality.get("blending")
    if not isinstance(raw_plan, dict):
        return hydrotreated.model_copy(
            update={
                "quality_prediction": None,
                "prediction_lower": None,
                "prediction_upper": None,
                "violation_probability": None,
                "product": QualityProduct.COMMERCIAL_DIESEL,
                "metrics": None,
                "warnings": sorted({*hydrotreated.warnings, "BLENDING_PLAN_MISSING"}),
            }
        )

    plan = BlendPlan.model_validate(raw_plan)
    shares = [
        _candidate_value(candidate, component.share_control, component.share_pct)
        for component in plan.components
    ]
    share_sum = sum(shares)
    denominator = share_sum if share_sum > 0 else 100.0
    additive_pct = _candidate_value(candidate, plan.additive_control, plan.additive_pct)

    hydro_mean = hydrotreated.quality_prediction
    hydro_lower = hydrotreated.prediction_lower
    hydro_upper = hydrotreated.prediction_upper
    sulfur = t95 = density = cetane = base_cost = 0.0
    hydro_weight = 0.0
    for component, share in zip(plan.components, shares, strict=True):
        weight = share / denominator
        component_sulfur = (
            hydro_mean if component.use_hydrotreated_sulfur else component.sulfur_mg_kg
        )
        if component_sulfur is None:
            return hydrotreated.model_copy(
                update={
                    "quality_prediction": None,
                    "prediction_lower": None,
                    "prediction_upper": None,
                    "violation_probability": None,
                    "product": QualityProduct.COMMERCIAL_DIESEL,
                    "grade": plan.grade,
                    "metrics": None,
                    "warnings": sorted(
                        {*hydrotreated.warnings, "HYDROTREATED_SULFUR_UNAVAILABLE_FOR_BLEND"}
                    ),
                }
            )
        sulfur += weight * component_sulfur
        t95 += weight * component.t95_c
        density += weight * component.density_kg_m3
        cetane += weight * component.cetane_number
        base_cost += weight * component.relative_cost
        if component.use_hydrotreated_sulfur:
            hydro_weight += weight

    cetane += additive_pct * plan.cetane_gain_per_pct
    relative_cost = base_cost + additive_pct / 100.0 * plan.additive_relative_cost
    lower = None
    upper = None
    if hydro_mean is not None and hydro_lower is not None and hydro_upper is not None:
        lower = sulfur + hydro_weight * (hydro_lower - float(hydro_mean))
        upper = sulfur + hydro_weight * (hydro_upper - float(hydro_mean))
    probability = hydrotreated.violation_probability
    if lower is not None and upper is not None:
        sigma = max((upper - lower) / (2.0 * 1.2815515655446004), 0.05)
        probability = 1.0 - NormalDist(mu=sulfur, sigma=sigma).cdf(10.0)

    metrics = ProductQualityMetrics(
        sulfur_mg_kg=round(sulfur, 3),
        t95_c=round(t95, 3),
        density_kg_m3=round(density, 3),
        cetane_number=round(cetane, 3),
        blend_share_sum_pct=round(share_sum, 3),
        additive_pct=round(additive_pct, 4),
        relative_cost=round(relative_cost, 4),
    )
    return hydrotreated.model_copy(
        update={
            "quality_prediction": metrics.sulfur_mg_kg,
            "prediction_lower": None if lower is None else round(max(lower, 0.0), 3),
            "prediction_upper": None if upper is None else round(max(upper, 0.0), 3),
            "violation_probability": (
                None if probability is None else round(min(max(float(probability), 0.0), 1.0), 4)
            ),
            "product": QualityProduct.COMMERCIAL_DIESEL,
            "grade": plan.grade,
            "metrics": metrics,
            "warnings": sorted(
                {
                    *hydrotreated.warnings,
                    "BLENDING_LINEAR_PROXY",
                    "BLENDING_INPUT_NOT_PLANT_RECIPE",
                }
            ),
        }
    )
