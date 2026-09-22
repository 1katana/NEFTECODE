"""Build a clearly labelled what-if blend around observed historical telemetry."""

from __future__ import annotations

import json
from copy import deepcopy

import pandas as pd
from integration.scripts.build_historical_request import ROOT, build

AT = pd.Timestamp("2026-05-15 12:00:00")
OUTPUT = ROOT / "integration/examples/illustrative_blend_20260515_1200.json"


def main() -> None:
    request, evidence = build(AT)
    demo = json.loads((ROOT / "integration/runtime/demo_request.json").read_text(encoding="utf-8"))
    blending = deepcopy(demo["process_state"]["quality"]["blending"])
    request["run_id"] = "illustrative-blend-20260515-1200"
    request["input_source"] = "SYNTHETIC"
    current = request["process_state"]
    current["quality"]["blending"] = blending
    current["current_controls"].update(
        {component["share_control"]: component["share_pct"] for component in blending["components"]}
    )
    current["current_controls"][blending["additive_control"]] = blending["additive_pct"]
    evidence.update(
        {
            "input_source": "SYNTHETIC",
            "observed_part": "Historical AVT, 24-2000 and PAK at 10-minute intervals",
            "assumed_part": "Illustrative 80/20 blending recipe and component properties copied from integration/runtime/demo_request.json",
            "not_an_operational_recipe": True,
            "limitations": [
                *evidence["limitations"],
                "Blend shares, component properties and cost proxies are assumptions, not plant measurements",
                "A KEEP decision validates software flow only; it does not validate blending physics or action safety",
            ],
        }
    )
    OUTPUT.write_text(json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    OUTPUT.with_name(OUTPUT.stem + "_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
