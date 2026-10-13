"""GRIDWELL Atlas build: one abandoned-well inventory screened for Enhanced
Geothermal Systems (EGS). Every number the page shows is written here from the
official files, so the page cannot drift from the data.

Data files keep SI units (metres, degC, km); the page and the paper show field
units first with SI in brackets.

    python -m pipeline.build [--prev-snapshot PATH]
"""
from __future__ import annotations
import argparse, json, time
from datetime import date
import numpy as np, pandas as pd
from . import ec, inventory as I
from .counties import load_counties
from .geo import PolygonIndex
from .grid import load_plants
from .loads import load_places
from .paths import BUILD, SITE_DATA, MANIFEST
from .wells import load_registry, load_dow
from . import diff as D

CLASSES = I.CLASSES
FITS = tuple(I.FIT)
GRADE_KEYS = ('egs', 'near', 'mod', 'low', 'nd')
F_BINS = np.arange(50, 451, 25)            # degF bins for temperature at total depth
N_PER_FIT = 20                             # candidate wells kept per county and fit tier
CAND_COLS = ['key', 'api', 'lat', 'lon', 'cls', 'orphan', 'src', 'status', 'type', 'td_ft', 'basis', 'dev', 'spud',
             'grad', 't_td', 'deepen_m', 'hs', 't10k', 't15k', 'conf', 'grad_n', 'grad_km', 'load_i', 'load_km',
             'plant_i', 'plant_km', 'plant69_i', 'plant69_km', 'operator', 'public', 'orphan_plugged', 'fit', 'new']


def q(x, ps=(10, 25, 50, 75, 90), nd=1):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return [round(float(v), nd) for v in np.percentile(x, ps)] if len(x) else None


def r(v, nd=1):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if np.isfinite(v) else None


def ii(v):
    return int(v) if v is not None and pd.notna(v) else None


def s_or(v, n=60):
    return v[:n] if isinstance(v, str) else ''


def c2f(c):
    return np.asarray(c, float) * 9 / 5 + 32


def clean(o):
    if isinstance(o, float):
        return o if np.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.floating):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def hist_f(t_c):
    t = c2f(pd.Series(t_c).dropna())
    if not len(t):
        return None
    return np.histogram(np.clip(t, F_BINS[0], F_BINS[-1] - 0.01), bins=F_BINS)[0].tolist()


def matrix(d):
    return {c: {g: int(((d.cls4 == c) & (d.grade == g)).sum()) for g in GRADE_KEYS} for c in CLASSES}


def class_block(d):
    v = d[d.vd_m.notna()]
    return {'n': int(len(d)), 'vd_n': int(len(v)), 'td': q(v.td_ft, nd=0), 'ttd': q(v.t_td), 'dp': q(v.deepen_m, nd=0),
            't10': q(d.t10k), 't15': q(d.t15k), 'op': int(d.operator.fillna('').astype(str).str.strip().str.len().gt(0).sum()),
            'w69': int(d.grid.sum()), 'e150': int((v.t_td >= 150).sum()), 'e120': int((v.t_td >= 120).sum()),
            'spud': r(d.spud_yr.median(), 0), 'hist': hist_f(v.t_td)}


def well_row(x, new_keys):
    return [x.key, s_or(x.api, 20), r(x.lat, 5), r(x.lon, 5), x.cls4, int(bool(x.orphan)), x.src, s_or(x.raw_status, 48),
            x.type_class, r(x.td_ft, 0), s_or(x.depth_basis, 16) or None, int(bool(x.dev)), ii(x.spud_yr),
            r(x.grad, 2), r(x.t_td), r(x.deepen_m, 0), r(x.hs, 3), r(x.t10k), r(x.t15k), x.conf,
            ii(x.grad_n) or 0, r(x.grad_km), ii(x.load_i), r(x.load_km), ii(x.plant_i), r(x.plant_km),
            ii(x.plant69_i), r(x.plant69_km), s_or(x.operator, 40), int(bool(x.public_plug)),
            int(bool(x.orphan_since_plugged)), x.fit, int(x.key in new_keys)]


