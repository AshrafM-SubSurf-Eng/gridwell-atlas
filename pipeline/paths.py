"""Where things live. Every path can be overridden by an environment variable so
the same code runs on a laptop, in CI and on the monthly GitHub Actions refresh."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(os.environ.get('GRIDWELL_ROOT', Path(__file__).resolve().parents[1]))
RAW = Path(os.environ.get('GRIDWELL_RAW', ROOT / 'data' / 'raw'))        # downloads (not committed)
STATIC = ROOT / 'data' / 'static'                                          # small vendored inputs (committed)
BUILD = Path(os.environ.get('GRIDWELL_BUILD', ROOT / 'build'))            # per-run outputs (not committed)
SITE = ROOT / 'site'                                                       # the published page
SITE_DATA = SITE / 'data'
MANIFEST = ROOT / 'data' / 'manifest.json'                                 # what was fetched, when, checksums
SOURCES = ROOT / 'sources.json'                                            # the source registry

for _d in (RAW, BUILD, SITE_DATA):
    _d.mkdir(parents=True, exist_ok=True)
