"""Download every source in sources.json and record what was fetched.

group=registry   state well registries: downloaded every run; a changed SHA-256
                 is what tells the refresh that new wells may have been recorded.
group=reference  federal layers pinned by SHA-256. A cached copy with the pinned
                 hash is reused, else the copy kept in data/reference, else the
                 agency download; a download whose hash differs is NOT used -- the
                 build stops and a review issue is opened, because a silently
                 replaced reference file would change results without a record.
                 next_vintage URLs are probed so a new annual release is noticed.
group=watch/static  a landing page is fetched and its content hash compared with
                 the last run; a change opens a review issue.

If a registry download fails, the last good copy (restored from the Actions cache)
is used and the page says how old it is.

    python -m pipeline.fetch [--only ok,ks] [--offline]
"""
from __future__ import annotations
import argparse, gzip, hashlib, io, json, os, shutil, sys, time, zipfile
from datetime import datetime, timezone
from pathlib import Path
from .paths import RAW, MANIFEST, SOURCES

UA = 'GRIDWELL-Atlas/0.2 (+https://github.com/AshrafM-SubSurf-Eng/gridwell-atlas; monthly research refresh)'
TIMEOUT = 300
# Copies of the pinned reference files kept in the repository (data/reference), so a
# build never depends on a federal server being up; each is checked against its pin.
REFERENCE = Path(__file__).resolve().parents[1] / 'data' / 'reference'


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    s.headers['User-Agent'] = UA
    r = Retry(total=4, backoff_factor=5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=('GET', 'HEAD'))
    s.mount('https://', HTTPAdapter(max_retries=r))
    s.mount('http://', HTTPAdapter(max_retries=r))
    return s


def _download(sess, url, dest: Path, gz=False):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + '.part')
    with sess.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        meta = {'http_last_modified': r.headers.get('Last-Modified'), 'http_etag': r.headers.get('ETag')}
        if gz:
            with gzip.GzipFile(filename='', mode='wb', fileobj=open(tmp, 'wb'), mtime=0) as g:
                for b in r.iter_content(1 << 20):
                    g.write(b)
        else:
            with open(tmp, 'wb') as f:
                for b in r.iter_content(1 << 20):
                    f.write(b)
    return tmp, meta


def _arcgis(sess, src, dest: Path):
    """Page through an ArcGIS MapServer layer and write the attributes as gzipped CSV."""
    import csv
    url = src['url'].rstrip('/') + '/query'
    fields = src['fields'].split(',')
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + '.part')
    n, off, page = 0, 0, 2000
    with gzip.open(tmp, 'wt', newline='', encoding='utf-8') as g:
        w = csv.writer(g)
        w.writerow(fields)
        while True:
            p = {'where': src['where'], 'outFields': src['fields'], 'returnGeometry': 'false', 'orderByFields': 'OBJECTID',
                 'resultOffset': off, 'resultRecordCount': page, 'f': 'json'}
            r = sess.get(url, params=p, timeout=TIMEOUT)
            r.raise_for_status()
            js = r.json()
            if 'error' in js:
                raise RuntimeError(js['error'])
            feats = js.get('features', [])
            for ft in feats:
                a = ft['attributes']
                w.writerow(['' if a.get(k) is None else a.get(k) for k in fields])
            n += len(feats)
            off += len(feats)
            if not feats or not js.get('exceededTransferLimit', len(feats) == page):
                break
            time.sleep(0.5)
    return tmp, {'records': n}


def _repo_copy(src, dest: Path, pin: str) -> bool:
    name = Path(src['save_as']).name
    for cand in (REFERENCE / name, REFERENCE / (name + '.gz')):
        if not cand.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + '.part')
        if cand.suffix == '.gz' and not name.endswith('.gz'):
            with gzip.open(cand, 'rb') as fi, open(tmp, 'wb') as fo:
                shutil.copyfileobj(fi, fo)
        else:
            shutil.copyfile(cand, tmp)
        if sha256(tmp) == pin:
            tmp.replace(dest)
            return True
        tmp.unlink()
    return False


def _unzip(zpath: Path, into: Path):
    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            name = Path(m.filename).name
            if not name or m.is_dir():
                continue
            with z.open(m) as fi, open(into / name, 'wb') as fo:
                shutil.copyfileobj(fi, fo)


