#!/bin/sh
set -eu

primary_manifest="/app/Quality_neftecode/artifacts/experiments/H_full_pak_residual_oof_calibration/training_manifest.json"
fallback_manifest="/app/Quality_neftecode/artifacts/experiments/C_telemetry_only/training_manifest.json"
missing=0

for manifest in "$primary_manifest" "$fallback_manifest"; do
    if [ ! -f "$manifest" ]; then
        echo "ERROR: required QualityAgent model bundle is missing: $manifest" >&2
        missing=1
    fi
done

if [ "$missing" -ne 0 ]; then
    echo "Restore the H and C bundles under project/Quality_neftecode/artifacts/experiments and rebuild the image." >&2
    exit 78
fi

exec "$@"
