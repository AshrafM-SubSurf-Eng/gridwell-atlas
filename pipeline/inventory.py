"""One abandoned-well inventory, screened for Enhanced Geothermal Systems (EGS).

Why one inventory
-----------------
An orphaned well is an abandoned well whose operator is unknown or insolvent
(IOGCC 2021: orphan wells are idle wells "for which the operator is unknown or
insolvent"; 42 U.S.C. 15907(a)(5)). Orphaned wells are therefore a subset of
abandoned wells, not a separate population. GRIDWELL keeps them in one inventory
and sorts every well by abandonment type, which is what decides how the wellbore
can be reached and who can sign for it:

  IN  Inactive, unplugged, operator of record   (temporarily abandoned / idle / shut-in)
  OR  Orphaned, unplugged                       (no responsible operator; state or USGS DOW list)
  PA  Plugged and abandoned                     (incl. orphans since plugged with public money)
  DA  Dry and abandoned                         (drilled, never produced)

Sources and de-duplication
--------------------------
* Six state registries (OK, KS, CA, NY, CO, ND) give every type.
* The USGS DOW (2022) gives documented unplugged orphaned wells in 26 states.
  In the registry states a DOW well is matched to its registry record by 10-digit
  API (Kansas DOW rows carry KCC numbers, not APIs, so they are matched by
  location to the state's orphan-programme wells, <= MATCH_M metres). A match keeps
  the registry's newer status and sets the orphan flag; unmatched DOW wells are
  added as type OR.
* Within a registry, records sharing a 10-digit API are one wellbore (the 14-digit
  suffix is sidetrack/event); the record with the highest suffix is kept.

EGS screen
----------
Temperature at a well's own total depth (TD) comes from the ORPHANHEAT gradient
field, using vertical depth only. Wells with no total depth, or with measured
depth on a record that looks horizontal, are not graded at TD; they still get
temperatures at 5,000, 10,000 and 15,000 ft (1,524, 3,048 and 4,572 m).
"""
from __future__ import annotations
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
from . import thermal as oh_thermal
from .loads import Nearest
from .paths import RAW
from .welltypes import classify

REGISTRY_STATES = ('OK', 'KS', 'CA', 'NY', 'CO', 'ND')
CLASSES = ('IN', 'OR', 'PA', 'DA')
MATCH_M = 100.0
FT = 0.3048
CFG = oh_thermal.ThermalConfig()
SURFACE_T = CFG.surface_temp_c                  # 15 degC (59 degF)
REF_DEPTHS_FT = (5000, 10000, 15000)
GRID_KM = 10.0                                  # 6.2 mi to a >=69 kV interconnection

# Thermal grade of a well at its own vertical total depth.
#   egs   >= 150 degC (302 degF): the lower bound of the EGS temperature range
#         (150-300 degC, JASON 2013 via Simmons 2015) and the 'high' class of
#         Gardner et al. (2025)
#   near  120-150 degC (248-302 degF): binary-cycle grade; EGS power after deepening
#   mod   90-120 degC (194-248 degF): low-temperature binary or direct use
#   low   < 90 degC (194 degF)
#   nd    not graded: no usable vertical depth
GRADES = (('egs', 150.0), ('near', 120.0), ('mod', 90.0), ('low', -1e9))
EGS_T = 150.0

# EGS fit: abandonment type (how the wellbore can be reached, who can sign for
# it) crossed with thermal grade. Rationale and evidence: docs/METHODS.md and the paper.
FIT = {
    'A': 'Best fit: inactive, unplugged, with an operator of record, and at least 302 °F (150 °C) at total depth',
    'B': 'Strong fit after ownership transfer: orphaned, unplugged, at least 302 °F (150 °C) at total depth',
    'C': 'Conditional: plugged well at EGS grade (plugs must be drilled out), or unplugged well at 248–302 °F (120–150 °C) that needs deepening',
    'D': 'Limited: dry hole at 248 °F (120 °C) or more, or plugged well at 248–302 °F (120–150 °C); value is mainly as data or a sidetrack start',
    'E': 'Below EGS grade at total depth: under 248 °F (120 °C)',
    'U': 'Not graded: no vertical total depth on record',
}


def n10(s: pd.Series) -> pd.Series:
    d = s.astype('string').str.replace(r'\D', '', regex=True)
    return d.where(d.str.len() > 0)


