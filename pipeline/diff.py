"""Change detection between monthly refreshes.

Each build writes a compact snapshot (one row per well: key, state, county,
abandonment type, EGS fit). Comparing it with the previous release's snapshot
gives the wells that joined the inventory since the last refresh -- wells an
agency has newly recorded as plugged, dry, temporarily abandoned, idle, shut-in
or orphaned -- and the wells whose type changed (for example an idle well that
was later orphaned or plugged)."""
from __future__ import annotations
from datetime import date
import pandas as pd

SNAP_COLS = ['key', 'st', 'fips', 'cls4', 'fit', 't_td', 'src']
MAX_LIST = 500


def snapshot(inv: pd.DataFrame) -> pd.DataFrame:
    s = inv[['key', 'st', 'fips', 'cls4', 'fit', 't_td', 'src']].copy()
    s['t_td'] = s.t_td.round(1)
    return s.sort_values('key').reset_index(drop=True)


def read_snapshot(path) -> pd.DataFrame | None:
    try:
        s = pd.read_csv(path, dtype={'key': str, 'st': str, 'fips': str, 'cls4': str, 'fit': str, 'src': str})
    except (FileNotFoundError, OSError, pd.errors.EmptyDataError):
        return None
    return s


def compare(prev: pd.DataFrame | None, cur: pd.DataFrame, inv: pd.DataFrame) -> dict:
    today = date.today().isoformat()
    if prev is None or prev.empty:
        return {'baseline': True, 'date': today,
                'note': 'First build with change tracking: every well is the baseline. From the next monthly refresh, '
                        'wells that join the inventory are listed here.',
                'added_n': 0, 'removed_n': 0, 'reclassified_n': 0, '_added_keys': [], 'added_by_fips': {}}
    p = prev.set_index('key')
    c = cur.set_index('key')
    added = c.index.difference(p.index)
    removed = p.index.difference(c.index)
    both = c.index.intersection(p.index)
    moved = both[(c.loc[both, 'cls4'] != p.loc[both, 'cls4']).to_numpy()]
    fit_up = both[(c.loc[both, 'fit'] != p.loc[both, 'fit']).to_numpy()]
    a = c.loc[added]
    trans = (p.loc[moved, 'cls4'].astype(str) + '→' + c.loc[moved, 'cls4'].astype(str)).value_counts().to_dict()
    sub = inv.set_index('key').loc[added] if len(added) else inv.iloc[0:0].set_index('key')
    order = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 4, 'U': 5}
    lst = (sub.assign(_o=sub.fit.map(order), _t=sub.t_td.fillna(-999))
              .sort_values(['_o', '_t'], ascending=[True, False]).head(MAX_LIST))
    return {
        'baseline': False, 'date': today,
        'added_n': int(len(added)), 'removed_n': int(len(removed)), 'reclassified_n': int(len(moved)),
        'fit_changed_n': int(len(fit_up)),
        'added_by_class': a.cls4.value_counts().to_dict(),
        'added_by_fit': a.fit.value_counts().to_dict(),
        'added_by_state': a.st.value_counts().to_dict(),
        'removed_by_state': p.loc[removed, 'st'].value_counts().to_dict(),
        'transitions': trans,
        'added_list': [[k, x.st, x.fips, x.cls4, x.fit, None if pd.isna(x.t_td) else round(float(x.t_td), 1),
                        x.api if isinstance(x.api, str) else '', x.raw_status if isinstance(x.raw_status, str) else '']
                       for k, x in lst.iterrows()],
        '_added_keys': [str(k) for k in added],
        'added_by_fips': a.fips.dropna().value_counts().to_dict(),
    }
