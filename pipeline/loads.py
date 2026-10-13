"""Nearest community load: incorporated places (Census Gazetteer 2025 internal
points) with Vintage 2025 population estimates (Census PEP, SUMLEV 162)."""
from __future__ import annotations
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
from .paths import RAW

R_EARTH_KM = 6371.0088

def unit_xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])

def chord_to_km(d):
    return 2 * R_EARTH_KM * np.arcsin(np.clip(d / 2, 0, 1))

def load_places():
    g = pd.read_csv(RAW / '2025_Gaz_place_national.txt', sep='|', dtype=str)
    g.columns = [x.strip() for x in g.columns]
    p = pd.read_csv(RAW / 'sub-est2025.csv', dtype=str, encoding='latin-1')
    p = p[p.SUMLEV.isin(['162', '170', '172'])].copy()
    p['GEOID'] = p.STATE + p.PLACE
    p = p.drop_duplicates('GEOID')
    m = g.merge(p[['GEOID', 'POPESTIMATE2025']], on='GEOID', how='inner')
    m = m[m.FUNCSTAT.isin(['A', 'B', 'C', 'F', 'G'])] if 'A' in set(m.FUNCSTAT) else m
    m['pop'] = m.POPESTIMATE2025.astype(int)
    m['lat'] = m.INTPTLAT.astype(float); m['lon'] = m.INTPTLONG.astype(float)
    return m[['GEOID', 'USPS', 'NAME', 'pop', 'lat', 'lon']].reset_index(drop=True)

class Nearest:
    def __init__(self, df):
        self.df = df.reset_index(drop=True)
        self.tree = cKDTree(unit_xyz(self.df.lat.values, self.df.lon.values))
    def query(self, lat, lon):
        d, i = self.tree.query(unit_xyz(lat, lon), k=1)
        return chord_to_km(d), i
