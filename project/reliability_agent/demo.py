"""Reproducible historical assessments and explicitly hypothetical edge cases."""
import copy
import json
from pathlib import Path

from .agent import ReliabilityAgent
from .config import ROOT
from .data import read_telemetry, snapshot


def main():
    out = ROOT / 'reliability_agent' / 'examples'
    out.mkdir(exist_ok=True)
    agent = ReliabilityAgent()
    values, ages = read_telemetry()
    dates = ['2023-02-01 12:00', '2023-06-01 12:00', '2023-12-01 12:00',
             '2024-04-01 12:00', '2024-10-01 12:00', '2025-03-01 12:00',
             '2025-09-01 12:00', '2026-02-01 12:00', '2026-06-20 12:00', '2026-08-01 12:00']
    results = []
    for i, at in enumerate(dates,1):
        state = snapshot(values, ages, at)
        response = agent.assess(state)
        result = {'case':f'history_{i:02}', 'origin':'actual_historical_state', 'state':state, 'response':response}
        (out / f'history_{i:02}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        results.append({'timestamp':at, 'level':response['reliability_risk'], 'score':response['risk_score'], 'confidence':response['data_confidence']})
    baseline = snapshot(values, ages, dates[0])
    candidate = {'candidate_id':'hypothetical_temperature_plus_20', 'mode':'delta', 'changes':{'avt_t55':20}}
    # This is an input-sensitivity demonstration, not a confirmed control action.
    request = {'state':baseline, 'candidate':candidate}
    (out/'request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'state.json').write_text(json.dumps(baseline,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'candidate.json').write_text(json.dumps(candidate,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'comparison.json').write_text(json.dumps(agent.compare(**request),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    missing = copy.deepcopy(baseline)
    missing['telemetry']['avt_t55'] = None
    (out/'missing_signal.json').write_text(json.dumps({'state':missing,'response':agent.assess(missing)},ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
