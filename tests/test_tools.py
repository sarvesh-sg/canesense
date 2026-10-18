"""Runs the nine tools against the exported data. No model, no network: this is the ground every answer stands on.
Run: DATA_DIR=data python -m unittest tests/test_tools.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'agents'))
os.environ.setdefault('DATA_DIR', os.path.join(ROOT, 'data'))

from canesense import data as D  # noqa: E402
from canesense import tools as T  # noqa: E402


class ToolsOverExport(unittest.TestCase):
    def test_season_summary_has_the_headline_figures(self):
        s = T.season_summary()
        for k in ('cane_crushed_t', 'farmers_who_delivered', 'supply_villages', 'standing_cane_estimate_t_at_90_t_per_ha'):
            self.assertIn(k, s)
        self.assertGreater(s['cane_crushed_t'], 0)

    def test_catchment_gap_is_ranked_and_within_distance(self):
        r = T.catchment_gap(max_km=30, min_cane_ha=100, limit=8)
        rows = r['rows']
        self.assertTrue(rows)
        self.assertLessEqual(len(rows), 8)
        for row in rows:
            self.assertLessEqual(row['km_to_our_mill'], 30)
            self.assertGreaterEqual(row['satellite_cane_ha_2026'], 100)

    def test_village_brief_known_and_unknown(self):
        b = T.village_brief('Ashtha')
        self.assertEqual(b['village'], 'Ashtha')
        self.assertIn('standing_cane_estimate_t', b)
        self.assertEqual(b['standing_cane_estimate_t'], round(b['satellite_cane_ha_by_season']['2026'] * D.YIELD_T_PER_HA))
        self.assertIn('error', T.village_brief('No Such Place'))

    def test_village_names_spoken_and_devanagari(self):
        for spoken in ('Asta', 'Ashta', 'आष्टा', 'कसबे डिग्रज', 'बेडग', 'ಆಷ್ಟಾ', 'ಬೇಡಗ'):
            self.assertIsNotNone(D.find_village(spoken), spoken)
        self.assertIn('did_you_mean', D.not_found('Digraj'))

    def test_district_trend_has_seven_seasons(self):
        r = T.district_trend('Sangli')
        self.assertFalse(r.get('error'), r.get('error'))
        series = next(iter(r['cane_ha_by_season'].values()))
        self.assertGreaterEqual(len(series), 5)

    def test_nearby_cane_not_ours(self):
        r = T.nearby_cane_not_ours(max_km=40, limit=5)
        self.assertTrue(r['rows'])
        for row in r['rows']:
            self.assertLessEqual(row['km_to_our_mill'], 40)

    def test_anomaly_cases_and_detail_use_codes_only(self):
        r = T.anomaly_cases('contractor_advances', limit=5)
        self.assertTrue(r['rows'])
        code = r['rows'][0]['code']
        self.assertRegex(code, r'^C-\d{4}$')
        d = T.case_detail('contractor_advances', code)
        self.assertNotIn('error', d)

    def test_plot_lookup_for_a_picture_village(self):
        r = T.plot_lookup('Ashtha', only_cane=True, limit=5)
        self.assertFalse(r.get('error'), r.get('error'))
        self.assertTrue(r['rows'])
        self.assertTrue(r['picture_urls'])

    def test_no_names_in_export(self):
        import json
        a = json.load(open(os.path.join(os.environ['DATA_DIR'], 'anomalies.json')))
        for row in a['contractor_advances'][:50]:
            self.assertRegex(row['code'], r'^C-\d{4}$')


if __name__ == '__main__':
    unittest.main()
