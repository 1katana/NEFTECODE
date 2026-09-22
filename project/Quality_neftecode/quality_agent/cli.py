from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from .agent import QualityAgent
from .contracts import CandidateAction, ProcessState
from .data_prep import prepare_training_data
from .features import FeatureConfig
from .router import QualityAgentRouter
from .runtime import RuntimeConfig, check_runtime_bundle
from .shadow import ShadowLogger, ShadowPromotionGates, evaluate_shadow_readiness
from .state_adapter import ingest_process_state
from .train import TrainingConfig, train_all

app = typer.Typer(help="QualityAgent: prepare data / train / predict")


@app.command("prepare-data")
def prepare_data_cmd(
    workspace_root: Path = typer.Option(..., exists=True, file_okay=False),
    output_dir: Path = typer.Option("data/processed", file_okay=False),
    feature_anchor_offset_min: int = typer.Option(
        0,
        min=0,
        help="Build features this many minutes before the LIMS timestamp.",
    ),
):
    manifest = prepare_training_data(
        workspace_root,
        output_dir,
        feature_anchor_offset_min=feature_anchor_offset_min,
    )
    typer.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@app.command("train")
def train_cmd(
    train: Path = typer.Option(..., exists=True, help="split_train.csv"),
    val: Path = typer.Option(..., exists=True, help="split_val.csv"),
    test: Path = typer.Option(..., exists=True, help="split_test.csv"),
    out: Path = typer.Option("artifacts"),
    config: Path = typer.Option(None, help="modeling.yaml"),
    schema: Path = typer.Option(None, help="feature_schema.json"),
    model_variant: str = typer.Option(
        "full",
        help="full or telemetry_only",
    ),
    regression_target_max: float | None = typer.Option(
        None,
        help="Optional upper target bound for regression only; classifier keeps all rows.",
    ),
    regression_mode: str = typer.Option(
        "direct",
        help="direct or pak_residual",
    ),
    residual_scale_mode: str = typer.Option(
        "none",
        help="none or blocked_oof_mae; only for pak_residual",
    ),
    calibration_policy: str = typer.Option(
        "always",
        help="always or chronological_holdout",
    ),
    cv_gap_hours: float = typer.Option(6.0, min=0.0),
):
    cfg = FeatureConfig.from_yaml(config) if config else FeatureConfig()
    if schema is None:
        sibling_schema = train.parent / "feature_schema.json"
        schema = sibling_schema if sibling_schema.exists() else None
    metrics = train_all(
        str(train),
        str(val),
        str(test),
        cfg,
        str(out),
        schema_path=str(schema) if schema else None,
        training_config=TrainingConfig(
            model_variant=model_variant,  # type: ignore[arg-type]
            regression_target_max=regression_target_max,
            regression_mode=regression_mode,  # type: ignore[arg-type]
            residual_scale_mode=residual_scale_mode,  # type: ignore[arg-type]
            calibration_policy=calibration_policy,  # type: ignore[arg-type]
            cv_gap_hours=cv_gap_hours,
        ),
    )
    typer.echo(json.dumps(metrics, indent=2, ensure_ascii=False))