def run(only=None, offline=False):
    reg = json.loads(SOURCES.read_text())['sources']
    prev = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    man = {'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'sources': {}}
    report = {'changed': [], 'unchanged': [], 'failed': [], 'stale': [], 'pin_mismatch': [], 'new_vintage': [], 'watch_changed': []}
    sess = None if offline else _session()
    for s in reg:
        sid = s['id']
        if only and sid not in only:
            man['sources'][sid] = prev.get('sources', {}).get(sid)
            continue
        old = prev.get('sources', {}).get(sid) or {}
        rec = {'layer': s['layer'], 'group': s['group'], 'url': s['url']}
        try:
            if s['group'] in ('watch', 'static'):
                if s.get('watch') and not offline:
                    r = sess.get(s.get('landing') or s['url'], timeout=TIMEOUT)
                    r.raise_for_status()
                    h = hashlib.sha256(r.content).hexdigest()
                    rec.update(page_sha256=h, checked=man['fetched_at'])
                    if old.get('page_sha256') and old['page_sha256'] != h:
                        report['watch_changed'].append(sid)
                if s.get('vendored'):
                    rec['vendored'] = s['vendored']
                man['sources'][sid] = rec
                continue
            dest = RAW / s['save_as']
            if s['group'] == 'reference':
                pin = s['sha256']
                if dest.exists() and sha256(dest) == pin:
                    rec.update(sha256=pin, bytes=dest.stat().st_size, from_cache=True)
                elif _repo_copy(s, dest, pin):
                    rec.update(sha256=pin, bytes=dest.stat().st_size, from_repository=True)
                elif offline:
                    raise FileNotFoundError(f'{dest} missing or not the pinned file')
                else:
                    tmp, meta = _download(sess, s['url'], dest)
                    h = sha256(tmp)
                    if h != pin:
                        tmp.unlink()
                        report['pin_mismatch'].append({'id': sid, 'expected': pin, 'got': h})
                        raise RuntimeError(f'{sid}: SHA-256 {h} does not match the pinned {pin}')
                    tmp.replace(dest)
                    rec.update(sha256=h, bytes=dest.stat().st_size, from_cache=False, **meta)
                if s.get('unzip'):
                    _unzip(dest, RAW / s['unzip'])
                if s.get('next_vintage') and not offline:
                    nxt = s['next_vintage'].format(Y=s['vintage'] + 1)
                    try:
                        hr = sess.head(nxt, timeout=60, allow_redirects=True)
                        if hr.status_code == 200:
                            report['new_vintage'].append({'id': sid, 'url': nxt})
                    except Exception:
                        pass
            else:   # registry
                if offline:
                    if not dest.exists():
                        raise FileNotFoundError(dest)
                    tmp, meta = None, {}
                elif s.get('method') == 'arcgis':
                    tmp, meta = _arcgis(sess, s, dest)
                else:
                    tmp, meta = _download(sess, s['url'], dest, gz=s.get('gzip', False))
                if tmp is not None:
                    tmp.replace(dest)
                h = sha256(dest)
                rec.update(sha256=h, bytes=dest.stat().st_size, retrieved=man['fetched_at'], **meta)
                if s.get('unzip'):
                    _unzip(dest, RAW / s['unzip'])
                (report['changed'] if h != old.get('sha256') else report['unchanged']).append(sid)
        except Exception as e:
            rec['error'] = f'{type(e).__name__}: {e}'[:400]
            report['failed'].append(sid)
            if old and (RAW / s.get('save_as', '_')).exists():
                rec.update({k: old.get(k) for k in ('sha256', 'bytes', 'retrieved', 'http_last_modified')})
                rec['stale_since'] = old.get('retrieved')
                report['stale'].append(sid)
        man['sources'][sid] = rec
    man['report'] = report
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(man, indent=1))
    return man


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default=None, help='comma-separated source ids')
    ap.add_argument('--offline', action='store_true', help='use files already in data/raw; no network')
    a = ap.parse_args()
    m = run(set(a.only.split(',')) if a.only else None, a.offline)
    print(json.dumps(m['report'], indent=1))
    sys.exit(1 if m['report']['pin_mismatch'] else 0)
