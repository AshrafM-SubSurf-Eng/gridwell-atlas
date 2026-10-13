"""Well sources -> county-assigned frames: the six state registries and the USGS
Documented Unplugged Orphaned Oil and Gas Well dataset (DOW, 2022, CC0)."""
from __future__ import annotations
import numpy as np, pandas as pd
from .counties import assign_county
from .geo import PolygonIndex
from .paths import STATIC
from .states import load_all
from .welltypes import classify

DOW_FILE = STATIC / 'dow_2022_wells.csv.gz'


def _sane(lat, lon):
    return lat.between(18, 72) & lon.between(-180, -60)


def load_registry(counties, feats, index=None):
    a = load_all()
    a = a[a.cls.notna() | a.orphan_list].copy()
    bad = ~_sane(a.lat, a.lon)
    a.loc[bad, ['lat', 'lon']] = np.nan
    idx = index or PolygonIndex(feats, counties.fips)
    a['county'] = a.county_src.fillna('').astype(str).str.replace(r'\s*\(.*\)$', '', regex=True)
    a.loc[a.county.eq(''), 'county'] = None
    a = a.rename(columns={'state': 'st'})
    tmp = a.rename(columns={'st': 'state', 'lat': 'latitude', 'lon': 'longitude'})
    fips, method, qa = assign_county(tmp, counties, idx)
    a['fips'] = fips.values
    a['county_method'] = method
    a['coord_county'] = qa.by_pip.values
    cmp = qa.dropna()
    return a, {'rows': int(len(a)), 'classified': int(a.cls.notna().sum()),
               'state_orphan_list': int(a.orphan_list.sum()), 'no_coordinates': int(a.lat.isna().sum()),
               'county_by_name': int((method == 'name').sum()), 'county_by_point': int((method == 'point').sum()),
               'county_unassigned': int((method == 'unassigned').sum()),
               'name_point_compared': int(len(cmp)),
               'name_point_agreement': float((cmp.by_name == cmp.by_pip).mean()) if len(cmp) else None,
               'rows_by_state': a.st.value_counts().to_dict()}


def load_dow(counties, feats, index=None):
    w = pd.read_csv(DOW_FILE, dtype={'api10': str})
    idx = index or PolygonIndex(feats, counties.fips)
    fips, method, qa = assign_county(w, counties, idx)
    w['fips'] = fips.values
    w['county_method'] = method
    w['coord_county'] = qa.by_pip.values
    w['type_class'] = w.well_type.map(classify)
    cmp = qa.dropna()
    return w, {'wells_in': int(len(w)), 'county_by_name': int((method == 'name').sum()),
               'county_by_point': int((method == 'point').sum()),
               'county_unassigned_offshore': int((method == 'unassigned').sum()),
               'name_point_agreement': float((cmp.by_name == cmp.by_pip).mean()),
               'name_point_compared': int(len(cmp))}
