import copy
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .config import DEFAULT_ARTIFACT, PRESSURE_SOURCES, RAW_FEATURES
from .model import pressure_consensus, score_components


def canonical_tag(key):
    if not isinstance(key, str):
        raise ValueError('Tag names must be strings')
    key = key.strip().lower().replace(':', '_')
    if key.startswith('242000_'):
        key = 'hyd_' + key[7:]
    if not key.startswith(('avt_', 'hyd_')):
        raise ValueError(f'Tag must contain unit prefix avt_ or hyd_: {key}')
    return key


def number(value, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError('Expected a finite number' + (' or null' if nullable else ''))
    return float(value)


def flag(value):
    if value in (True, False, 0, 1) and not isinstance(value, str):
        return bool(value)
    raise ValueError('Data-quality flags must be booleans or 0/1')


class ReliabilityAgent:
    """A standalone snapshot assessor. No QualityAgent or orchestrator needed.

    Scores are regime proxies. UNKNOWN/null is intentionally distinct from LOW.
    Controls/bounds are optional caller-supplied configuration, never inferred.
    """

    def __init__(self, artifact=DEFAULT_ARTIFACT, policy=None):
        self.artifact = joblib.load(Path(artifact))
        self.policy = copy.deepcopy(self.artifact['policy'])
        if isinstance(policy, (str, Path)):
            policy = json.loads(Path(policy).read_text(encoding='utf-8-sig'))
        if policy:
            unknown = set(policy) - set(self.policy)
            if unknown:
                raise ValueError(f'Unknown policy fields: {sorted(unknown)}')
            self.policy.update(policy)
        self._validate_policy()

    def _validate_policy(self):
        p = self.policy
        if not 0 < number(p['medium_score']) < number(p['high_score']) <= 1:
            raise ValueError('Score thresholds must satisfy 0 < medium < high <= 1')
        if not 0 < number(p['minimum_feature_coverage']) <= 1:
            raise ValueError('minimum_feature_coverage must be in (0,1]')
        for key in ['stale_minutes', 'flatline_minutes']:
            if number(p[key]) <= 0:
                raise ValueError(f'{key} must be positive')
        for section in ['controls', 'technology_bounds']:
            if not isinstance(p[section], dict):
                raise ValueError(f'{section} must be an object')
            normalized = {}
            for tag, item in p[section].items():
                tag = canonical_tag(tag)
                if tag in normalized or not isinstance(item, dict):
                    raise ValueError('Duplicate tag or malformed bound configuration')
                if not item.get('source') or not item.get('unit'):
                    raise ValueError(f'{section}/{tag} needs source and unit')
                for key in ['min', 'max', 'max_delta']:
                    if key in item:
                        number(item[key])
                if 'min' not in item and 'max' not in item:
                    raise ValueError(f'{section}/{tag} needs min or max')
                if 'min' in item and 'max' in item and item['min'] >= item['max']:
                    raise ValueError('min must be smaller than max')
                if 'max_delta' in item and item['max_delta'] < 0:
                    raise ValueError('max_delta must be nonnegative')
                normalized[tag] = copy.deepcopy(item)
            p[section] = normalized

    def _input(self, state):
        if not isinstance(state, dict) or not isinstance(state.get('telemetry'), dict):
            raise ValueError('state.telemetry must be an object')
        timestamp = pd.Timestamp(state.get('timestamp')) if state.get('timestamp') is not None else pd.NaT
        if pd.isna(timestamp):
            raise ValueError('state.timestamp is required')
        telemetry = {}
        for tag, value in state['telemetry'].items():
            tag = canonical_tag(tag)
            if tag == 'avt_p_k2':
                raise ValueError('avt_p_k2 is internal; supply the original pressure channels')
            if tag in telemetry:
                raise ValueError(f'Duplicate canonical tag: {tag}')
            telemetry[tag] = number(value, nullable=True)
        flags = {}
        dq = state.get('data_quality', {})
        if not isinstance(dq, dict):
            raise ValueError('state.data_quality must be an object')
        for key, value in dq.items():
            if isinstance(value, dict):
                tag = canonical_tag(key)
                fields = value
            else:
                suffix = next((s for s in ['_flag_missing', '_flag_stale', '_flag_outlier'] if key.endswith(s)), None)
                if suffix is None:
                    raise ValueError(f'Unrecognized data-quality field: {key}')
                tag, fields = canonical_tag(key[:-len(suffix)]), {suffix[1:]: value}
            record = flags.setdefault(tag, {})
            for name, val in fields.items():
                if name in ['flag_missing', 'flag_stale', 'flag_outlier']:
                    parsed = flag(val)
                elif name in ['age_min', 'flatline_min']:
                    parsed = number(val)
                    if parsed < 0:
                        raise ValueError(f'{name} cannot be negative')
                else:
                    raise ValueError(f'Unrecognized quality field: {name}')
                if name in record and record[name] != parsed:
                    raise ValueError('Contradictory data-quality fields')
                record[name] = parsed
        source_age = 0.
        if state.get('source_timestamp') is not None:
            try:
                source_age = (timestamp - pd.Timestamp(state['source_timestamp'])).total_seconds()/60
            except TypeError as exc:
                raise ValueError('Use consistent timestamp timezones') from exc
            if not np.isfinite(source_age) or source_age < 0:
                raise ValueError('source_timestamp cannot be missing or in the future')
        scopes = state.get('scope', list(self.artifact['groups']))
        if not isinstance(scopes, list) or not scopes or len(set(scopes)) != len(scopes) or any(s not in self.artifact['groups'] for s in scopes):
            raise ValueError('scope must be a nonempty list of distinct known asset IDs')
        return telemetry, flags, source_age, scopes

    def assess(self, state, candidate=None):
        values, quality, source_age, scopes = self._input(state)
        original = values.copy()
        warnings, factors = [], []
        candidate_eligible = True
        changed = set()
        if candidate is not None:
            if not isinstance(candidate, dict) or not isinstance(candidate.get('changes'), dict):
                raise ValueError('candidate.changes must be an object')
            mode = candidate.get('mode', 'absolute')
            if mode not in ['absolute', 'delta']:
                raise ValueError('candidate.mode must be absolute or delta')
            for tag, value in candidate['changes'].items():
                tag = canonical_tag(tag)
                if tag in changed:
                    raise ValueError('Duplicate candidate tag')
                if tag not in RAW_FEATURES or tag not in original or original[tag] is None:
                    raise ValueError(f'Candidate requires a known measured source tag: {tag}')
                changed.add(tag)
                new = number(value)
                if mode == 'delta':
                    new += original[tag]
                values[tag] = number(new)
                control = self.policy['controls'].get(tag)
                if control is None:
                    warnings.append(f'UNCONFIRMED_CONTROL:{tag}')
                    candidate_eligible = False
                else:
                    violation = (('min' in control and new < control['min']) or
                                 ('max' in control and new > control['max']) or
                                 ('max_delta' in control and abs(new-original[tag]) > control['max_delta']))
                    if violation:
                        candidate_eligible = False
                        factors.append({'code':'CONTROL_BOUND', 'kind':'configured_constraint', 'tag':tag,
                                        'value':new, 'score':1., 'source':control['source']})
            warnings.append('CANDIDATE_IS_STATIC_PROXY_NOT_CAUSAL_RESPONSE')
        if not self.policy['technology_bounds']:
            warnings.append('TECHNOLOGY_LIMITS_NOT_CONFIGURED')
        usable, quality_issues, uncertain = {}, {}, set()
        for tag in RAW_FEATURES:
            v = values.get(tag)
            q = quality.get(tag, {})
            reasons = []
            if v is None or q.get('flag_missing', False):
                reasons.append('MISSING')
            if q.get('flag_stale', False) or max(q.get('age_min', 0), source_age) > self.policy['stale_minutes']:
                reasons.append('STALE')
            if q.get('flatline_min', 0) >= self.policy['flatline_minutes']:
                reasons.append('FLATLINE_SUSPECT')
            if q.get('flag_outlier', False):
                # Do not silently erase a potentially real severe condition.
                uncertain.add(tag)
            freshness_known = 'source_timestamp' in state or 'age_min' in q or 'flag_stale' in q
            observation_flags_known = 'flatline_min' in q or 'flag_outlier' in q or 'flag_stale' in q
            if not freshness_known or not observation_flags_known:
                uncertain.add(tag)
            usable[tag] = np.nan if reasons else (v if v is not None else np.nan)
            if reasons:
                quality_issues[tag] = reasons
        pressure = [usable[t] for t in PRESSURE_SOURCES]
        usable['avt_p_k2'] = float(pressure_consensus(pressure, self.artifact['pressure_tolerance'])[0])
        n_press = int(np.isfinite(pressure).sum())
        if n_press < 3 or (n_press and np.nanmax(pressure)-np.nanmin(pressure) > self.artifact['pressure_tolerance']):
            uncertain.add('avt_p_k2')
        if any(t in uncertain for t in PRESSURE_SOURCES):
            uncertain.add('avt_p_k2')
        # Bounds apply to observations only when their source is usable.
        unchecked_limits = []
        for tag, rule in self.policy['technology_bounds'].items():
            if tag not in usable or not np.isfinite(usable[tag]):
                unchecked_limits.append(tag)
                continue
            v = float(usable[tag])
            violation = ('min' in rule and v < rule['min']) or ('max' in rule and v > rule['max'])
            if violation:
                factors.append({'code':'TECHNOLOGY_BOUND', 'kind':'configured_constraint', 'tag':tag,
                                'value':v, 'score':1., 'source':rule['source'], 'unit':rule['unit']})
            elif 'min' in rule and 'max' in rule:
                margin = min(v-rule['min'], rule['max']-v) / (rule['max']-rule['min'])
                if margin < .1:
                    factors.append({'code':'NEAR_TECHNOLOGY_BOUND', 'kind':'configured_margin', 'tag':tag,
                                    'value':v, 'score':float(.7*(1-margin/.1)), 'source':rule['source']})
        results = {}
        for name in scopes:
            bundle = self.artifact['groups'][name]
            spec, cols = bundle['spec'], bundle['spec']['features']
            arr = np.array([usable.get(t, np.nan) for t in cols])
            missing = [t for t,v in zip(cols,arr) if not np.isfinite(v)]
            coverage = float(np.isfinite(arr).mean())
            result = {'name':spec['name'], 'feature_coverage':coverage, 'risk_score':None,
                      'data_confidence':'LOW', 'warnings':[], 'risk_factors':[]}
            if any(t in missing for t in spec['critical']) or coverage < self.policy['minimum_feature_coverage']:
                result['status'] = 'insufficient_data'
                result['warnings'] = ['UNAVAILABLE:'+t for t in missing]
            elif usable[spec['load']] <= bundle['load_floor']:
                result['status'] = 'outside_active_load_scope'
                result['warnings'] = ['LOW_LOAD_OR_TRANSITION_NOT_A_FAILURE_LABEL']
            else:
                imputed = ~np.isfinite(arr)
                arr[imputed] = np.asarray(bundle['fill_values'])[imputed]
                score, anomaly, bounds, by_tag = score_components(bundle, arr[None,:])
                result.update(status='assessed', risk_score=float(score[0]), data_confidence='HIGH',
                              anomaly_score=float(anomaly[0]), reference_tail_score=float(bounds[0]))
                if missing:
                    result['data_confidence'] = 'MEDIUM'
                    result['warnings'].extend('CONTEXT_IMPUTED_FOR_MODEL:'+t for t in missing)
                if any(t in uncertain for t in cols):
                    result['data_confidence'] = 'MEDIUM'
                    result['warnings'].append('INPUT_FLAGS_OR_PRESSURE_CONSENSUS_UNCERTAIN')
                result['warnings'].extend('OUTLIER_FLAG:'+t for t in cols if quality.get(t, {}).get('flag_outlier', False))
                if name == 'hyd_regime':
                    result['data_confidence'] = 'MEDIUM'
                    result['warnings'].append('HYD_MAPPING_UNVERIFIED_STATISTICAL_INTERPRETATION_ONLY')
                for i in np.argsort(-by_tag[0])[:3]:
                    if by_tag[0,i] <= 0 or imputed[i]:
                        continue
                    q = bundle['quantiles'][i]
                    result['risk_factors'].append({'code':'HISTORICAL_TAIL', 'kind':'model_reference',
                        'tag':cols[i], 'value':float(arr[i]), 'score':float(by_tag[0,i]),
                        'direction':'high' if arr[i] > q[3] else 'low',
                        'reference_p001':q[0], 'reference_p999':q[4],
                        'description':'Отклонение от исторической области; не паспортный предел'})
                if anomaly[0] > 0:
                    result['risk_factors'].append({'code':'UNUSUAL_COMBINATION', 'kind':'ml_domain',
                        'score':float(anomaly[0]), 'description':'Нетипичное совместное состояние сигналов группы'})
                if score[0] >= self.policy['high_score']:
                    result['warnings'].append('HIGH_HISTORICAL_DEVIATION_NOT_FAILURE_PROBABILITY')
            results[name] = result
        available = [r['risk_score'] for r in results.values() if r['risk_score'] is not None]
        all_available = len(available) == len(results)
        configured_violation = any(f['code'] in ['TECHNOLOGY_BOUND','CONTROL_BOUND'] for f in factors)
        partial = max([*available, *(f['score'] for f in factors)], default=None)
        risk = partial if (all_available and not unchecked_limits) or configured_violation else None
        confidence = 'HIGH'
        if any(r['data_confidence']=='MEDIUM' for r in results.values()):
            confidence = 'MEDIUM'
        if not all_available or unchecked_limits or not candidate_eligible:
            confidence = 'LOW'
        if unchecked_limits:
            warnings.extend('UNCHECKED_TECHNOLOGY_LIMIT:'+t for t in unchecked_limits)
        for name, r in results.items():
            warnings.extend(name+':'+w for w in r['warnings'])
        if risk is None:
            warnings.append('ASSESSMENT_INCOMPLETE_NOT_LOW_RISK')
        level = 'UNKNOWN' if risk is None else ('HIGH' if risk >= self.policy['high_score'] else 'MEDIUM' if risk >= self.policy['medium_score'] else 'LOW')
        return {
            'reliability_risk':level, 'risk_score':risk, 'data_confidence':confidence,
            'warnings':sorted(set(warnings)), 'timestamp':state['timestamp'],
            'model_version':self.artifact['version'], 'scope':scopes,
            'score_meaning':self.artifact['score_meaning'],
            'partial_risk_score':partial, 'assets':results,
            'risk_factors':factors + [dict(f, asset=k) for k,r in results.items() for f in r['risk_factors']],
            'candidate_id':candidate.get('candidate_id') if candidate else None,
            'candidate_controls_supported':candidate_eligible if candidate is not None else None,
            'observation_issues':{t:r for t,r in quality_issues.items() if any(t in self.artifact['groups'][s]['spec']['features'] or (t in PRESSURE_SOURCES and s=='avt_k2') for s in scopes)},
            'technology_limits_configured':bool(self.policy['technology_bounds']),
        }

    def compare(self, state, candidate):
        before, after = self.assess(state), self.assess(state, candidate)
        a,b = before['risk_score'], after['risk_score']
        return {'current':before, 'candidate':after,
                'current_risk':a, 'candidate_risk':b,
                'risk_delta':b-a if a is not None and b is not None else None,
                'drivers':[{'asset':k, 'current_score':v['risk_score'],
                            'candidate_score':after['assets'][k]['risk_score'],
                            'candidate_factors':after['assets'][k]['risk_factors']}
                           for k,v in before['assets'].items() if v['risk_score'] != after['assets'][k]['risk_score']]}
