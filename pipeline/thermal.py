# Vendored from ORPHANHEAT v0.1 (Ashraf Mohammed, 2026), code/orphanheat/thermal.py,
# unchanged except for this header, so GRIDWELL and ORPHANHEAT share one thermal model.
"""Thermal field: from bottom-hole temperature points to temperature at depth.

The screening question ORPHANHEAT answers for each well is deliberately *not*
"how hot is this well" -- most documented orphaned wells have no public total
depth, so that question is unanswerable for the majority of the inventory.
The question it answers instead is:

    if a well at this location were re-entered or deepened to z metres,
    what formation temperature would it meet, and how well constrained is
    that estimate by nearby measurements?

That is answerable everywhere, it is the question a screening study should ask,
and it degrades honestly: every estimate carries the number of supporting
measurements and the distance to them.

Method
------
1. Correct each BHT measurement toward true formation temperature.
2. Convert each corrected measurement to a geothermal gradient.
3. Interpolate the gradient field to well locations by inverse-distance
   weighting over the k nearest measurements inside a search radius.
4. Evaluate T(z) = T_surface + gradient * z at reference depths.

Every step is a modelling choice; each one is exposed as a parameter, recorded
in the output, and listed in docs/VERIFY_CHECKLIST.md as a decision the author
must personally rule on rather than inherit from this code.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

EARTH_RADIUS_KM = 6371.0088
FEET_TO_M = 0.3048

# Thermal class boundaries follow the categories used in the USGS/GRC
# assessment of orphan-well geothermal potential (Gardner et al., 2025) so that
# ORPHANHEAT tiers are directly comparable with the published federal work
# rather than inventing a private classification.
THERMAL_CLASS_BOUNDS_C = {"low": (None, 90.0), "moderate": (90.0, 150.0), "high": (150.0, None)}


@dataclass(frozen=True)
class ThermalConfig:
    """Every knob in the thermal model, recorded with the outputs."""

    surface_temp_c: float = 15.0
    bht_correction: str = "harrison"  # "harrison" | "none"
    min_bht_depth_m: float = 150.0
    max_bht_depth_m: float = 9000.0
    min_gradient_c_per_km: float = 5.0
    max_gradient_c_per_km: float = 120.0
    neighbours: int = 12
    search_radius_km: float = 75.0
    idw_power: float = 2.0
    reference_depths_m: tuple[float, ...] = (1000.0, 2000.0, 3000.0)

    def as_dict(self) -> dict:
        return asdict(self)


def harrison_correction_c(depth_m: np.ndarray) -> np.ndarray:
    """Harrison et al. (1983) BHT correction, depth in metres.

    A bottom-hole temperature is logged before the borehole has re-equilibrated
    with the formation, so it under-reads, increasingly so with depth. The
    Harrison polynomial is the correction most widely applied to US BHT
    compilations. It was fitted in Oklahoma, which is precisely why the choice
    is flagged for the author: applying an Oklahoma correction to Appalachian
    or Californian wells is a defensible screening simplification and an
    indefensible claim of local accuracy.
    """
    depth_m = np.asarray(depth_m, dtype=float)
    correction = -16.51 + 0.018268 * depth_m - 2.345e-6 * np.square(depth_m)
    # The polynomial turns over and goes negative at shallow depths, where BHT
    # disequilibrium is small anyway; clamp rather than subtract heat.
    return np.clip(correction, 0.0, None)


def _to_unit_sphere(lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    lat = np.radians(np.asarray(lat_deg, dtype=float))
    lon = np.radians(np.asarray(lon_deg, dtype=float))
    return np.column_stack(
        [np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)]
    )


def _chord_from_arc_km(arc_km: float) -> float:
    return 2.0 * np.sin(min(arc_km / EARTH_RADIUS_KM, np.pi) / 2.0)


def _arc_km_from_chord(chord: np.ndarray) -> np.ndarray:
    chord = np.clip(np.asarray(chord, dtype=float), 0.0, 2.0)
    return 2.0 * np.arcsin(chord / 2.0) * EARTH_RADIUS_KM


# A continental geotherm sits around 25-30 degC/km; basins run hotter, shields
# cooler. These bounds are deliberately wide -- they are here to separate
# "plausible planet" from "wrong unit", a factor-of-3.28 error, not to judge
# any individual measurement. The per-measurement envelope in ThermalConfig
# does that job afterwards.
PLAUSIBLE_MEDIAN_GRADIENT_C_PER_KM = (12.0, 60.0)


def infer_depth_unit(
    depth_raw: np.ndarray, temp_c: np.ndarray, cfg: ThermalConfig
) -> tuple[str, dict]:
    """Decide whether an unlabelled depth column is metres or feet, from evidence.

    Some BHT compilations ship a bare `Depth` header. Reading metres as feet
    multiplies every gradient by 1/0.3048 and produces a national dataset whose
    median well appears to sit at 190 degC at 2 km -- wrong, and wrong in a way
    that looks like a spectacular finding rather than a bug.

    So the unit is inferred the same way this pipeline treats an unlabelled
    temperature column: test both readings against physics, take the one that
    survives, and report the evidence rather than assume silently. The decision
    is written to the build audit and printed in the QA report, and it is listed
    in VERIFY_CHECKLIST.md as a call the author must ratify.
    """
    depth_raw = np.asarray(depth_raw, dtype=float)
    temp_c = np.asarray(temp_c, dtype=float)
    evidence: dict = {}

    for name, factor in (("m", 1.0), ("ft", FEET_TO_M)):
        depth_m = depth_raw * factor
        usable = (
            np.isfinite(depth_m)
            & np.isfinite(temp_c)
            & (depth_m >= cfg.min_bht_depth_m)
            & (depth_m <= cfg.max_bht_depth_m)
        )
        if usable.sum() < 100:
            evidence[name] = {"usable_rows": int(usable.sum()), "median_gradient_c_per_km": None,
                              "share_in_envelope_pct": 0.0}
            continue
        grad = (temp_c[usable] - cfg.surface_temp_c) / depth_m[usable] * 1000.0
        in_env = (grad >= cfg.min_gradient_c_per_km) & (grad <= cfg.max_gradient_c_per_km)
        evidence[name] = {
            "usable_rows": int(usable.sum()),
            "median_gradient_c_per_km": round(float(np.median(grad)), 2),
            "share_in_envelope_pct": round(float(in_env.mean() * 100), 2),
        }

    def score(name: str) -> tuple[int, float]:
        med = evidence[name]["median_gradient_c_per_km"]
        lo, hi = PLAUSIBLE_MEDIAN_GRADIENT_C_PER_KM
        plausible = 1 if (med is not None and lo <= med <= hi) else 0
        return (plausible, evidence[name]["share_in_envelope_pct"])

    chosen = "m" if score("m") >= score("ft") else "ft"
    evidence["chosen"] = chosen
    evidence["basis"] = (
        "median implied gradient inside "
        f"{PLAUSIBLE_MEDIAN_GRADIENT_C_PER_KM[0]}-{PLAUSIBLE_MEDIAN_GRADIENT_C_PER_KM[1]} degC/km, "
        "then the larger share of measurements inside the configured envelope"
    )
    return chosen, evidence


def prepare_bht(bht: pd.DataFrame, cfg: ThermalConfig) -> tuple[pd.DataFrame, dict]:
    """Clean BHT measurements and convert each to a geothermal gradient.

    Returns the usable points and an audit dict explaining every dropped row.
    """
    audit: dict[str, int | float | str] = {"input_rows": int(len(bht))}
    df = bht.copy()

    for col in ("latitude", "longitude", "depth_m", "temp_c"):
        if col not in df.columns:
            raise KeyError(f"BHT frame is missing required column {col!r}")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["latitude", "longitude", "depth_m", "temp_c"])
    audit["dropped_null"] = before - len(df)

    before = len(df)
    df = df[df["latitude"].between(-90, 90) & df["longitude"].between(-180, 180)]
    audit["dropped_bad_coords"] = before - len(df)

    before = len(df)
    df = df[df["depth_m"].between(cfg.min_bht_depth_m, cfg.max_bht_depth_m)]
    audit["dropped_depth_out_of_range"] = before - len(df)

    if cfg.bht_correction == "harrison":
        df["temp_corrected_c"] = df["temp_c"] + harrison_correction_c(df["depth_m"].to_numpy())
    elif cfg.bht_correction == "none":
        df["temp_corrected_c"] = df["temp_c"]
    else:
        raise ValueError(f"unknown bht_correction {cfg.bht_correction!r}")

    df["gradient_c_per_km"] = (
        (df["temp_corrected_c"] - cfg.surface_temp_c) / df["depth_m"] * 1000.0
    )

    before = len(df)
    df = df[
        df["gradient_c_per_km"].between(cfg.min_gradient_c_per_km, cfg.max_gradient_c_per_km)
    ]
    audit["dropped_gradient_out_of_range"] = before - len(df)

    audit["usable_rows"] = int(len(df))
    audit["mean_correction_c"] = (
        float((df["temp_corrected_c"] - df["temp_c"]).mean()) if len(df) else 0.0
    )
    audit["median_gradient_c_per_km"] = (
        float(df["gradient_c_per_km"].median()) if len(df) else float("nan")
    )
    return df.reset_index(drop=True), audit


class GradientField:
    """Inverse-distance-weighted gradient surface over corrected BHT points."""

    def __init__(self, points: pd.DataFrame, cfg: ThermalConfig):
        if points.empty:
            raise ValueError("cannot build a gradient field from zero usable BHT points")
        self.cfg = cfg
        self.points = points
        self._xyz = _to_unit_sphere(points["latitude"].to_numpy(), points["longitude"].to_numpy())
        self._tree = cKDTree(self._xyz)
        self._gradients = points["gradient_c_per_km"].to_numpy()

    def query(self, lat: np.ndarray, lon: np.ndarray) -> pd.DataFrame:
        """Estimate gradient at each location with its support diagnostics."""
        target = _to_unit_sphere(lat, lon)
        k = min(self.cfg.neighbours, len(self._gradients))
        chord_limit = _chord_from_arc_km(self.cfg.search_radius_km)

        dist, idx = self._tree.query(target, k=k, distance_upper_bound=chord_limit)
        dist = np.atleast_2d(dist)
        idx = np.atleast_2d(idx)

        valid = np.isfinite(dist) & (idx < len(self._gradients))
        arc_km = np.where(valid, _arc_km_from_chord(np.where(valid, dist, 0.0)), np.nan)

        safe_idx = np.where(valid, idx, 0)
        neighbour_grad = np.where(valid, self._gradients[safe_idx], np.nan)

        # Inverse distance weighting; a point sitting exactly on a measurement
        # takes that measurement's value rather than dividing by zero.
        with np.errstate(divide="ignore", invalid="ignore"):
            weights = np.where(valid, 1.0 / np.power(np.maximum(arc_km, 1e-6), self.cfg.idw_power), 0.0)
        weight_sum = weights.sum(axis=1)

        gradient = np.where(
            weight_sum > 0,
            np.nansum(np.where(valid, neighbour_grad * weights, 0.0), axis=1)
            / np.where(weight_sum > 0, weight_sum, 1.0),
            np.nan,
        )

        n_support = valid.sum(axis=1)
        nearest_km = np.where(n_support > 0, np.nanmin(np.where(valid, arc_km, np.nan), axis=1), np.nan)
        spread = np.where(
            n_support > 1,
            np.nanstd(np.where(valid, neighbour_grad, np.nan), axis=1),
            np.nan,
        )

        return pd.DataFrame(
            {
                "gradient_c_per_km": gradient,
                "gradient_n_support": n_support.astype("int32"),
                "gradient_nearest_km": nearest_km,
                "gradient_local_sd": spread,
            }
        )


def temperature_at_depth(gradient_c_per_km: np.ndarray, depth_m: float, cfg: ThermalConfig) -> np.ndarray:
    """T(z) = T_surface + gradient * z, with gradient in degC/km and z in metres."""
    return cfg.surface_temp_c + np.asarray(gradient_c_per_km, dtype=float) * (depth_m / 1000.0)


def thermal_class(temp_c: np.ndarray) -> np.ndarray:
    """Low / moderate / high classes matching the published federal categories."""
    temp = np.asarray(temp_c, dtype=float)
    out = np.full(temp.shape, "unknown", dtype=object)
    out[temp < 90.0] = "low"
    out[(temp >= 90.0) & (temp < 150.0)] = "moderate"
    out[temp >= 150.0] = "high"
    out[~np.isfinite(temp)] = "unknown"
    return out


def confidence_band(n_support: np.ndarray, nearest_km: np.ndarray, cfg: ThermalConfig) -> np.ndarray:
    """How well constrained is this estimate by nearby measurements?

    This is a statement about data density, not about geology. A 'high' band
    means several measurements sit close by; it does not mean the formation
    temperature is known to a degree.
    """
    n = np.asarray(n_support, dtype=float)
    d = np.asarray(nearest_km, dtype=float)
    out = np.full(n.shape, "none", dtype=object)
    supported = n > 0
    out[supported] = "low"
    out[supported & (n >= 3) & (d <= cfg.search_radius_km / 2.0)] = "moderate"
    out[supported & (n >= 8) & (d <= cfg.search_radius_km / 5.0)] = "high"
    return out
