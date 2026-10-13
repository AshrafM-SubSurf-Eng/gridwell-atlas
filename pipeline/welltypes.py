"""Coarse well-type classes for display. Ordered rules; first match wins.
Raw values are kept in the per-well export so nothing is lost."""
import re
RULES = [
    ('Dry hole',            r'^(dry hole|dry|d&a|dry wildcat|dry & abandoned|dry and abandoned|da)$'),
    ('Injection / disposal', r'inject|disposal|\bswd\b|^wi$|water ?flood|eor|^sw$|^ws?d$|^wiw$'),
    ('Oil & gas',           r'^(oil ?& ?gas|o ?& ?g|og|oil ?/ ?gas( well)?|oil and gas)$'),
    ('Gas',                 r'^g$|gas|cbm|cbg|coal ?bed|methane|^sigw$|^ncg$|^cmg$'),
    ('Oil',                 r'^o$|oil|petroleum'),
    ('Other / test',        r'strat|observ|monitor|water well|^wsw$|storage|test'),
]
NOT_REPORTED = r'^(|not listed|not available|no product specified|well|vertical|horizontal.*|permitted location|sidetrack.*|unknown|n/?a|nt|tm|wl)$'
def classify(raw):
    s = '' if raw is None or raw != raw else str(raw).strip().lower()
    if re.match(NOT_REPORTED, s):
        return 'Not reported'
    for name, pat in RULES:
        if re.search(pat, s):
            return name
    return 'Other / test'
