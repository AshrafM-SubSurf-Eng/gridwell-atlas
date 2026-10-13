"""Grid tie-in proxy: existing generator interconnections from Form EIA-860
(2025 final, released 2026-09-10). A plant's reported grid voltage is the
voltage at which it ties into the transmission or distribution system, so the
nearest operable plant is a documented interconnection point. It is a proxy:
substations and lines are closer in most places but no current federal open
layer publishes them (HIFLD Open was withdrawn 2025-08-26)."""
from __future__ import annotations
import numpy as np, pandas as pd

from .paths import RAW
D = str(RAW / 'eia860') + '/'

def load_plants():
    p = pd.read_excel(D + '2___Plant_Y2025.xlsx', header=1)
    g = pd.read_excel(D + '3_1_Generator_Y2025.xlsx', sheet_name='Operable', header=1)
    g = g[pd.to_numeric(g['Plant Code'], errors='coerce').notna()]
    g['mw'] = pd.to_numeric(g['Nameplate Capacity (MW)'], errors='coerce').fillna(0)
    g = g.sort_values('mw', ascending=False)
    agg = g.groupby('Plant Code').agg(mw=('mw', 'sum'), tech=('Technology', 'first'),
                                     n_gen=('Generator ID', 'size'),
                                     geo=('Technology', lambda s: int((s == 'Geothermal').any()))).reset_index()
    for c in ['Grid Voltage (kV)', 'Grid Voltage 2 (kV)', 'Grid Voltage 3 (kV)']:
        p[c] = pd.to_numeric(p[c], errors='coerce')
    p['kv'] = p[['Grid Voltage (kV)', 'Grid Voltage 2 (kV)', 'Grid Voltage 3 (kV)']].max(axis=1)
    m = p.merge(agg, on='Plant Code', how='inner')
    m = m[m.Latitude.notna() & m.Longitude.notna()]
    m = m.rename(columns={'Plant Code': 'plant', 'Plant Name': 'name', 'State': 'st', 'Latitude': 'lat',
                          'Longitude': 'lon', 'Balancing Authority Code': 'ba', 'NERC Region': 'nerc'})
    m['lat'] = m.lat.astype(float); m['lon'] = m.lon.astype(float)
    return m[['plant', 'name', 'st', 'lat', 'lon', 'kv', 'mw', 'tech', 'geo', 'ba', 'nerc']].reset_index(drop=True)

if __name__ == '__main__':
    pl = load_plants()
    print(len(pl), 'operable plants'); print(pl.kv.describe().round(1).to_dict())
    print('kv>=69:', (pl.kv >= 69).sum(), ' kv missing:', pl.kv.isna().sum(), ' geothermal plants:', pl.geo.sum(), round(pl[pl.geo == 1].mw.sum(), 1), 'MW')
    print(pl.tech.value_counts().head(8).to_dict())
