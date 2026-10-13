"""Tests that need no downloads: classification rules, the EGS fit matrix, the
depth-matched temperature field on a synthetic Earth, and change detection."""
import numpy as np
import pandas as pd

from pipeline import inventory as I
from pipeline import diff as D
from pipeline import tfield as T
from pipeline.states import likely_deviated


def test_likely_deviated_rules():
    # North Dakota: measured depth >= 12,500 ft on a post-2005 well is treated as horizontal
    assert likely_deviated('ND', ['MD', 'MD', 'MD'], [20000, 9000, 13000], [2012, 2012, 1985], ['A 1-2H', 'B 1', 'C 1']).tolist() == [True, False, False]
    # Kansas: >= 7,500 ft and spudded 2010 or later
    assert likely_deviated('KS', ['MD (KGS DEPTH)'] * 2, [9000, 9000], [2012, 1990], ['', '']).tolist() == [True, False]
    # true vertical depth is never flagged
    assert likely_deviated('CO', ['TVD'], [15000], [2015], ['X 1H']).tolist() == [False]


def _inv(cls, t):
    return pd.DataFrame({'cls4': cls, 't_td': t, 'plant69_km': [5.0] * len(cls)})


def test_fit_matrix():
    inv = I.add_fit(_inv(['IN', 'OR', 'PA', 'DA', 'IN', 'PA', 'DA', 'OR', 'IN'],
                         [160, 160, 160, 160, 130, 130, 130, 80, np.nan]))
    assert inv.fit.tolist() == ['A', 'B', 'C', 'D', 'C', 'D', 'D', 'E', 'U']
    assert inv.grade.tolist() == ['egs', 'egs', 'egs', 'egs', 'near', 'near', 'near', 'low', 'nd']


def test_grade_boundaries():
    g = I.grade(pd.Series([150.0, 149.99, 120.0, 119.9, 90.0, 89.9]))
    assert g.tolist() == ['egs', 'near', 'near', 'mod', 'mod', 'low']


def _synthetic_points(n=6000, seed=1):
    rng = np.random.default_rng(seed)
    lat = rng.uniform(36, 38, n)
    lon = rng.uniform(-100, -98, n)
    grad = 25 + 10 * (lat - 36)                       # 25-45 degC/km north-south trend
    z = rng.uniform(500, 4000, n)
    t = 15 + grad * z / 1000 + rng.normal(0, 2, n)
    return pd.DataFrame({'latitude': lat, 'longitude': lon, 'depth_m': z, 'temp_corrected_c': t,
                         'gradient_c_per_km': (t - 15) / z * 1000})


def test_depth_matched_field_recovers_truth():
    pts = _synthetic_points()
    f = T.DepthMatchedField(pts)
    q = f.query(np.array([37.0, 36.5]), np.array([-99.0, -99.0]), np.array([3000.0, 2000.0]))
    truth = np.array([35.0, 30.0])
    assert np.all(np.abs(q.grad.to_numpy() - truth) < 2.0)
    assert q.matched.all()


def test_outlier_is_rejected():
    pts = _synthetic_points()
    bad = pd.DataFrame({'latitude': [37.0], 'longitude': [-99.0], 'depth_m': [3000.0],
                        'temp_corrected_c': [15 + 110 * 3.0], 'gradient_c_per_km': [110.0]})
    f = T.DepthMatchedField(pd.concat([pts, bad], ignore_index=True))
    q = f.query(np.array([37.0]), np.array([-99.0]), np.array([3000.0]))
    assert abs(q.grad.iloc[0] - 35.0) < 3.0           # a co-located 110 degC/km reading does not take over


def test_validation_runs():
    r = T.validate(_synthetic_points(), n=500, min_depth_m=1000)
    assert r['gridwell_depth_matched']['mae_c'] < 5


def test_change_detection():
    prev = pd.DataFrame({'key': ['KS:1', 'KS:2', 'KS:3'], 'st': 'KS', 'fips': '20001', 'cls4': ['IN', 'PA', 'IN'],
                         'fit': 'E', 't_td': 50.0, 'src': 'state'})
    cur = pd.DataFrame({'key': ['KS:1', 'KS:2', 'KS:4'], 'st': 'KS', 'fips': '20001', 'cls4': ['PA', 'PA', 'IN'],
                        'fit': 'E', 't_td': 50.0, 'src': 'state'})
    inv = cur.assign(api='', raw_status='')
    c = D.compare(prev, cur, inv)
    assert c['added_n'] == 1 and c['removed_n'] == 1 and c['reclassified_n'] == 1
    assert c['transitions'] == {'IN→PA': 1}
    assert D.compare(None, cur, inv)['baseline'] is True


def test_year_parsing_handles_arcgis_epoch_ms():
    from pipeline.states import _year
    y = _year(['1262304000000', '1262304000000.0', '2015-03-01', '03/04/1987', '', None])
    assert list(y[:4]) == [2010.0, 2010.0, 2015.0, 1987.0]
    assert y[4:].isna().all()
