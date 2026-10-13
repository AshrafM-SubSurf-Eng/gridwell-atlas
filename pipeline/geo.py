"""Minimal, dependency-free geometry helpers (shapefile reader, point-in-polygon,
topology-preserving simplification to TopoJSON). Written because the build
environment has no GDAL/shapely; every routine is small enough to audit."""
from __future__ import annotations
import struct, math
import numpy as np
from matplotlib.path import Path

# ---------------------------------------------------------------- shapefile
def read_dbf(path):
    with open(path, 'rb') as f:
        hdr = f.read(32)
        nrec, hlen, rlen = struct.unpack('<IHH', hdr[4:12])
        fields = []
        while True:
            d = f.read(32)
            if d[0] == 0x0D:
                break
            name = d[:11].split(b'\x00')[0].decode('ascii')
            fields.append((name, chr(d[11]), d[16]))
        f.seek(hlen)
        rows = []
        for _ in range(nrec):
            rec = f.read(rlen)
            pos = 1
            row = {}
            for name, typ, ln in fields:
                raw = rec[pos:pos + ln]
                pos += ln
                row[name] = raw.decode('utf-8', 'replace').strip()
            rows.append(row)
    return rows

def read_shp_polygons(path):
    """Return list of features; each feature is a list of rings (Nx2 float arrays)."""
    out = []
    with open(path, 'rb') as f:
        data = f.read()
    pos = 100
    n = len(data)
    while pos < n:
        _recno, clen = struct.unpack('>ii', data[pos:pos + 8])
        pos += 8
        st = struct.unpack('<i', data[pos:pos + 4])[0]
        if st == 0:
            out.append([])
            pos += clen * 2
            continue
        assert st in (5, 15, 25), f'not a polygon shape: {st}'
        nparts, npts = struct.unpack('<ii', data[pos + 36:pos + 44])
        parts = struct.unpack(f'<{nparts}i', data[pos + 44:pos + 44 + 4 * nparts])
        p0 = pos + 44 + 4 * nparts
        pts = np.frombuffer(data[p0:p0 + 16 * npts], dtype='<f8').reshape(npts, 2)
        rings = []
        for i, s in enumerate(parts):
            e = parts[i + 1] if i + 1 < nparts else npts
            rings.append(np.array(pts[s:e]))
        out.append(rings)
        pos += clen * 2
    return out

# ---------------------------------------------------------- point in polygon
class PolygonIndex:
    """Even-odd point-in-polygon over many features with bbox prefilter."""
    def __init__(self, features, ids):
        self.ids = list(ids)
        self.paths, self.bbox = [], []
        for rings in features:
            ps = [Path(r) for r in rings if len(r) >= 4]
            self.paths.append(ps)
            if rings:
                allp = np.vstack(rings)
                self.bbox.append(allp.min(0).tolist() + allp.max(0).tolist())
            else:
                self.bbox.append([np.inf, np.inf, -np.inf, -np.inf])
        self.bbox = np.array(self.bbox)

    def locate(self, lon, lat):
        lon = np.asarray(lon, float); lat = np.asarray(lat, float)
        res = np.full(len(lon), None, dtype=object)
        pts = np.column_stack([lon, lat])
        for k, (ps, bb) in enumerate(zip(self.paths, self.bbox)):
            m = (lon >= bb[0]) & (lon <= bb[2]) & (lat >= bb[1]) & (lat <= bb[3]) & (res == None)  # noqa: E711
            if not m.any():
                continue
            idx = np.where(m)[0]
            cnt = np.zeros(len(idx), int)
            for p in ps:
                cnt += p.contains_points(pts[idx]).astype(int)
            hit = idx[cnt % 2 == 1]
            res[hit] = self.ids[k]
        return res

# ------------------------------------------------- topology + simplification
def _dp(pts, tol):
    """Douglas-Peucker on an open polyline; keeps both endpoints."""
    n = len(pts)
    if n <= 2:
        return pts
    keep = np.zeros(n, bool); keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        p, q = pts[a], pts[b]
        seg = pts[a + 1:b]
        d = q - p
        L = math.hypot(*d)
        if L == 0:
            dist = np.hypot(*(seg - p).T)
        else:
            dist = np.abs(d[0] * (seg[:, 1] - p[1]) - d[1] * (seg[:, 0] - p[0])) / L
        i = int(np.argmax(dist))
        if dist[i] > tol:
            k = a + 1 + i
            keep[k] = True
            stack += [(a, k), (k, b)]
    return pts[keep]

