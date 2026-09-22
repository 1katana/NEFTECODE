import copy
import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .agent import ReliabilityAgent
from .config import DEFAULT_ARTIFACT
from .server import make_server


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = ReliabilityAgent()
        cls.state = json.loads(Path(__file__).with_name('examples').joinpath('state.json').read_text(encoding='utf-8'))

    def state_for(self, scope):
        s = copy.deepcopy(self.state)
        s['scope'] = [scope]
        return s

    def test_repeatable_and_reloadable(self):
        one = self.agent.assess(self.state)
        self.assertEqual(one, self.agent.assess(self.state))
        self.assertEqual(one, ReliabilityAgent(DEFAULT_ARTIFACT).assess(self.state))
        json.dumps(one, allow_nan=False)

    def test_missing_critical_is_unknown_not_low(self):
        s = self.state_for('avt_p3')
        s['telemetry']['avt_t55'] = None
        r = self.agent.assess(s)
        self.assertEqual((r['reliability_risk'],r['risk_score'],r['data_confidence']), ('UNKNOWN',None,'LOW'))

    def test_partial_coverage_does_not_hide_missing_asset(self):
        s = copy.deepcopy(self.state)
        del s['telemetry']['avt_t55']
        r = self.agent.assess(s)
        self.assertIsNone(r['risk_score'])
        self.assertIsNotNone(r['assets']['hyd_regime']['risk_score'])

    def test_new_timestamp_does_not_repair_flatline(self):
        s = self.state_for('avt_p3')
        s['data_quality']['avt_t55'].update(age_min=0, flatline_min=800)
        self.assertIsNone(self.agent.assess(s)['risk_score'])

    def test_stale_is_unavailable(self):
        s = self.state_for('avt_p3')
        s['data_quality']['avt_f31']['age_min'] = 61
        self.assertIsNone(self.agent.assess(s)['risk_score'])

    def test_missing_observation_flags_reduces_confidence(self):
        s = self.state_for('avt_p3')
        s.pop('data_quality')
        r = self.agent.assess(s)
        self.assertEqual(r['data_confidence'], 'MEDIUM')

    def test_outlier_does_not_erase_real_high_observation(self):
        s = self.state_for('avt_p3')
        s['telemetry']['avt_t55'] += 50
        s['data_quality']['avt_t55']['flag_outlier'] = True
        r = self.agent.assess(s)
        self.assertEqual(r['reliability_risk'], 'HIGH')
        self.assertEqual(r['data_confidence'], 'MEDIUM')

    def test_candidate_isolated_and_unconfirmed_control_explicit(self):
        before = copy.deepcopy(self.state)
        candidate = {'changes':{'avt_t55':20}, 'mode':'delta'}
        result = self.agent.compare(self.state,candidate)
        self.assertEqual(self.state, before)
        self.assertGreater(result['risk_delta'], 0)
        self.assertFalse(result['candidate']['candidate_controls_supported'])
        self.assertEqual(result['candidate']['data_confidence'], 'LOW')
        self.assertIn('UNCONFIRMED_CONTROL:avt_t55', result['candidate']['warnings'])

    def test_configured_limit_not_overruled_by_model(self):
        value = self.state['telemetry']['avt_t55']
        agent = ReliabilityAgent(policy={'technology_bounds':{'avt_t55':{'max':value-1,'unit':'test_scale','source':'test fixture, not an operating limit'}}})
        r = agent.assess(self.state)
        self.assertEqual((r['reliability_risk'],r['risk_score']), ('HIGH',1.0))
        self.assertTrue(any(f['code']=='TECHNOLOGY_BOUND' for f in r['risk_factors']))

    def test_configured_control_step(self):
        v = self.state['telemetry']['avt_t55']
        a = ReliabilityAgent(policy={'controls':{'avt_t55':{'min':v-50,'max':v+50,'max_delta':1,'unit':'test_scale','source':'test-only synthetic control'}}})
        r = a.assess(self.state, {'changes':{'avt_t55':2},'mode':'delta'})
        self.assertEqual(r['risk_score'],1.0)
        self.assertFalse(r['candidate_controls_supported'])

    def test_pressure_two_sources_survive_one_fault(self):
        s = self.state_for('avt_k2')
        s['telemetry']['avt_p22'] = 240
        s['data_quality']['avt_p22']['flag_stale'] = True
        r = self.agent.assess(s)
        self.assertIsNotNone(r['risk_score'])
        self.assertEqual(r['data_confidence'],'MEDIUM')

    def test_pressure_conflict_is_unknown(self):
        s = self.state_for('avt_k2')
        for i,tag in enumerate(['avt_p22','avt_p23','avt_p67']):
            s['telemetry'][tag] = i*10.0
        self.assertIsNone(self.agent.assess(s)['risk_score'])

    def test_cannot_fake_new_control_channel_or_ambiguous_prefix(self):
        with self.assertRaises(ValueError):
            self.agent.assess(self.state, {'changes':{'avt_unknown':1}})
        with self.assertRaises(ValueError):
            self.agent.assess({'timestamp':'2026-01-01','telemetry':{'F26':1}})

    def test_nonfinite_and_future_source_rejected(self):
        s = copy.deepcopy(self.state)
        s['telemetry']['avt_t55'] = float('nan')
        with self.assertRaises(ValueError):
            self.agent.assess(s)
        s = copy.deepcopy(self.state)
        s['source_timestamp'] = '2099-01-01'
        with self.assertRaises(ValueError):
            self.agent.assess(s)

    def test_http_roundtrip_and_bad_input(self):
        server = make_server(self.agent, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_address[1]}'
        try:
            with urlopen(base+'/health',timeout=5) as r:
                self.assertEqual(json.load(r)['status'],'ready')
            request = Request(base+'/assess',data=json.dumps({'state':self.state}).encode(),headers={'Content-Type':'application/json'})
            with urlopen(request,timeout=5) as r:
                self.assertEqual(json.load(r),self.agent.assess(self.state))
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(base+'/assess',data=b'{}'),timeout=5)
            self.assertEqual(caught.exception.code,400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
