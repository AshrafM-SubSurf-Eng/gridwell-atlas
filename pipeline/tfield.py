"""Depth-matched temperature field (GRIDWELL refinement of the ORPHANHEAT field).

ORPHANHEAT v0.1 interpolates one gradient per location from the 12 nearest
corrected bottom-hole temperatures (BHT) within 75 km, at any depth, and lets a
measurement that sits on the target dominate (distance floor 1e-6 km). That is
fine for a national screen at fixed depths, but GRIDWELL evaluates each well at
its own total depth, and two things then go wrong:

1. Shallow BHTs carry the largest correction error and the noisiest gradients
   (and, in parts of the aggregated file, implausible values -- e.g. 180 degC at
   1.4 km in the Williston Basin, where measurements at 3-4 km in the same
   square kilometre read 120-130 degC). A linear geotherm fitted to a shallow
   reading and extrapolated to 4 km inherits that error four-fold.
2. A single co-located reading can set a well's temperature on its own.

So for a target depth z the field uses only BHTs measured between 0.75 z and 1.25 z
(at least DEPTH_FLOOR_M), takes the 12 nearest inside 75 km, rejects readings
whose gradient lies more than 3 scaled median absolute deviations from the
neighbourhood median, and inverse-distance weights the rest with a 1 km distance
floor. Where fewer than MIN_MATCHED depth-matched readings exist, it falls back to
the ORPHANHEAT all-depth estimate and says so (matched = False).

validate() measures both fields by predicting held-out BHTs from their
neighbours (readings within 0.5 km of the held-out one are excluded, so a
well's other logging runs cannot leak into its prediction).
"""
from __future__ import annotations
import numpy as np, pandas as pd
from scipy.spatial import cKDTree

R_KM = 6371.0088
K_QUERY = 96
K_USE = 12
RADIUS_KM = 75.0
FLOOR_KM = 1.0
MIN_MATCHED = 3
DEPTH_LO, DEPTH_HI = 0.75, 1.25       # use BHTs measured within +/-25% of the target depth
DEPTH_FLOOR_M = 300.0
MAD_K = 3.0
SURFACE_T = 15.0


