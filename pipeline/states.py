"""State well registries -> one schema.

Each loader reads the agency's own file (the full download the monthly refresh
fetches; a reduced copy made in the author's browser is accepted for local work),
applies the agency's own status codes, and returns one row per record with:

  cls          PA  plugged and abandoned (produced, injected or otherwise used, now plugged)
               DA  dry and abandoned (drilled, never produced)
               IN  inactive and unplugged (temporarily abandoned, idle, shut-in, inactive)
               None for wells the agency lists as orphaned and not yet plugged; those
               become class OR in inventory.py
  orphan_list  the agency lists the well as orphaned or in its state-funded plugging queue
  public_plug  the well was plugged with state or federal money
  td_ft        total depth in feet, true vertical depth where the agency reports it
  depth_basis  'TVD' or 'MD' (measured depth)
  dev          measured depth only, and the record looks deviated or horizontal, so the
               depth cannot be used as a vertical depth (see likely_deviated below)
  spud_yr      year drilling began, where reported

Every mapping quotes the agency's code; anything not listed is excluded, never guessed.
"""
from __future__ import annotations
import io, re, zipfile
import numpy as np, pandas as pd
from .geo import read_dbf
from .paths import RAW

R = RAW / 'states'
H_NAME = re.compile(r'(?:\d+H\b|\d+HR\b|[0-9A-Z]-?\d*[NS]H\b|\bH\d*$|HZ|HORIZ|\bXH\b|TFH\b|MBH\b|\d+ ?H$)', re.I)


def _num(s):
    return pd.to_numeric(s, errors='coerce')


def _year(s):
    s = pd.Series(s, dtype='string')
    # ArcGIS date fields arrive as epoch milliseconds
    ms = pd.to_numeric(s.where(s.str.fullmatch(r'-?\d{11,13}(\.0)?', na=False)), errors='coerce')
    from_ms = pd.to_datetime(ms, unit='ms', errors='coerce').dt.year
    y = pd.to_numeric(s.str.extract(r'((?:18|19|20)\d\d)', expand=False), errors='coerce')
    return from_ms.where(from_ms.notna(), y).astype('float')


def _first(*names):
    for n in names:
        p = R / n
        if p.exists():
            return p
    raise FileNotFoundError(f'none of {names} under {R}')


def likely_deviated(st: str, basis, td_ft, spud_yr, name, slant=None) -> np.ndarray:
    """True where only measured depth is reported and the record looks deviated.

    Measured depth along a horizontal lateral overstates vertical depth, and so
    temperature, by a factor of up to two (a Bakken well is ~20,000 ft measured,
    ~10,500 ft vertical). These rules are deliberately narrow and state-specific:
      ND  MD >= 12,500 ft and (spudded 2005 or later, or a horizontal-style name)
      KS  MD >= 7,500 ft and spudded 2010 or later (Mississippian/Hunton horizontal era)
      CO  MD only, spudded 2008 or later (or spud year unknown), and (horizontal-style
          name or MD >= 10,000 ft); and any MD-only record of 15,000 ft or more
      NY  MD only and the DEC 'Slant' field says Horizontal or Directional
    """
    b = pd.Series(basis).astype('string').fillna('')
    md = b.str.startswith('MD').to_numpy()
    td = np.asarray(td_ft, float)
    yr = np.asarray(spud_yr, float)
    nm = pd.Series(name).astype('string').fillna('').str.contains(H_NAME).to_numpy()
    if st == 'ND':
        return md & (td >= 12500) & ((yr >= 2005) | nm)
    if st == 'KS':
        return md & (td >= 7500) & (yr >= 2010)
    if st == 'CO':
        # spud year unknown counts as possibly modern; very deep MD-only records are never trusted as vertical
        return md & (((yr >= 2008) | np.isnan(yr)) & (nm | (td >= 10000)) | (td >= 15000))
    if st == 'NY' and slant is not None:
        sl = pd.Series(slant).astype('string').fillna('').str.lower()
        return md & sl.str.contains('horiz|direc').to_numpy()
    return np.zeros(len(td), bool)


