"""Per-well lookup index for the atlas page.

Every well with a 10-digit API number is written to one small JSON file named after
the first five digits of its API number (two for the state, three for the county), so
the page fetches only the file for the county a user asks about. API numbers are the
public, permanent identifier of a U.S. oil or gas well; a company's AFE number is an
internal budget code and lease well numbers repeat, so neither is used.

    site/data/wells/index.json   shard list, column names, build date
    site/data/wells/ref.json     names of the towns and power plants that wells point to
    site/data/wells/SSCCC.json   rows for API state code SS, county code CCC; a county
                                 with more than MAX_ROWS wells is split further by the
                                 next digit (SSCCCD.json)

The folder is not committed to git (it is large and changes every month); the
monthly refresh packs it as wells.tar.gz on the dated release and the page
deploy unpacks the latest one.
"""
from __future__ import annotations
import json, shutil
from pathlib import Path
import numpy as np, pandas as pd

WCOLS = ['api10', 'api', 'name', 'st', 'fips', 'cls', 'orph', 'orpp', 'pub', 'src', 'status', 'type', 'wtype',
         'op', 'spud', 'td', 'basis', 'dev', 'lat', 'lon', 't_td', 'grade', 'fit', 't5', 't10', 't15', 'zegs',
         'deep', 'grad', 'gn', 'gkm', 'conf', 'p69', 'p69_i', 'town', 'town_i', 'grid', 'ec']
MAX_ROWS = 15000


def _num(s, nd):
    v = pd.to_numeric(s, errors='coerce').round(nd)
    return v.astype('Int64') if nd == 0 else v


def _str(s):
    return s.astype('string').str.strip().replace('', pd.NA)


def well_rows(inv: pd.DataFrame) -> pd.DataFrame:
    """One row per well with a 10-digit API number, in WCOLS order."""
    a10 = inv.api10.astype('string')
    ok = a10.str.fullmatch(r'\d{10}').fillna(False).astype(bool)
    d = inv[ok]
    g = lambda c: d[c] if c in d else pd.Series(pd.NA, index=d.index)
    out = pd.DataFrame({
        'api10': d.api10.astype('string'),
        # the full 12- or 14-digit number only where the source gives more than 10 digits
        'api': (lambda x: x.where(x.str.len() > 10))(d.api.astype('string').str.replace(r'\D', '', regex=True)),
        'name': _str(g('well_name')),
        'st': d.st, 'fips': d.fips,
        'cls': d.cls4,
        'orph': d.orphan.astype(bool).astype(int),
        'orpp': d.orphan_since_plugged.astype(bool).astype(int),
        'pub': d.public_plug.fillna(False).astype(bool).astype(int),
        'src': d.src,
        'status': _str(d.raw_status), 'type': _str(d.raw_type), 'wtype': _str(d.type_class),
        'op': _str(d.operator),
        'spud': _num(d.spud_yr, 0),
        'td': _num(d.td_ft, 0), 'basis': _str(d.depth_basis),
        'dev': d.dev.astype(bool).astype(int),
        'lat': _num(d.lat, 5), 'lon': _num(d.lon, 5),
        't_td': _num(d.t_td, 1), 'grade': d.grade, 'fit': d.fit,
        't5': _num(d.t5k, 1), 't10': _num(d.t10k, 1), 't15': _num(d.t15k, 1),
        'zegs': _num(d.z_egs_m, 0), 'deep': _num(d.deepen_m, 0),
        'grad': _num(d.grad, 1), 'gn': _num(d.grad_n, 0), 'gkm': _num(d.grad_km, 1), 'conf': _str(d.conf),
        'p69': _num(d.plant69_km, 1), 'p69_i': _num(d.plant69_i, 0),
        'town': _num(d.load10k_km, 1), 'town_i': _num(d.load10k_i, 0),
        'grid': d.grid.fillna(False).astype(bool).astype(int), 'ec': d.ec26.fillna(False).astype(bool).astype(int),
    })
    # a well's API number is unique within its state; keep one row per number
    return out.sort_values('api10').drop_duplicates('api10', keep='first')[WCOLS]


def _records(df: pd.DataFrame) -> list:
    obj = df.astype(object).where(df.notna(), None)
    return obj.values.tolist()


def write_well_index(inv: pd.DataFrame, places: pd.DataFrame, plants: pd.DataFrame, out_dir: Path, built: str) -> dict:
    out = Path(out_dir)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    rows = well_rows(inv)
    prefix = rows.api10.str.slice(0, 5)
    big = prefix.map(prefix.value_counts()) > MAX_ROWS
    prefix = prefix.where(~big, rows.api10.str.slice(0, 6))
    shards, states = {}, {}
    for p, part in rows.groupby(prefix, sort=True):
        with open(out / f'{p}.json', 'w') as f:
            json.dump({'cols': WCOLS, 'rows': _records(part)}, f, separators=(',', ':'), allow_nan=False)
        shards[p] = int(len(part))
        states.setdefault(p[:2], part.st.mode().iat[0])
    pi = sorted({int(i) for i in rows.town_i.dropna()})
    gi = sorted({int(i) for i in rows.p69_i.dropna()})
    ref = {'places': {i: [str(places.NAME[i]), str(places.USPS[i]), int(places['pop'][i])] for i in pi},
           'plants': {i: [str(plants.name[i]), str(plants.st[i]), float(plants.kv[i]), float(plants.mw[i])] for i in gi}}
    with open(out / 'ref.json', 'w') as f:
        json.dump(ref, f, separators=(',', ':'), allow_nan=False)
    meta = {'built': built, 'cols': WCOLS, 'shards': shards, 'state_codes': states,
            'wells': int(len(rows)), 'without_api': int(len(inv) - len(rows))}
    with open(out / 'index.json', 'w') as f:
        json.dump(meta, f, separators=(',', ':'))
    return {k: meta[k] for k in ('wells', 'without_api')} | {'shards': len(shards)}
