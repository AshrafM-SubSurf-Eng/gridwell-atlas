"""Energy-community (IRA §45/§48/§45Y/§48E bonus) layers from the Treasury
machine-readable files. Every flag is copied from Treasury; nothing is recomputed,
so a disagreement with an IRS appendix is a finding, not a modelling choice."""
from __future__ import annotations
import pandas as pd

from .paths import RAW as _RAW
RAW = str(_RAW) + '/'

def _fips(d):
    return d.iloc[:, 0].astype(int).astype(str).str.zfill(2) + d.iloc[:, 1].astype(int).astype(str).str.zfill(3)

def statistical_area():
    """One row per county; columns per status year. 'yr' is the unemployment
    data year; the IRS notice that published it and its effective date are
    recorded in NOTICES so the page never mislabels which year is in force."""
    out = None
    # 2025 and 2024 files carry both delineation vintages
    for yr in (2025, 2024):
        d = pd.read_excel(RAW + f'EC_MSA_FFE_U{yr}_AllCounties.xlsx', header=1)
        d = d.dropna(subset=[d.columns[0]])
        d = d[d.iloc[:, 1].notna()]
        f = _fips(d)
        col = {c: c for c in d.columns}
        g = pd.DataFrame({
            'fips': f,
            f'ec{yr}': d[f'{yr} Energy Community (one or both vintages)'].astype(int).values,
            f'ec{yr}_v1': d[f'{yr} Energy Community (Vintage 1) (0/1)'].astype(int).values,
            f'ec{yr}_v2': d[f'{yr} Energy Community (Vintage 2) (0/1)'].astype(int).values,
            f'ffe{yr}_v1': d[[c for c in d.columns if c.startswith('FFE for MSA/non-MSA') and 'Vintage 1' in c][0]].astype(int).values,
            f'ffe{yr}_v2': d[[c for c in d.columns if c.startswith('FFE for MSA/non-MSA') and 'Vintage 2' in c][0]].astype(int).values,
            f'ur{yr}_v1': d[f'{yr} unemployment rate for MSA/non-MSA, Vintage 1'].values,
            f'ur{yr}_v2': d[f'{yr} unemployment rate for MSA/non-MSA, Vintage 2'].values,
            f'urnat{yr}': d[f'EC National Unemployment Rate {yr}'].values,
        })
        if yr == 2025:
            g['msa_v1'] = d['MSA or non-MSA Name (Vintage 1)'].values
            g['msa_v2'] = d['MSA or non-MSA Name (Vintage 2)'].values
        out = g if out is None else out.merge(g, on='fips', how='outer')
    for yr, notice in ((2023, '2024-48'), (2022, '2024-30')):
        d = pd.read_excel(RAW + f'EC_MSA_FFE_U{yr}_AllCounties.xlsx', header=1)
        d = d.dropna(subset=[d.columns[0]])
        d = d[d.iloc[:, 1].notna()]
        g = pd.DataFrame({'fips': _fips(d),
                          f'ec{yr}': d[f'Energy Community according to IRS Notice {notice}'].astype(int).values,
                          f'ffe{yr}': d['Meets FFE Rate Threshold according to IRS Notice 2024-30'].astype(int).values})
        out = out.merge(g, on='fips', how='outer')
    return out

NOTICES = {
    # unemployment-data year -> (IRS notice, status in force from)
    2025: ('Notice 2026-39', '2026-06-10'),
    2024: ('Notice 2025-31', '2025-06-23'),
    2023: ('Notice 2024-48', '2024-06-07'),
    2022: ('Notice 2023-47 as supplemented by Notice 2024-30', '2023-06-15'),
}

def coal_closure_by_county():
    t = pd.read_excel(RAW + 'EC_AllTracts_V5.xlsx', header=1, dtype=str)
    t = t.iloc[:, :5]
    t.columns = ['state', 'county', 'tract', 'date', 'cc']
    t = t.dropna(subset=['tract'])
    t['tract'] = t.tract.str.split('.').str[0].str.zfill(11)
    t['fips'] = t.tract.str[:5]
    t['is_cc'] = (t.cc.str.strip() == 'Yes').astype(int)
    c = pd.read_excel(RAW + 'EC_CC_V5.xlsx', header=1, dtype=str)
    c.columns = ['state', 'county', 'tract', 'type', 'date']
    c['tract'] = c.tract.str.zfill(11)
    t = t.merge(c[['tract', 'type']], on='tract', how='left')
    t['origin'] = t.type.fillna('').str.contains('Mine closure|Generating unit retirement').astype(int) & t.is_cc
    agg = t.groupby('fips').agg(tracts=('tract', 'size'), cc_tracts=('is_cc', 'sum'),
                                cc_origin_tracts=('origin', 'sum')).reset_index()
    cc_list = t[t.is_cc == 1].groupby('fips').apply(
        lambda x: [[r.tract, (r.type or ''), r.date] for r in x.itertuples()], include_groups=False)
    agg['cc_list'] = agg.fips.map(cc_list)
    return agg, t