def _frame(st, api, lat, lon, cls, orphan, public, status, wtype, td, basis, op, county, spud, name=None, slant=None):
    idx = pd.Series(api).index
    td = pd.Series(td, index=idx) if np.isscalar(td) or td is None else pd.Series(td).set_axis(idx)
    td = _num(td).where((_num(td) > 0) & (_num(td) < 35000))
    basis = (pd.Series(basis, index=idx) if np.isscalar(basis) or basis is None else pd.Series(basis).set_axis(idx))
    basis = basis.where(td.notna(), None)
    yr = _year(spud).set_axis(idx) if spud is not None else pd.Series(np.nan, index=idx)
    nm = pd.Series(name).set_axis(idx) if name is not None else pd.Series('', index=idx)
    sl = pd.Series(slant).set_axis(idx) if slant is not None else None
    dev = likely_deviated(st, basis, td, yr, nm, sl)
    return pd.DataFrame({'state': st, 'api': api, 'lat': _num(lat), 'lon': _num(lon), 'cls': cls,
                         'orphan_list': orphan, 'public_plug': public, 'raw_status': status, 'raw_type': wtype,
                         'td_ft': td, 'depth_basis': basis, 'dev': dev, 'spud_yr': yr,
                         'operator': op, 'county_src': county})


# ------------------------------------------------------------------- Oklahoma
OK_KEEP = ['PA', 'PASF', 'PASUR', 'PASURSF', 'PAFF', 'TA', 'OR', 'STFD', 'SIFORDER', 'SFFO', 'SFAW']


def ok():
    """OCC RBDMS. PA* plugged; TA temporarily abandoned; OR/STFD/SIFORDER/SFFO/SFAW
    orphaned or in the state-funded plugging queue; AC+DRY drilled dry, not plugged.
    RBDMS carries no total depth."""
    p = _first('ok/rbdms-wells.csv', 'ok/ok_rbdms_reduced.csv.gz')
    d = pd.read_csv(p, dtype=str, usecols=lambda c: c in {'API', 'OPERATOR', 'WELLSTATUS', 'WELLTYPE', 'SYMBOL_CLASS', 'SH_LAT', 'SH_LON', 'COUNTY', 'WELL_NAME'})
    s, t = d.WELLSTATUS.fillna('').str.strip(), d.WELLTYPE.fillna('').str.strip()
    d = d[s.isin(OK_KEEP) | ((s == 'AC') & (t == 'DRY'))].copy()
    s, t = d.WELLSTATUS.str.strip(), d.WELLTYPE.fillna('').str.strip()
    cls = pd.Series(None, index=d.index, dtype=object)
    plugged = s.isin(['PA', 'PASF', 'PASUR', 'PASURSF', 'PAFF'])
    cls[plugged & (t == 'DRY')] = 'DA'
    cls[plugged & (t != 'DRY')] = 'PA'
    cls[s == 'TA'] = 'IN'
    cls[(s == 'AC') & (t == 'DRY')] = 'IN'
    orphan = s.isin(['OR', 'STFD', 'SIFORDER', 'SFFO', 'SFAW'])
    public = s.isin(['PASF', 'PAFF', 'PASURSF'])
    return _frame('OK', d.API, d.SH_LAT, d.SH_LON, cls, orphan, public, s, t, np.nan, None,
                  d.OPERATOR, d.COUNTY, None)


# --------------------------------------------------------------------- Kansas
KS_S2 = ['Inactive Well', 'ON LIST', 'Federal Plugging Project', 'KCC Fee Fund Plugging', 'Plugged with Federal Funds',
         'Unplugged Former Injection Well', 'Approved for Plugging - CP-1 Received', 'Expired Plugging Application (CP-1)',
         'Re-Plugged (non Fee-Fund)', 'Plugged and Abandoned']
KS_COLS = ['API_NUM_NODASH', 'LATITUDE', 'LONGITUDE', 'CURR_OPERATOR', 'ORIG_OPERATOR', 'DEPTH', 'SPUD', 'STATUS', 'STATUS2', 'LEASE', 'WELL']


def _ks_read():
    p = _first('ks/ks_wells.zip', 'ks/ks_wells_reduced.csv.gz')
    if p.suffix == '.zip':
        with zipfile.ZipFile(p) as z:
            member = max((i for i in z.infolist() if i.filename.lower().endswith(('.txt', '.csv'))), key=lambda i: i.file_size)
            raw = z.read(member)
        return pd.read_csv(io.BytesIO(raw), dtype=str, encoding='latin-1', usecols=lambda c: c in KS_COLS)
    return pd.read_csv(p, dtype=str, usecols=lambda c: c in KS_COLS)


