import re, unicodedata
SUFFIX = re.compile(r"\b(county|parish|borough|census area|city and borough|municipality|municipio|planning region|city)\b")
def norm_county(s):
    if s is None or (isinstance(s,float)): return None
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii','ignore').decode().lower().strip()
    s = s.replace('&',' and ')
    s = re.sub(r"\bste\.?\s", "sainte ", s)
    s = re.sub(r"\bst\.?\s", "saint ", s)
    s = SUFFIX.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s or None
