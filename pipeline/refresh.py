"""Monthly refresh: fetch -> decide -> build -> record.

    python -m pipeline.refresh [--prev-snapshot prev/snapshot.csv.gz] [--force] [--offline]

Writes, for the workflow to act on:
  build/refresh_result.json   what happened (changed sources, stale sources, counts)
  build/release_notes.md      body of the dated GitHub release
  build/issues.json           review issues to open (new vintages, pin mismatches, failures,
                              and builds held because a state's well count moved too far)
and appends one line to CHANGELOG.md when a new build was published.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date
from .paths import BUILD, ROOT, SITE_DATA
from . import fetch

# A registry whose well count moves more than this between refreshes is more likely a
# changed agency file layout than a real change, so the build is held for review.
MAX_DROP, MAX_RISE = 0.20, 0.50


def _state_counts(stats):
    by = (stats or {}).get('inv', {}).get('by_state', {})
    return {st: sum(v.get('c', {}).values()) for st, v in by.items()}


def sanity_check(old_stats, new_stats, registry_states):
    """Compare a new build with the published one; return a list of problems."""
    if not old_stats:
        return []
    old, new = _state_counts(old_stats), _state_counts(new_stats)
    probs = []
    for st in registry_states:
        a, b = old.get(st, 0), new.get(st, 0)
        if a and (b < a * (1 - MAX_DROP) or b > a * (1 + MAX_RISE)):
            probs.append(f'{st}: {a:,} -> {b:,} wells ({(b - a) / a:+.0%})')
    a, b = old_stats.get('inv', {}).get('n', 0), new_stats['inv']['n']
    if a and b < a * (1 - MAX_DROP / 2):
        probs.append(f'inventory: {a:,} -> {b:,} wells ({(b - a) / a:+.0%})')
    return probs


def main(prev_snapshot=None, force=False, offline=False, allow_large_change=False):
    man = fetch.run(offline=offline)
    rep = man['report']
    issues = []
    for m in rep['pin_mismatch']:
        issues.append({'title': f"Reference file changed upstream: {m['id']}",
                       'body': f"The download no longer matches the pinned SHA-256.\n\nexpected `{m['expected']}`\n\ngot `{m['got']}`\n\n"
                               'The build kept the pinned copy. Review the new file, then update `sources.json`.'})
    for v in rep['new_vintage']:
        issues.append({'title': f"New vintage available: {v['id']}",
                       'body': f"A newer release appears to exist at {v['url']}.\n\nReview its schema, update `sources.json` "
                               '(url, sha256, vintage) and re-run the refresh.'})
    for w in rep['watch_changed']:
        issues.append({'title': f'Watched page changed: {w}', 'body': 'The landing page content changed since the last refresh. '
                       'Check whether a new data release was published.'})
    for f in rep['failed']:
        err = man['sources'][f].get('error', '')
        issues.append({'title': f'Download failed: {f}', 'body': f"`{err}`\n\nThe last good copy was used if one was cached."})
    (BUILD / 'issues.json').write_text(json.dumps(issues, indent=1))

    must_stop = bool(rep['pin_mismatch']) or any(f not in rep['stale'] for f in rep['failed'])
    changed = bool(rep['changed'])
    result = {'date': date.today().isoformat(), 'changed_sources': rep['changed'], 'stale_sources': rep['stale'],
              'failed_sources': rep['failed'], 'built': False}
    if must_stop:
        result['reason'] = 'stopped: a reference file changed upstream or a source failed with no cached copy'
    elif not (changed or force):
        result['reason'] = 'no registry changed since the last refresh'
    else:
        import shutil
        from . import build
        from .inventory import REGISTRY_STATES
        old_stats = json.loads((SITE_DATA / 'stats.json').read_text()) if (SITE_DATA / 'stats.json').exists() else None
        backup = BUILD / 'site_data_published'
        shutil.rmtree(backup, ignore_errors=True)
        if SITE_DATA.exists():
            shutil.copytree(SITE_DATA, backup)
        inv, s = build.main(prev_snapshot)
        probs = [] if allow_large_change else sanity_check(old_stats, s, REGISTRY_STATES)
        if probs:
            shutil.rmtree(SITE_DATA)
            shutil.copytree(backup, SITE_DATA)
            result['reason'] = 'held for review: ' + '; '.join(probs)
            issues.append({'title': f"Refresh held for review ({result['date']})",
                           'body': 'The new build changed these well counts by more than the review threshold '
                                   f'(-{MAX_DROP:.0%} / +{MAX_RISE:.0%} for a state):\n\n' + '\n'.join(f'- {p}' for p in probs)
                                   + '\n\nThis usually means an agency changed its file layout or status codes. The published '
                                     'data were left unchanged. If the change is real, re-run **Monthly data refresh** with '
                                     '*force* and *allow large change* ticked.'})
            (BUILD / 'issues.json').write_text(json.dumps(issues, indent=1))
            (BUILD / 'refresh_result.json').write_text(json.dumps(result, indent=1))
            print(json.dumps(result, indent=1))
            return 3
        ch = s['changes']
        result.update(built=True, wells=s['inv']['n'], by_class=s['inv']['by_class'], by_fit=s['inv']['by_fit'],
                      added=ch.get('added_n', 0), removed=ch.get('removed_n', 0), reclassified=ch.get('reclassified_n', 0),
                      baseline=ch.get('baseline', False))
        line = (f"- {result['date']}: {result['wells']:,} wells; "
                + ('baseline for change tracking' if result['baseline'] else
                   f"{result['added']:,} joined, {result['reclassified']:,} changed type, {result['removed']:,} left")
                + f"; sources updated: {', '.join(rep['changed']) or 'none'}"
                + (f"; stale: {', '.join(rep['stale'])}" if rep['stale'] else '') + '\n')
        cl = ROOT / 'CHANGELOG.md'
        txt = cl.read_text() if cl.exists() else '# Data changelog\n\nOne line per published monthly refresh.\n\n'
        cl.write_text(txt + line)
        notes = [f"# GRIDWELL Atlas data refresh, {result['date']}", '',
                 f"Wells in the inventory: **{result['wells']:,}**", '',
                 '| Abandonment type | Wells |', '|---|---:|']
        names = {'IN': 'Inactive, unplugged (operator of record)', 'OR': 'Orphaned, unplugged',
                 'PA': 'Plugged and abandoned', 'DA': 'Dry and abandoned'}
        notes += [f'| {names[k]} | {v:,} |' for k, v in result['by_class'].items()]
        notes += ['', '| EGS fit | Wells |', '|---|---:|'] + [f'| {k} | {v:,} |' for k, v in result['by_fit'].items()]
        if not result['baseline']:
            notes += ['', f"Since the previous refresh: **{result['added']:,}** wells joined the inventory, "
                          f"**{result['reclassified']:,}** changed abandonment type, {result['removed']:,} left it."]
        notes += ['', f"Registries re-downloaded and changed: {', '.join(rep['changed']) or 'none'}."]
        if rep['stale']:
            notes += [f"Could not be downloaded this month (last good copy used): {', '.join(rep['stale'])}."]
        notes += ['', 'Assets: `snapshot.csv.gz` (one row per well, used to detect next month\'s changes), '
                      '`stats.json`, `changes.json`, `manifest.json`.']
        (BUILD / 'release_notes.md').write_text('\n'.join(notes) + '\n')
    (BUILD / 'refresh_result.json').write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
    return 2 if must_stop else 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--prev-snapshot', default=None)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--allow-large-change', action='store_true', help='publish even if a state count moved past the review threshold')
    a = ap.parse_args()
    sys.exit(main(a.prev_snapshot, a.force, a.offline, a.allow_large_change))