def main(prev_snapshot=None, out_site=True):
    t0 = time.time()
    counties, feats = load_counties()
    index = PolygonIndex(feats, counties.fips)
    places = load_places()
    plants = load_plants()

    reg, qa_reg = load_registry(counties, feats, index)
    dow, qa_dow = load_dow(counties, feats, index)
    inv, qa_u = I.unify(reg, dow)
    inv = I.add_nearest(inv, places, plants)
    inv, qa_t = I.add_thermal(inv)
    inv = I.add_fit(inv)
    inv['td_ft'] = inv.td_m / I.FT

    sa = ec.statistical_area().set_index('fips')
    cc, _ = ec.coal_closure_by_county()
    cc = cc.set_index('fips')
    inv['ec26'] = inv.fips.isin(set(sa.index[sa.ec2025 == 1]))

    # ------------------------------------------------ change detection
    snap = D.snapshot(inv)
    snap_path = BUILD / 'snapshot.csv.gz'
    snap.to_csv(snap_path, index=False, compression={'method': 'gzip', 'mtime': 0})
    prev = D.read_snapshot(prev_snapshot) if prev_snapshot else None
    changes = D.compare(prev, snap, inv)
    new_keys = set(changes.get('_added_keys', []))
    new_by_fips = changes.get('added_by_fips', {})

    reg_states = list(I.REGISTRY_STATES)
    dow_states = sorted(set(dow.state.dropna()) - set(reg_states))

    # ------------------------------------------------ county records
    recs, cands, used_places, used_plants = [], {}, set(), set()
    groups = {k: v for k, v in inv[inv.fips.notna()].groupby('fips')}
    for row in counties.itertuples():
        f = row.fips
        rec = {'f': f, 'n': row.namelsad, 'st': row.st, 's': row.state, 'la': r(row.lat, 3), 'lo': r(row.lon, 3),
               'km2': r(row.aland_km2, 0),
               'cov': 'registry' if row.st in reg_states else ('DOW' if row.st in dow_states else None)}
        if f in sa.index:
            e = sa.loc[f]
            iv = lambda v: int(v) if pd.notna(v) else None
            rec['ec'] = {'y26': iv(e.ec2025), 'v1': iv(e.ec2025_v1), 'v2': iv(e.ec2025_v2),
                         'msa1': e.msa_v1 if isinstance(e.msa_v1, str) else None,
                         'msa2': e.msa_v2 if isinstance(e.msa_v2, str) else None,
                         'ur1': r(e.ur2025_v1, 2), 'ur2': r(e.ur2025_v2, 2), 'urn': r(e.urnat2025, 2),
                         'ffe1': iv(e.ffe2025_v1), 'ffe2': iv(e.ffe2025_v2),
                         'y25': iv(e.ec2024), 'y24': iv(e.ec2023), 'y23': iv(e.ec2022)}
        else:
            rec['ec'] = None
        if f in cc.index:
            c = cc.loc[f]
            rec['cc'] = {'tr': int(c.tracts), 'cc': int(c.cc_tracts), 'org': int(c.cc_origin_tracts),
                         'list': (c.cc_list if isinstance(c.cc_list, list) else [])[:40]}
        else:
            rec['cc'] = None
        if f in groups:
            d = groups[f]
            v = d[d.vd_m.notna()]
            rec['w'] = {
                'n': int(len(d)), 'c': {k: int((d.cls4 == k).sum()) for k in CLASSES},
                'fit': {k: int((d.fit == k).sum()) for k in FITS},
                'fitg': {k: int(((d.fit == k) & d.grid).sum()) for k in FITS},
                'm': matrix(d), 'orf': int(d.orphan.sum()), 'orp': int(d.orphan_since_plugged.sum()),
                'pub': int(d.public_plug.astype(bool).sum()), 'dow': int(d.dow.astype(bool).sum()),
                'td_n': int((d.td_m > 0).sum()), 'vd_n': int(len(v)), 'dev': int(d.dev.sum()), 'td': q(v.td_ft, nd=0),
                'g': q(d.grad, nd=2), 'gsd': r(d.grad_sd.median(), 2), 'gn': r(d.grad_n.median(), 0),
                'gkm': r(d.grad_km.median(), 1), 'conf': {k: int(n) for k, n in d.conf.value_counts().items()},
                't5': q(d.t5k), 't10': q(d.t10k), 't15': q(d.t15k), 'zegs': q(d.z_egs_m, nd=0),
                'pl': q(d.plant_km), 'pl69': q(d.plant69_km), 'load': q(d.load_km), 'load10k': q(d.load10k_km),
                'w69': int(d.grid.sum()), 'cl': {k: class_block(d[d.cls4 == k]) for k in CLASSES if (d.cls4 == k).any()},
                'types': {k: int(n) for k, n in d.type_class.value_counts().items()},
                'new': int(new_by_fips.get(f, 0)),
            }
            order = {k: i for i, k in enumerate(FITS)}
            dd = d.assign(_o=d.fit.map(order), _t=d.t_td.fillna(-999), _x=d.t10k.fillna(-999))
            top = (dd.sort_values(['_o', '_t', '_x'], ascending=[True, False, False])
                     .groupby('fit', group_keys=False).head(N_PER_FIT))
            new_here = dd[dd.key.isin(new_keys)].head(N_PER_FIT)
            top = pd.concat([top, new_here]).drop_duplicates('key').sort_values(['_o', '_t', '_x'], ascending=[True, False, False])
            cands[f] = [well_row(x, new_keys) for x in top.itertuples()]
            used_places.update(int(v) for v in top.load_i.dropna())
            used_plants.update(int(v) for v in pd.concat([top.plant_i, top.plant69_i]).dropna())
        else:
            rec['w'] = None
        recs.append(rec)

    pl_tab = {int(i): [places.NAME[i], places.USPS[i], int(places['pop'][i])] for i in sorted(used_places)}
    gp_tab = {int(i): [plants.name[i], plants.st[i], r(plants.kv[i]), r(plants.mw[i]), plants.tech[i],
                       plants.ba[i] if isinstance(plants.ba[i], str) else ''] for i in sorted(used_plants)}

    # ------------------------------------------------ national statistics
    s = {'generated': date.today().isoformat(), 'version': '0.2.0'}
    s['counties'] = int(len(counties))
    s['ec2026_counties'] = int((sa.ec2025 == 1).sum())
    s['ec2025_counties'] = int((sa.ec2024 == 1).sum())
    s['ec2024_counties'] = int((sa.ec2023 == 1).sum())
    s['ec2023_counties'] = int((sa.ec2022 == 1).sum())
    s['urnat2025'] = float(sa.urnat2025.dropna().iloc[0])
    s['cc_tracts'] = int(cc.cc_tracts.sum())
    s['cc_counties'] = int((cc.cc_tracts > 0).sum())
    s['registry_states'] = reg_states
    s['dow_states'] = dow_states
    s['fit_labels'] = I.FIT
    s['qa'] = {'registry': qa_reg, 'dow': qa_dow, 'unify': qa_u,
               'thermal': {k: v for k, v in qa_t.items() if k != 'depth_unit_evidence'},
               'thermal_depth_unit_evidence': qa_t.get('depth_unit_evidence')}
    v = inv[inv.vd_m.notna()]
    s['inv'] = {
        'n': int(len(inv)), 'counties': int(inv.fips.nunique()), 'states': int(inv.st.nunique()),
        'by_class': {k: int((inv.cls4 == k).sum()) for k in CLASSES},
        'by_fit': {k: int((inv.fit == k).sum()) for k in FITS},
        'by_fit_grid': {k: int(((inv.fit == k) & inv.grid).sum()) for k in FITS},
        'by_fit_grid_ec': {k: int(((inv.fit == k) & inv.grid & inv.ec26).sum()) for k in FITS},
        'matrix': matrix(inv),
        'by_cov': {k: {c: int(((inv.coverage == k) & (inv.cls4 == c)).sum()) for c in CLASSES} for k in ('registry', 'DOW')},
        'by_state': {st: {'c': {c: int((g.cls4 == c).sum()) for c in CLASSES}, 'fit': {k: int((g.fit == k).sum()) for k in FITS},
                          'vd_n': int(g.vd_m.notna().sum())} for st, g in inv.groupby('st')},
        'orphan_flag': int(inv.orphan.sum()), 'orphan_since_plugged': int(inv.orphan_since_plugged.sum()),
        'public_plug': int(inv.public_plug.astype(bool).sum()),
        'td_n': int((inv.td_m > 0).sum()), 'vd_n': int(len(v)), 'dev_n': int(inv.dev.sum()),
        'dev_by_state': inv[inv.dev].st.value_counts().to_dict(),
        'vd_median_ft': r(v.td_ft.median(), 0), 'vd_states': sorted(v.st.unique().tolist()),
        'grad_median': r(inv.grad.median(), 2), 'grad_supported_pct': qa_t['supported_pct'],
        'w69': int(inv.grid.sum()), 'pl69_median_km': r(inv.plant69_km.median()), 'ec26': int(inv.ec26.sum()),
        'spud_median': r(inv.spud_yr.median(), 0),
    }
    cls_stats = {}
    for k in CLASSES:
        d = inv[inv.cls4 == k]
        t = d[d.vd_m.notna()]
        o = {'n': int(len(d)), 'vd_n': int(len(t)), 'td_q': q(t.td_ft, nd=0), 'ttd_q': q(t.t_td),
             'deepen_q_m': q(t.deepen_m, nd=0), 'hs_q': q(t.hs, nd=3), 't10_q': q(d.t10k), 't15_q': q(d.t15k),
             'op_known': int(d.operator.fillna('').astype(str).str.strip().str.len().gt(0).sum()),
             'w69': int(d.grid.sum()), 'ec26': int(d.ec26.sum()), 'orphan_flag': int(d.orphan.sum()),
             'dow': int(d.dow.astype(bool).sum()), 'spud_q': q(d.spud_yr, nd=0),
             'vd_by_state': {st: int(n) for st, n in t.st.value_counts().items()},
             'ge_10000ft': int((t.td_ft >= 10000).sum()), 'hist': hist_f(t.t_td),
             'types': {kk: int(n) for kk, n in d.type_class.value_counts().items()}}
        for T in (90, 120, 150):
            o[f'ttd_ge_{T}'] = int((t.t_td >= T).sum())
            o[f't10_ge_{T}'] = int((d.t10k >= T).sum())
            o[f't15_ge_{T}'] = int((d.t15k >= T).sum())
        cls_stats[k] = o
    s['cls'] = cls_stats
    ks = inv[(inv.st == 'KS') & inv.vd_m.notna()]
    s['ks_depth_by_class_ft'] = {k: q(ks[ks.cls4 == k].td_ft, nd=0) for k in CLASSES}
    top = inv[inv.fit.isin(['A', 'B'])]
    s['top'] = {'by_state': top.groupby(['st', 'fit']).size().unstack(fill_value=0).to_dict('index'),
                'counties': top.fips.value_counts().head(12).to_dict(),
                'grid_counties': top[top.grid].fips.value_counts().head(12).to_dict(),
                'grid_ec_counties': top[top.grid & top.ec26].fips.value_counts().head(12).to_dict()}
    s['plants'] = {'operable': int(len(plants)), 'kv69': int((plants.kv >= 69).sum()),
                   'geothermal_plants': int(plants.geo.sum()), 'geothermal_mw': r(plants[plants.geo == 1].mw.sum())}
    s['places'] = {'incorporated': int(len(places)), 'pop10k': int((places['pop'] >= 10_000).sum())}
    s['units'] = {'egs_t_c': I.EGS_T, 'grid_km': I.GRID_KM, 'ref_depths_ft': list(I.REF_DEPTHS_FT),
                  'f_bins': F_BINS.tolist(), 'surface_t_c': I.SURFACE_T}
    s['changes'] = {k: v for k, v in changes.items() if not k.startswith('_')}

    meta = {'built': date.today().isoformat(), 'version': '0.2.0',
            'public_url': 'https://ashrafm-subsurf-eng.github.io/gridwell-atlas/',
            'repository': 'https://github.com/AshrafM-SubSurf-Eng/gridwell-atlas',
            'sources': json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None,
            'refresh': {'cadence': 'monthly', 'cron_utc': '17 9 3 * *',
                        'note': 'State registries are re-downloaded on the 3rd of each month; federal reference layers are '
                                'pinned by checksum and checked for new vintages on the same run.'}}

    out = SITE_DATA if out_site else BUILD
    dump = lambda name, obj, **kw: json.dump(clean(obj), open(out / name, 'w'), allow_nan=False, **kw)
    dump('counties.json', recs, separators=(',', ':'))
    dump('candidates.json', {'cols': CAND_COLS, 'rows': cands, 'places': pl_tab, 'plants': gp_tab}, separators=(',', ':'))
    dump('stats.json', s, indent=1)
    dump('changes.json', {k: v for k, v in changes.items() if k != '_added_keys'}, indent=1)
    dump('meta.json', meta, indent=1)
    import shutil
    from .paths import SOURCES, STATIC
    shutil.copyfile(SOURCES, out / 'sources.json')
    if (STATIC / 'counties.topo.json').exists():
        shutil.copyfile(STATIC / 'counties.topo.json', out / 'counties.topo.json')
    inv.to_pickle(BUILD / 'inventory.pkl')
    print(json.dumps(clean({k: s[k] for k in ('inv', 'changes')}), indent=1)[:6000])
    print('built in', round(time.time() - t0, 1), 's')
    return inv, s


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--prev-snapshot', default=None)
    a = ap.parse_args()
    main(a.prev_snapshot)