def to_topojson(features, props, tol=0.01, quant=1e5):
    """Build a TopoJSON Topology from polygon features with shared-arc
    simplification so neighbouring counties keep identical borders."""
    # 1. canonical rings (drop closing duplicate), keyed points
    rings_all = []  # (feature_idx, ring_idx, array without closing point)
    for fi, rings in enumerate(features):
        for ri, r in enumerate(rings):
            r = np.round(r, 7)
            if len(r) > 1 and (r[0] == r[-1]).all():
                r = r[:-1]
            if len(r) >= 3:
                rings_all.append((fi, ri, r))
    # 2. junction detection: a point is a junction if its neighbour pairs differ
    neigh = {}
    for _, _, r in rings_all:
        n = len(r)
        keys = [tuple(p) for p in r]
        for i, k in enumerate(keys):
            a, b = keys[i - 1], keys[(i + 1) % n]
            pair = (a, b) if a <= b else (b, a)
            s = neigh.setdefault(k, set())
            s.add(pair)
    junction = {k for k, s in neigh.items() if len(s) > 1}
    # 3. cut rings into arcs at junctions, dedupe
    arc_index, arcs = {}, []
    geoms = [[] for _ in features]
    for fi, ri, r in rings_all:
        keys = [tuple(p) for p in r]
        n = len(keys)
        js = [i for i, k in enumerate(keys) if k in junction]
        if not js:
            js = [0]
            junction.add(keys[0])
        ring_arcs = []
        for t, s in enumerate(js):
            e = js[(t + 1) % len(js)]
            idxs = list(range(s, e + 1)) if e > s else list(range(s, n)) + list(range(0, e + 1))
            seq = tuple(keys[i] for i in idxs)
            if seq in arc_index:
                ring_arcs.append(arc_index[seq])
            elif seq[::-1] in arc_index:
                ring_arcs.append(~arc_index[seq[::-1]])
            else:
                arc_index[seq] = len(arcs)
                arcs.append(np.array(seq))
                ring_arcs.append(arc_index[seq])
        geoms[fi].append(ring_arcs)
    # 4. simplify each arc once (closed arcs are split at their farthest point
    #    so an island or enclave keeps at least a triangle)
    def _simplify(a):
        if len(a) > 3 and (a[0] == a[-1]).all():
            k = int(np.argmax(np.hypot(*(a - a[0]).T)))
            return np.vstack([_dp(a[:k + 1], tol)[:-1], _dp(a[k:], tol)])
        return _dp(a, tol)
    simp = [_simplify(a) for a in arcs]
    # 5. quantize + delta encode
    allp = np.vstack(simp)
    x0, y0 = allp.min(0); x1, y1 = allp.max(0)
    kx = (x1 - x0) / (quant - 1); ky = (y1 - y0) / (quant - 1)
    qarcs = []
    for a in simp:
        q = np.round(np.column_stack([(a[:, 0] - x0) / kx, (a[:, 1] - y0) / ky])).astype(int)
        d = np.vstack([q[:1], np.diff(q, axis=0)])
        # drop zero-length steps except the first point
        keep = np.ones(len(d), bool); keep[1:] = (d[1:] != 0).any(1)
        if keep.sum() < 2:
            keep[-1] = True
        qarcs.append(d[keep].tolist())
    def ring_coords(ra):
        pts = []
        for a in ra:
            seg = simp[a] if a >= 0 else simp[~a][::-1]
            pts.extend(seg[:-1].tolist())
        return np.array(pts)
    def signed_area(r):
        x, y = r[:, 0], r[:, 1]
        return 0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))
    orig = {}
    for fi, ri, r in rings_all:
        orig.setdefault(fi, []).append(r)
    geometries = []
    dropped = 0
    for fi, rs in enumerate(geoms):
        outers, holes = [], []
        for ra, r0 in zip(rs, orig.get(fi, [])):
            a0 = signed_area(r0)
            rc = ring_coords(ra)
            if len(rc) < 3:
                dropped += 1; continue
            a1 = signed_area(rc)
            if a1 == 0 or (a1 > 0) != (a0 > 0):
                dropped += 1; continue
            (outers if a0 < 0 else holes).append((ra, r0))   # shapefile: outer = clockwise (negative)
        polys = [[o[0]] for o in outers]
        for ra, r0 in holes:
            p = r0[0]
            for k, (ora, or0) in enumerate(outers):
                if Path(or0).contains_point(p):
                    polys[k].append(ra); break
        geometries.append({'type': 'MultiPolygon' if polys else None,
                           'arcs': polys, 'properties': props[fi]})
    return {'type': 'Topology',
            'transform': {'scale': [kx, ky], 'translate': [x0, y0]},
            'arcs': qarcs, 'geometries': geometries, 'dropped_rings': dropped}