def _xyz(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def _arc(ch):
    return 2.0 * np.arcsin(np.clip(ch, 0, 2) / 2.0) * R_KM


def _chord(km):
    return 2.0 * np.sin(min(km / R_KM, np.pi) / 2.0)


class DepthMatchedField:
    def __init__(self, pts: pd.DataFrame):
        self.lat = pts.latitude.to_numpy(float)
        self.lon = pts.longitude.to_numpy(float)
        self.z = pts.depth_m.to_numpy(float)
        self.g = pts.gradient_c_per_km.to_numpy(float)
        self.tree = cKDTree(_xyz(self.lat, self.lon))

    def _neigh(self, xyz, k=K_QUERY):
        d, i = self.tree.query(xyz, k=k, distance_upper_bound=_chord(RADIUS_KM))
        valid = np.isfinite(d) & (i < len(self.g))
        km = np.where(valid, _arc(np.where(valid, d, 0)), np.nan)
        return km, np.where(valid, i, 0), valid

    def query(self, lat, lon, z_m, chunk=50_000, exclude_km=0.0):
        """Gradient (degC/km) for targets at depth z_m. Returns a frame with
        grad, n, nearest_km, sd, matched."""
        lat = np.asarray(lat, float); lon = np.asarray(lon, float)
        z_m = np.broadcast_to(np.asarray(z_m, float), lat.shape)
        out = {k: np.full(lat.shape, np.nan) for k in ('grad', 'n', 'nearest_km', 'sd', 'grad_all', 'grad_oh')}
        matched = np.zeros(lat.shape, bool)
        for s in range(0, len(lat), chunk):
            sl = slice(s, s + chunk)
            km, idx, valid = self._neigh(_xyz(lat[sl], lon[sl]))
            if exclude_km > 0:
                valid &= ~(km < exclude_km)
            gz, zz = self.g[idx], self.z[idx]
            zt = z_m[sl][:, None]
            # all-depth (ORPHANHEAT-style, but with the 1 km floor) for fallback
            out['grad_all'][sl] = self._idw(km, gz, valid, K_USE)
            out['grad_oh'][sl] = self._idw(km, gz, valid, K_USE, floor=1e-6)
            lo = np.maximum(DEPTH_LO * zt, DEPTH_FLOOR_M)
            m = valid & (zz >= lo) & (zz <= DEPTH_HI * zt)
            g, n, near, sd = self._robust_idw(km, gz, m)
            ok = n >= MIN_MATCHED
            out['grad'][sl] = np.where(ok, g, out['grad_all'][sl])
            out['n'][sl] = np.where(ok, n, valid[:, :K_USE].sum(1))
            out['nearest_km'][sl] = np.where(ok, near, np.nanmin(np.where(valid, km, np.nan), axis=1) if valid.any() else np.nan)
            out['sd'][sl] = np.where(ok, sd, np.nan)
            matched[sl] = ok
        f = pd.DataFrame(out)
        f['matched'] = matched
        return f

    @staticmethod
    def _idw(km, g, valid, k, floor=FLOOR_KM):
        # first k valid neighbours (rows are sorted by distance)
        rank = np.cumsum(valid, axis=1)
        use = valid & (rank <= k)
        w = np.where(use, 1.0 / np.maximum(np.where(use, km, 1), floor) ** 2, 0.0)
        ws = w.sum(1)
        with np.errstate(invalid='ignore', divide='ignore'):
            return np.where(ws > 0, (w * np.where(use, g, 0)).sum(1) / ws, np.nan)

    @staticmethod
    def _robust_idw(km, g, m):
        rank = np.cumsum(m, axis=1)
        use = m & (rank <= K_USE)
        gg = np.where(use, g, np.nan)
        with np.errstate(all='ignore'):
            med = np.nanmedian(gg, axis=1)
            mad = 1.4826 * np.nanmedian(np.abs(gg - med[:, None]), axis=1)
            mad = np.where(np.isfinite(mad), np.maximum(mad, 2.0), 2.0)      # >= 2 degC/km so tight clusters keep their members
            keep = use & (np.abs(g - med[:, None]) <= MAD_K * mad[:, None])
            w = np.where(keep, 1.0 / np.maximum(np.where(keep, km, 1), FLOOR_KM) ** 2, 0.0)
            ws = w.sum(1)
            grad = np.where(ws > 0, (w * np.where(keep, g, 0)).sum(1) / ws, np.nan)
            n = keep.sum(1)
            near = np.nanmin(np.where(keep, km, np.nan), axis=1)
            sd = np.nanstd(np.where(keep, g, np.nan), axis=1)
        return grad, n, near, sd


def validate(pts: pd.DataFrame, n=20_000, min_depth_m=1000.0, seed=7, exclude_km=0.5):
    """Hold out n BHTs deeper than min_depth_m and predict each one's corrected
    temperature from neighbours more than exclude_km away (so other logging runs
    in the same well cannot leak in). Three estimators are scored on the same
    held-out set: the ORPHANHEAT v0.1 form (all depths, no distance floor), the
    same with a 1 km floor, and the depth-matched robust field used by GRIDWELL."""
    rng = np.random.default_rng(seed)
    cand = np.flatnonzero(pts.depth_m.to_numpy() >= min_depth_m)
    pick = rng.choice(cand, size=min(n, len(cand)), replace=False)
    t = pts.iloc[pick]
    q = DepthMatchedField(pts).query(t.latitude.values, t.longitude.values, t.depth_m.values, exclude_km=exclude_km)
    obs = t.temp_corrected_c.to_numpy()
    z = t.depth_m.to_numpy()
    res = {'held_out': int(len(t)), 'min_depth_m': min_depth_m, 'exclude_km': exclude_km,
           'matched_share': round(float(q.matched.mean()), 3)}
    for name, g in (('orphanheat_v0_1_form', q.grad_oh), ('all_depth_1km_floor', q.grad_all), ('gridwell_depth_matched', q.grad)):
        e = SURFACE_T + g.to_numpy() * z / 1000.0 - obs
        ok = np.isfinite(e)
        a = np.abs(e[ok])
        res[name] = {'n': int(ok.sum()), 'mae_c': round(float(a.mean()), 2), 'median_abs_c': round(float(np.median(a)), 2),
                     'bias_c': round(float(e[ok].mean()), 2), 'rmse_c': round(float(np.sqrt(np.mean(e[ok] ** 2))), 2),
                     'p90_abs_c': round(float(np.percentile(a, 90)), 2), 'share_within_10c': round(float((a <= 10).mean()), 3)}
    return res