def _xyz(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def dedupe_registry(ab: pd.DataFrame):
    a = ab.copy()
    digits = n10(a.api)
    a['api10'] = digits.str.slice(0, 10).where(digits.str.len() >= 10)
    a['_sfx'] = pd.to_numeric(digits.str.slice(10, 14).where(digits.str.len() == 14), errors='coerce').fillna(-1)
    before = a.groupby('st').size()
    has = a.api10.notna()
    keep = a[has].sort_values(['st', 'api10', '_sfx']).drop_duplicates(['st', 'api10'], keep='last')
    out = pd.concat([keep, a[~has]]).sort_index()
    removed = (before - out.groupby('st').size()).fillna(0).astype(int).to_dict()
    return out.drop(columns=['_sfx']), {'registry_rows_in': int(len(a)), 'registry_dup_api_removed': removed,
                                        'registry_rows_out': int(len(out))}


def _ks_type(s):
    if not isinstance(s, str):
        return ''
    return s.split(' / ')[0].split('(')[0].strip()


def unify(reg_in: pd.DataFrame, dow_in: pd.DataFrame):
    qa = {}
    reg, qd = dedupe_registry(reg_in)
    qa.update(qd)
    reg = reg.reset_index(drop=True)
    reg['src'] = 'state'
    reg['dow_id'] = None
    dow = dow_in.copy().reset_index(drop=True)
    k = n10(dow.api10)
    dow['k'] = k.str.slice(0, 10).where(k.str.len() >= 10)
    dow['matched'] = -1

    key = {(s, kk): i for i, (s, kk) in enumerate(zip(reg.st, reg.api10)) if isinstance(kk, str)}
    for j, (s, kk) in enumerate(zip(dow.state, dow.k)):
        if s in REGISTRY_STATES and isinstance(kk, str):
            i = key.get((s, kk))
            if i is not None:
                dow.at[j, 'matched'] = i
    for st in REGISTRY_STATES:
        need = dow.index[(dow.state == st) & (dow.matched < 0) & dow.k.isna() & dow.latitude.notna()]
        if len(need) == 0:
            continue
        cand = reg.index[(reg.st == st) & reg.lat.notna() & (reg.orphan_list.astype(bool) | reg.public_plug.astype(bool))]
        if len(cand) == 0:
            continue
        tree = cKDTree(_xyz(reg.lat[cand], reg.lon[cand]))
        d, ii = tree.query(_xyz(dow.latitude[need], dow.longitude[need]), k=1)
        taken = set()
        for j, dist, i in sorted(zip(need, d * 6371008.8, ii), key=lambda t: t[1]):
            ri = cand[i]
            if dist <= MATCH_M and ri not in taken:
                dow.at[j, 'matched'] = ri
                taken.add(ri)
        qa[f'dow_{st}_spatial_matched'] = int(len(taken))
        qa[f'dow_{st}_spatial_candidates'] = int(len(need))
        left = dow.index[(dow.state == st) & (dow.matched < 0) & dow.latitude.notna()]
        rest = [c for c in cand if c not in taken]
        if len(left) and len(rest):
            t2 = cKDTree(_xyz(reg.lat[rest], reg.lon[rest]))
            d2, _ = t2.query(_xyz(dow.latitude[left], dow.longitude[left]), k=1)
            qa[f'dow_{st}_possible_duplicates_max'] = int((d2 * 6371008.8 <= 400).sum())
            qa[f'dow_{st}_unmatched_added'] = int(len(left))

    m = dow[dow.matched >= 0]
    reg['dow'] = False
    reg.loc[m.matched.values, 'dow'] = True
    reg.loc[m.matched.values, 'dow_id'] = m.orphanheat_id.values
    reg.loc[m.matched.values, 'src'] = 'state+DOW'
    qa['dow_matched_to_registry'] = int(len(m))
    qa['dow_matched_by_state'] = m.state.value_counts().to_dict()

    orphan = reg.orphan_list.astype(bool) | reg.dow
    cls = reg.cls.copy()
    cls[cls.isna() & orphan] = 'OR'
    cls[(cls == 'IN') & orphan] = 'OR'
    reg['cls4'] = cls
    reg['orphan'] = orphan
    reg['orphan_since_plugged'] = orphan & reg.cls.isin(['PA', 'DA'])
    reg['type_class'] = [classify(_ks_type(s) if st == 'KS' else t) for st, s, t in zip(reg.st, reg.raw_status, reg.raw_type)]

    u = dow[dow.matched < 0]
    add = pd.DataFrame({
        'st': u.state.values, 'api': u.api10.values, 'api10': u.k.values,
        'lat': u.latitude.values, 'lon': u.longitude.values,
        'cls': None, 'cls4': 'OR', 'orphan': True, 'orphan_list': False, 'orphan_since_plugged': False,
        'public_plug': False, 'dow': True, 'dow_id': u.orphanheat_id.values, 'src': 'DOW',
        'raw_status': u.well_status.astype('string').values, 'raw_type': u.well_type.astype('string').values,
        'td_ft': np.nan, 'td_m': np.nan, 'depth_basis': None, 'dev': False, 'spud_yr': np.nan, 'operator': None,
        'county': u.county.values, 'fips': u.fips.values, 'county_method': u.county_method.values,
        'coord_county': u.coord_county.values, 'type_class': u.type_class.values,
    })
    qa['dow_added_unmatched'] = int(len(add))
    qa['dow_added_by_state'] = u.state.value_counts().to_dict()
    inv = pd.concat([reg, add], ignore_index=True)
    inv.loc[inv.cls4 == 'DA', 'type_class'] = 'Dry hole'
    inv['coverage'] = np.where(inv.st.isin(REGISTRY_STATES), 'registry', 'DOW')
    inv['dev'] = inv.dev.fillna(False).astype(bool)
    inv['key'] = make_key(inv)
    qa['inventory'] = int(len(inv))
    qa['by_class'] = inv.cls4.value_counts().to_dict()
    qa['orphan_flag'] = int(inv.orphan.sum())
    qa['orphan_since_plugged'] = int(inv.orphan_since_plugged.sum())
    qa['duplicate_keys'] = int(inv.key.duplicated().sum())
    return inv, qa


def make_key(inv: pd.DataFrame) -> pd.Series:
    """Stable well key used to detect wells that join the inventory between refreshes:
    state + 10-digit API where there is one, else the DOW id, else rounded location."""
    api = inv.api10.astype('string')
    dow = inv.dow_id.astype('string')
    loc = (inv.lat.round(5).astype('string') + ',' + inv.lon.round(5).astype('string'))
    k = inv.st.astype('string') + ':' + api.where(api.notna(), 'dow' + dow.where(dow.notna(), 'xy' + loc.fillna('?')))
    # records without API, DOW id or coordinates: disambiguate by row order within the state
    dup = k.duplicated(keep=False)
    if dup.any():
        k[dup] = k[dup] + '#' + inv[dup].groupby(k[dup]).cumcount().astype('string')
    return k


def add_nearest(inv, places, plants):
    big = places[places['pop'] >= 10_000].reset_index(drop=True)
    hv = plants[plants.kv >= 69].reset_index(drop=True)
    m = inv.lat.notna() & inv.lon.notna()
    for name, ref in (('load', places), ('load10k', big), ('plant', plants), ('plant69', hv)):
        d, i = Nearest(ref).query(inv.lat[m].values, inv.lon[m].values)
        inv[f'{name}_km'] = np.nan
        inv[f'{name}_i'] = np.nan
        inv.loc[m, f'{name}_km'] = d
        inv.loc[m, f'{name}_i'] = i
    # plant69_i indexes the >=69 kV subset; map it back to the full plant table
    hv_index = plants.index[plants.kv >= 69].to_numpy()
    ok = inv.plant69_i.notna()
    inv.loc[ok, 'plant69_i'] = hv_index[inv.loc[ok, 'plant69_i'].astype(int).to_numpy()]
    big_index = places.index[places['pop'] >= 10_000].to_numpy()
    ok = inv.load10k_i.notna()
    inv.loc[ok, 'load10k_i'] = big_index[inv.loc[ok, 'load10k_i'].astype(int).to_numpy()]
    return inv


# ---------------------------------------------------------------- thermal
def load_bht(path=None):
    path = path or (RAW / 'bht' / 'Bottom_Hole_Temperature_Data.csv')
    df = pd.read_csv(path, usecols=['Depth', 'Lat', 'Long', 'BHT'])
    unit, ev = oh_thermal.infer_depth_unit(df.Depth.to_numpy(float), df.BHT.to_numpy(float), CFG)
    depth_m = df.Depth if unit == 'm' else df.Depth * FT
    raw = pd.DataFrame({'latitude': df.Lat, 'longitude': df.Long, 'depth_m': depth_m, 'temp_c': df.BHT})
    pts, audit = oh_thermal.prepare_bht(raw, CFG)
    audit['depth_unit'] = unit
    audit['depth_unit_evidence'] = ev
    return pts, audit


def add_thermal(inv: pd.DataFrame, bht_path=None):
    """Temperatures from the depth-matched field (tfield.py): at each well's own
    vertical total depth, and at 5,000, 10,000 and 15,000 ft for every well."""
    from . import tfield
    pts, audit = load_bht(bht_path)
    field = tfield.DepthMatchedField(pts)
    ok = (inv.lat.notna() & inv.lon.notna()).to_numpy()
    lat, lon = inv.lat.to_numpy(float)[ok], inv.lon.to_numpy(float)[ok]
    vd = inv.td_m.where((inv.td_m > 0) & ~inv.dev)                     # usable vertical depth
    inv['vd_m'] = vd

    def put(col, values):
        inv[col] = np.nan
        inv.loc[ok, col] = values

    for zft in REF_DEPTHS_FT:
        q = field.query(lat, lon, zft * FT)
        put(f't{zft // 1000}k', SURFACE_T + q.grad.to_numpy() * zft * FT / 1000.0)
        if zft == 10000:
            put('grad10k', q.grad.to_numpy())
    # at total depth (wells without one get the 10,000 ft estimate as their gradient)
    has = vd.notna().to_numpy()[ok]
    z = np.where(has, vd.to_numpy()[ok], 10000 * FT)
    q = field.query(lat, lon, z)
    put('grad', q.grad.to_numpy())
    put('grad_n', q.n.to_numpy())
    put('grad_km', q.nearest_km.to_numpy())
    put('grad_sd', q.sd.to_numpy())
    put('matched', q.matched.to_numpy().astype(float))
    g = inv.grad.where(inv.grad > 0)
    inv['t_td'] = np.where(vd.notna(), SURFACE_T + g * vd / 1000.0, np.nan)
    # depth to 302 degF (150 degC): two fixed-point passes with the depth-matched field
    zq = (EGS_T - SURFACE_T) / inv.grad10k.where(inv.grad10k > 0) * 1000.0
    for _ in range(2):
        zz = np.clip(zq.to_numpy()[ok], 300, 9000)
        qq = field.query(lat, lon, np.nan_to_num(zz, nan=3048.0))
        gg = np.where(qq.grad.to_numpy() > 0, qq.grad.to_numpy(), np.nan)
        zq = pd.Series(np.nan, index=inv.index)
        zq[ok] = (EGS_T - SURFACE_T) / gg * 1000.0
    inv['z_egs_m'] = zq
    inv['deepen_m'] = np.clip(inv.z_egs_m - vd, 0, None)
    inv['hs'] = np.clip(vd / inv.z_egs_m, 0, 1)             # share of the drilling to 302 degF already done
    inv['conf'] = oh_thermal.confidence_band(inv.grad_n.fillna(0).to_numpy(), inv.grad_km.to_numpy(), CFG)
    inv.loc[inv.grad.isna(), 'conf'] = 'none'
    audit['supported_pct'] = round(float(inv.grad.notna().mean() * 100), 2)
    audit['depth_matched_pct_of_graded'] = round(float(inv.loc[vd.notna(), 'matched'].mean() * 100), 2)
    audit['points_used'] = int(len(pts))
    audit['validation'] = {f'ge_{d}m': tfield.validate(pts, n=20_000, min_depth_m=d, seed=7) for d in (1000, 2500)}
    audit['method'] = ('Harrison-corrected BHT gradients; for each target depth z, BHTs measured within 0.75z-1.25z, '
                       '12 nearest within 75 km, 3-MAD outlier rejection, inverse-distance-squared weights with a 1 km floor; '
                       'fallback to all depths when fewer than 3 match.')
    return inv, audit


def grade(t_c: pd.Series) -> pd.Series:
    out = pd.Series('nd', index=t_c.index, dtype=object)
    for name, lo in reversed(GRADES):
        out[t_c >= lo] = name
    out[t_c.isna()] = 'nd'
    return out


def add_fit(inv: pd.DataFrame) -> pd.DataFrame:
    g = grade(inv.t_td)
    c = inv.cls4
    fit = pd.Series('U', index=inv.index, dtype=object)
    fit[g.isin(['mod', 'low'])] = 'E'
    fit[(c == 'DA') & g.isin(['egs', 'near'])] = 'D'
    fit[(c == 'PA') & (g == 'near')] = 'D'
    fit[(c == 'PA') & (g == 'egs')] = 'C'
    fit[c.isin(['IN', 'OR']) & (g == 'near')] = 'C'
    fit[(c == 'OR') & (g == 'egs')] = 'B'
    fit[(c == 'IN') & (g == 'egs')] = 'A'
    inv['grade'] = g
    inv['fit'] = fit
    inv['grid'] = inv.plant69_km <= GRID_KM
    return inv