def ks():
    """KGS master well list with KCC status. STATUS 'P&A' plugged; 'D&A' dry;
    OTHER(TA|SHUT-IN|TEMP ABD) inactive; STATUS2 'ON LIST' and 'Federal Plugging
    Project' are the KCC orphan list; 'KCC Fee Fund Plugging' and 'Plugged with
    Federal Funds' were plugged with public money. DEPTH is total depth in feet."""
    d = _ks_read()
    s, s2 = d.STATUS.fillna(''), d.STATUS2.fillna('')
    keep = (s.str.contains('P&A', regex=False) | (s == 'D&A')
            | s.str.contains(r'\((?:TA|SHUT-IN|TEMP ABD|Dry|dry)\)', regex=True) | s2.isin(KS_S2))
    d = d[keep].copy()
    s, s2 = d.STATUS.fillna(''), d.STATUS2.fillna('')
    cls = pd.Series(None, index=d.index, dtype=object)
    cls[s.str.contains('P&A', regex=False)] = 'PA'
    cls[s == 'D&A'] = 'DA'
    unpl = ~s.str.contains('P&A', regex=False) & (s != 'D&A')
    cls[unpl & s2.isin(['Inactive Well', 'Unplugged Former Injection Well'])] = 'IN'
    cls[unpl & s.str.contains(r'\((?:TA|SHUT-IN|TEMP ABD)\)', regex=True)] = 'IN'
    cls[unpl & s.str.contains(r'\((?:Dry|dry)\)', regex=True)] = 'DA'
    orphan = unpl & s2.isin(['ON LIST', 'Federal Plugging Project'])
    cls[orphan] = None
    public = s2.isin(['KCC Fee Fund Plugging', 'Plugged with Federal Funds'])
    op = d.CURR_OPERATOR.where(~d.CURR_OPERATOR.fillna('').str.lower().isin(['', 'unavailable']), d.ORIG_OPERATOR)
    name = (d.LEASE.fillna('') + ' ' + d.WELL.fillna('')) if 'LEASE' in d else None
    return _frame('KS', d.API_NUM_NODASH, d.LATITUDE, d.LONGITUDE, cls, orphan, public, s + ' / ' + s2, '',
                  d.DEPTH, 'MD (KGS DEPTH)', op, None, d.SPUD, name)


# ----------------------------------------------------------------- California
def ca():
    """CalGEM WellSTAR. 'Plugged'/'PluggedOnly' plugged (type DH = dry hole);
    'Idle' = no production or injection for 24 consecutive months (PRC 3008).
    The WellSTAR layer carries no total depth."""
    p = _first('ca/ca_wellstar.csv.gz', 'ca/ca_wellstar_reduced.csv.gz')
    d = pd.read_csv(p, dtype=str)
    s, t = d.WellStatus, d.WellType.fillna('')
    d = d[s.isin(['Plugged', 'PluggedOnly', 'Idle'])].copy()
    s, t = d.WellStatus, d.WellType.fillna('')
    cls = pd.Series(None, index=d.index, dtype=object)
    plugged = s.isin(['Plugged', 'PluggedOnly'])
    cls[plugged & (t == 'DH')] = 'DA'
    cls[plugged & (t != 'DH')] = 'PA'
    cls[s == 'Idle'] = 'IN'
    return _frame('CA', d.API, d.Latitude, d.Longitude, cls, False, False, s, t + ' ' + d.WellTypeLabel.fillna(''),
                  np.nan, None, d.OperatorName, d.CountyName, d.get('SpudDate'))