@app.command("train-matrix")
def train_matrix_cmd(
    train: Path = typer.Option(..., exists=True, help="split_train.csv"),
    val: Path = typer.Option(..., exists=True, help="split_val.csv"),
    test: Path = typer.Option(..., exists=True, help="split_test.csv"),
    out: Path = typer.Option("artifacts/experiments"),
    config: Path = typer.Option(None, help="modeling.yaml"),
    schema: Path = typer.Option(None, help="feature_schema.json"),
    cv_gap_hours: float = typer.Option(6.0, min=0.0),
):
    """Run primary, target-sensitivity and telemetry-only experiments."""
    cfg = FeatureConfig.from_yaml(config) if config else FeatureConfig()
    if schema is None:
        sibling_schema = train.parent / "feature_schema.json"
        schema = sibling_schema if sibling_schema.exists() else None
    if schema is None:
        raise typer.BadParameter("feature_schema.json is required")

    experiments = {
        "A_full_all_targets": TrainingConfig(
            model_variant="full",
            cv_gap_hours=cv_gap_hours,
        ),
        "B_full_target_le_100": TrainingConfig(
            model_variant="full",
            regression_target_max=100.0,
            cv_gap_hours=cv_gap_hours,
        ),
        "C_telemetry_only": TrainingConfig(
            model_variant="telemetry_only",
            cv_gap_hours=cv_gap_hours,
        ),
    }
    summary: dict[str, dict] = {}
    for name, training_config in experiments.items():
        summary[name] = train_all(
            str(train),
            str(val),
            str(test),
            cfg,
            str(out / name),
            schema_path=str(schema),
            training_config=training_config,
        )
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("predict")
def predict_cmd(
    state_json: Path = typer.Option(..., exists=True),
    candidate_json: Path = typer.Option(None, exists=True),
    artifacts: Path = typer.Option("artifacts"),
    telemetry_fallback_artifacts: Path | None = typer.Option(
        None,
        help="Optional telemetry-only bundle used when sulfur PAK is invalid.",
    ),
    config: Path = typer.Option(None),
    history_jsonl: Path = typer.Option(None, exists=True, help="Past ProcessState JSONL"),
    point_policy: str = typer.Option(
        "model",
        help="model or pak_passthrough; requires telemetry fallback routing.",
    ),
    shadow_log: Path | None = typer.Option(
        None,
        help="Append prediction and both model outputs to this JSONL file.",
    ),
):
    cfg = FeatureConfig.from_yaml(config) if config else FeatureConfig()
    if point_policy != "model" and telemetry_fallback_artifacts is None:
        raise typer.BadParameter("point-policy requires telemetry-fallback-artifacts")
    shadow_logger = ShadowLogger(shadow_log) if shadow_log else None
    agent = (
        QualityAgentRouter(
            artifacts,
            telemetry_fallback_artifacts,
            cfg,
            point_policy=point_policy,  # type: ignore[arg-type]
            shadow_logger=shadow_logger,
        )
        if telemetry_fallback_artifacts
        else QualityAgent(artifacts, cfg)
    )

    if history_jsonl:
        for line_number, line in enumerate(
            history_jsonl.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                historical_state = ProcessState.model_validate_json(line)
            except ValueError as error:
                raise typer.BadParameter(
                    f"Invalid ProcessState at history line {line_number}: {error}"
                ) from error
            ingest_process_state(agent.history, historical_state)

    state = ProcessState.model_validate_json(state_json.read_text(encoding="utf-8"))
    cand = (
        CandidateAction.model_validate_json(candidate_json.read_text(encoding="utf-8"))
        if candidate_json
        else None
    )
    result = agent.predict(state, cand)
    typer.echo(result.model_dump_json(indent=2))
    if isinstance(agent, QualityAgentRouter) and agent.last_shadow_prediction_id:
        typer.echo(f"shadow_prediction_id={agent.last_shadow_prediction_id}", err=True)


@app.command("shadow-log-lims")
def shadow_log_lims_cmd(
    shadow_log: Path = typer.Option(...),
    timestamp: str = typer.Option(..., help="LIMS sample collection timestamp."),
    value: float = typer.Option(..., help="LIMS sulfur, mg/kg."),
    sample_id: str | None = typer.Option(None),
):
    logger = ShadowLogger(shadow_log)
    logger.log_lims(sample_timestamp=timestamp, sulfur_mg_kg=value, sample_id=sample_id)
    typer.echo("LIMS sample appended")


@app.command("shadow-summary")
def shadow_summary_cmd(
    shadow_log: Path = typer.Option(..., exists=True),
    tolerance_min: float = typer.Option(10.0, min=0.0),
    sulfur_limit: float = typer.Option(10.0),
):
    summary = ShadowLogger(shadow_log).summary(
        tolerance_min=tolerance_min,
        sulfur_limit=sulfur_limit,
    )
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("shadow-evaluate")
def shadow_evaluate_cmd(
    shadow_log: Path = typer.Option(..., exists=True),
    gates_config: Path = typer.Option(
        "configs/shadow_gates.yaml",
        exists=True,
        help="Predeclared evidence and quality gates.",
    ),
    tolerance_min: float = typer.Option(10.0, min=0.0),
    sulfur_limit: float = typer.Option(10.0),
):
    payload = yaml.safe_load(gates_config.read_text(encoding="utf-8")) or {}
    gate_values = payload.get("promotion_gates", payload)
    if not isinstance(gate_values, dict):
        raise typer.BadParameter("promotion_gates must be a mapping")
    try:
        gates = ShadowPromotionGates(**gate_values)
        gates.validate()
    except (TypeError, ValueError) as error:
        raise typer.BadParameter(f"Invalid promotion gates: {error}") from error
    logger = ShadowLogger(shadow_log)
    summary = logger.summary(tolerance_min=tolerance_min, sulfur_limit=sulfur_limit)
    result = {
        "summary": summary,
        "readiness": evaluate_shadow_readiness(summary, gates),
    }
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command("runtime-check")
def runtime_check_cmd(
    runtime_config: Path = typer.Option(
        "configs/runtime_shadow.yaml",
        exists=True,
        help="Pinned shadow runtime configuration.",
    ),
):
    try:
        config = RuntimeConfig.from_yaml(runtime_config)
        result = check_runtime_bundle(config)
    except (OSError, TypeError, ValueError) as error:
        raise typer.BadParameter(f"Invalid runtime bundle: {error}") from error
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "READY_FOR_SHADOW":
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
