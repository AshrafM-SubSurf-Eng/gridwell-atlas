"""County universe (Census cartographic boundary file, 2025 vintage) and the
well -> county assignment shared by the orphaned and abandoned sections."""
from __future__ import annotations
import numpy as np, pandas as pd
from .paths import RAW
from .geo import read_dbf, read_shp_polygons, PolygonIndex
from .norm import norm_county

CB = str(RAW / 'cb' / 'cb_2025_us_county_500k')
GAZ = RAW / '2025_Gaz_counties_national.txt'

def load_counties():
    rows = read_dbf(CB + '.dbf')
    feats = read_shp_polygons(CB + '.shp')
    c = pd.DataFrame(rows)[['GEOID', 'NAME', 'NAMELSAD', 'STUSPS', 'STATE_NAME', 'ALAND']]
    c.columns = ['fips', 'name', 'namelsad', 'st', 'state', 'aland']
    c['aland_km2'] = c.aland.astype(float) / 1e6
    g = pd.read_csv(GAZ, sep='|', dtype=str)
    g.columns = [x.strip() for x in g.columns]
    c = c.merge(g[['GEOID', 'INTPTLAT', 'INTPTLONG']].rename(columns={'GEOID': 'fips'}), on='fips', how='left')
    c['INTPTLAT'] = pd.to_numeric(c.INTPTLAT); c['INTPTLONG'] = pd.to_numeric(c.INTPTLONG)
    # territories missing from the national gazetteer: use polygon bbox centre
    for i in c.index[c.INTPTLAT.isna()]:
        allp = np.vstack(feats[i]) if feats[i] else np.array([[np.nan, np.nan]])
        c.loc[i, 'INTPTLONG'] = (allp[:, 0].min() + allp[:, 0].max()) / 2
        c.loc[i, 'INTPTLAT'] = (allp[:, 1].min() + allp[:, 1].max()) / 2
    c['lat'] = c.INTPTLAT.astype(float); c['lon'] = c.INTPTLONG.astype(float)
    c['key'] = c.namelsad.map(norm_county)
    c['key_short'] = c.name.map(norm_county)
    return c.drop(columns=['INTPTLAT', 'INTPTLONG', 'aland']), feats

# Known spelling variants in state submissions (each one checked by hand
# against the well coordinates before being added).
ALIASES = {('OH', 'green'): 'greene'}

def assign_county(df, counties, index, st_col='state', county_col='county'):
    """Name match within state first; point-in-polygon second. Returns
    (fips, method) and a QA frame comparing the two where both exist."""
    c = counties
    # county names: prefer non-'city' entities when a county and an independent
    # city share a stem (St. Louis, Baltimore, Fairfax, Richmond, Roanoke, Franklin)
    lut = {}
    for r in c.sort_values('namelsad', key=lambda s: s.str.endswith(' city')).itertuples():
        lut.setdefault((r.st, r.key_short), r.fips)
        lut.setdefault((r.st, r.key), r.fips)
    k = df[county_col].map(norm_county)
    k = [ALIASES.get((s, x), x) for s, x in zip(df[st_col], k)]
    by_name = pd.Series([lut.get((s, x)) for s, x in zip(df[st_col], k)], index=df.index)
    by_pip = pd.Series(index.locate(df.longitude.values, df.latitude.values), index=df.index)
    fips = by_name.where(by_name.notna(), by_pip)
    method = np.where(by_name.notna(), 'name', np.where(by_pip.notna(), 'point', 'unassigned'))
    # a point-in-polygon county in a different state than the record is not trusted
    st_of = dict(zip(c.fips, c.st))
    bad_state = (method == 'point') & (fips.map(st_of) != df[st_col]).values
    fips[bad_state] = None
    method[bad_state] = 'unassigned'
    qa = pd.DataFrame({'by_name': by_name, 'by_pip': by_pip})
    return fips, method, qa