# ------------------------------------------------------------------- New York
def ny():
    """NYS DEC. PA plugged (types DH/DW dry); IN inactive, SI shut-in, TA
    temporarily abandoned. True vertical depth where reported, else drilled depth."""
    p = _first('ny/ny_wells.csv.gz', 'ny/ny_wells.csv')
    d = pd.read_csv(p, dtype=str)
    d.columns = [c.strip() for c in d.columns]
    s, t = d['Well Status'].fillna(''), d['Well Type'].fillna('')
    d = d[(s == 'PA') | s.isin(['IN', 'SI', 'TA'])].copy()
    s, t = d['Well Status'].fillna(''), d['Well Type'].fillna('')
    cls = pd.Series(None, index=d.index, dtype=object)
    cls[(s == 'PA') & t.isin(['DH', 'DW'])] = 'DA'
    cls[(s == 'PA') & ~t.isin(['DH', 'DW'])] = 'PA'
    cls[s.isin(['IN', 'SI', 'TA'])] = 'IN'
    tvd, md = _num(d['True Vertical Depth, ft']), _num(d['Drilled Depth, ft'])
    td = tvd.where(tvd > 0, md.where(md > 0))
    basis = pd.Series(np.where(tvd > 0, 'TVD', np.where(md > 0, 'MD', None)), index=d.index)
    return _frame('NY', d['API Well Number'], d['Surface Latitude'], d['Surface Longitude'], cls, False, False, s, t,
                  td, basis, d['Company Name'], d['County'], d['Date Spudded'], d['Well Name'], d.get('Slant'))


# ------------------------------------------------------------------- Colorado
def co():
    """ECMC well spots. Facility status PA plugged (well class DA = dry);
    SI shut-in, TA temporarily abandoned, AB abandoned-not-plugged. Max_TVD where
    reported, else Max_MD."""
    d = pd.DataFrame(read_dbf(str(R / 'co' / 'Wells.dbf')))
    s, c = d.Facil_Stat, d.Well_Class
    keep = (s == 'PA') | (c == 'DA') | s.isin(['SI', 'TA', 'AB'])
    d = d[keep].copy()
    s, c = d.Facil_Stat, d.Well_Class
    cls = pd.Series(None, index=d.index, dtype=object)
    cls[(s == 'PA') & (c == 'DA')] = 'DA'
    cls[(s == 'PA') & (c != 'DA')] = 'PA'
    cls[(s != 'PA') & (c == 'DA')] = 'DA'
    cls[s.isin(['SI', 'TA', 'AB'])] = 'IN'
    tvd, md = _num(d.Max_TVD), _num(d.Max_MD)
    td = tvd.where(tvd > 0, md.where(md > 0))
    basis = pd.Series(np.where(tvd > 0, 'TVD', np.where(md > 0, 'MD', None)), index=d.index)
    name = d.Well_Name.fillna('') + ' ' + d.Well_Num.fillna('') + ' ' + d.Loc_Name.fillna('')
    return _frame('CO', d.API_Label, d.Latitude, d.Longitude, cls, False, False, s, c, td, basis,
                  d.Operator, None, d.Spud_Date, name)


# --------------------------------------------------------------- North Dakota
def nd():
    """NDIC DMR. PA/PANF plugged; DRY dry hole; IA inactive, TA/TAO/TASC
    temporarily abandoned, AB abandoned-not-plugged. 'td' is measured depth."""
    d = pd.DataFrame(read_dbf(str(R / 'nd' / 'OGD_Wells.dbf')))
    s = d.status
    d = d[s.isin(['PA', 'PANF', 'DRY', 'IA', 'TA', 'TAO', 'TASC', 'AB'])].copy()
    s = d.status
    cls = pd.Series(None, index=d.index, dtype=object)
    cls[s.isin(['PA', 'PANF'])] = 'PA'
    cls[s == 'DRY'] = 'DA'
    cls[s.isin(['IA', 'TA', 'TAO', 'TASC', 'AB'])] = 'IN'
    return _frame('ND', d.api_no, d.latitude, d.longitude, cls, False, False, s, d.well_type, d.td, 'MD',
                  d.operator, d.County, d.spud_date, d.well_name)


LOADERS = {'OK': ok, 'KS': ks, 'CA': ca, 'NY': ny, 'CO': co, 'ND': nd}


def load_all() -> pd.DataFrame:
    parts = []
    for st, f in LOADERS.items():
        df = f().reset_index(drop=True)
        df['source_rows'] = len(df)
        parts.append(df)
    a = pd.concat(parts, ignore_index=True)
    a['td_m'] = a.td_ft * 0.3048
    return a
