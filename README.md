# GRIDWELL Atlas

**Geothermal Repurposing Inventory of Abandoned Wells** — a self-updating national screen of abandoned oil and gas wells in the United States for repurposing as Enhanced Geothermal System (EGS) wells.

**Live atlas:** https://ashrafm-subsurf-eng.github.io/gridwell-atlas/  
**Author:** Ashraf Mohammed, Independent Researcher · ORCID [0009-0000-9232-1466](https://orcid.org/0009-0000-9232-1466)  
**Version:** 1.0.0. Screening information, not engineering, legal or tax advice.

## What it does

GRIDWELL puts every abandoned well it can source into one inventory and asks, for each well and each county:

1. **What kind of abandoned well is it?** Orphaned wells are abandoned wells whose operator is unknown or insolvent, so they are not treated as a separate population. Every well gets one abandonment type, which decides how the wellbore can be reached and who can sign for it:

   | Type | Meaning | EGS access |
   |---|---|---|
   | IN | Inactive, unplugged, operator of record (temporarily abandoned, idle, shut-in) | 1 · best: casing in place, an owner who can transfer it |
   | OR | Orphaned, unplugged (no responsible operator; state or USGS list) | 2 · transfer first |
   | PA | Plugged and abandoned (including orphans since plugged with public money) | 3 · re-entry: plugs must be drilled out |
   | DA | Dry and abandoned (drilled, never produced) | 4 · data well: often no production casing |

2. **How hot is the rock at the well's own bottom?** Temperature is estimated at each well's **vertical** total depth from a depth-matched bottom-hole-temperature field, and at 5,000, 10,000 and 15,000 ft (1,524, 3,048 and 4,572 m) for every well.

3. **How well does it fit EGS?** Type × temperature at total depth gives a rating:
   - **A** best fit: inactive, unplugged, operator of record, ≥ 302 °F (150 °C) at total depth
   - **B** strong fit after ownership transfer: orphaned, unplugged, ≥ 302 °F (150 °C)
   - **C** conditional: plugged well at EGS grade, or unplugged well at 248–302 °F (120–150 °C) needing deepening
   - **D** limited: dry hole ≥ 248 °F (120 °C), or plugged well at 248–302 °F (120–150 °C)
   - **E** below EGS grade at total depth (< 248 °F / 120 °C)
   - **U** not graded: no vertical total depth on record

4. **Can it reach the grid, and does it earn the tax-credit bonus?** Distance to the nearest power plant that ties in at ≥ 69 kV (EIA-860), distance to towns, and energy-community status under IRS Notice 2026-39.

Field units come first with SI units in brackets throughout; the page has a switch for SI first.

## How it stays current

`.github/workflows/refresh.yml` runs at 09:17 UTC on the 3rd of every month:

1. **Fetch** (`pipeline/fetch.py`): re-downloads the six state registries listed in `sources.json` and checksums each file. Federal reference layers are pinned by SHA-256 and kept as exact copies in `data/reference`, so the build does not depend on a federal server being up; a changed upstream file stops the build and opens an issue rather than silently changing results. Newer annual vintages (Census, EIA-860) and changes to watched pages (USGS orphaned-well release, Treasury energy-community page) also open review issues. A registry that fails to download falls back to last month's cached copy and is marked stale on the page.
2. **Build** (`pipeline/build.py`): rebuilds the inventory, temperatures, EGS ratings and county files. If a state's well count falls by more than 20% or rises by more than 50% against the published build (more often a changed agency file layout than a real change), the published data are left as they were and a review issue is opened; re-run with *allow large change* once the change is confirmed.
3. **Compare** (`pipeline/diff.py`): matches the new inventory against the previous release's `snapshot.csv.gz` and records the wells that joined (newly recorded as plugged, dry, temporarily abandoned, idle, shut-in or orphaned), changed type, or left.
4. **Publish**: commits `site/data`, appends a line to `CHANGELOG.md`, creates a dated `data-YYYY-MM-DD` release with the snapshot and statistics, and redeploys GitHub Pages.

Run it by hand from the Actions tab (**Monthly data refresh → Run workflow**, tick *force* to rebuild even if nothing changed).

## Data

| Layer | Source | Refresh |
|---|---|---|
| Abandoned wells | Oklahoma Corporation Commission (RBDMS), Kansas Geological Survey / KCC, CalGEM WellSTAR, NYS DEC, Colorado ECMC, North Dakota DMR | Monthly |
| Documented orphaned wells (26 states) | USGS Documented Unplugged Orphaned Oil and Gas Well dataset, 2022 (CC0), deduplicated in ORPHANHEAT v0.1 | Vendored; release watched |
| Bottom-hole temperatures | Stanford Thermal Earth Model input set (Aljubran & Horne), DOE GDR, doi:10.15121/2324793 (CC BY 4.0) | Pinned |
| Grid tie-in | EIA Form EIA-860, 2025 final | Pinned; new vintage flagged |
| Counties, towns, population | U.S. Census Bureau 2025 boundaries, Gazetteer and Vintage 2025 estimates | Pinned; new vintage flagged |
| Energy communities | U.S. Treasury data sets; IRS Notice 2026-39 Appendix 1 | Pinned; page watched |

Full URLs, licences and checksums: `sources.json` and `data/manifest.json`.

## Temperature model

Harrison-corrected bottom-hole temperatures are turned into gradients from a 59 °F (15 °C) surface. For a target depth *z*, only measurements taken between 0.75 *z* and 1.25 *z* are used: the 12 nearest within 46.6 mi (75 km), with readings more than 3 median absolute deviations from the local median rejected, inverse-distance weighted with a 0.6 mi (1 km) floor. Each build re-checks the model on 20,000 held-out measurements and publishes the errors in `site/data/stats.json` (`qa.thermal.validation`). Wells that report only measured depth on an apparently horizontal or deviated record are not graded at total depth.

## Run it locally

```bash
pip install -r requirements.txt
python -m pipeline.fetch          # downloads into data/raw (about 400 MB)
python -m pipeline.build          # writes site/data/*.json
python -m http.server -d site     # open http://localhost:8000
python -m pytest -q tests         # offline tests, no downloads needed
```

## Tools used

The author used Claude (Anthropic), an AI assistant, as a tool to get and process the data and to write the code and the atlas page.

## Licence and citation

Code: MIT (`LICENSE`). Derived data: CC BY 4.0 (`LICENSE-DATA.md`). Inputs keep their own terms. Cite with `CITATION.cff`.
