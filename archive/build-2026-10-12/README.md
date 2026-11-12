# Build of 12 October 2026

Every figure in the GRIDWELL Atlas paper is computed from this build. The files in this folder are exact copies of `site/data/` and `data/manifest.json` at commit [`fca14b6`](https://github.com/AshrafM-SubSurf-Eng/gridwell-atlas/tree/fca14b6a43a60db9b3f3b98eb3e67873ee046f63) (12 October 2026). They are kept here so that the release which archives them on Zenodo carries the data behind the paper. Later monthly builds differ from this build as the state registries change.

| File | Contents |
|---|---|
| `site/data/stats.json` | National totals, counts by abandonment type and fit rating, temperature-model validation |
| `site/data/candidates.json` | Wells rated A to D, with modelled temperatures, depth, grid distance and energy-community status |
| `site/data/counties.json` | County summaries shown on the atlas map |
| `site/data/counties.topo.json` | County boundaries used by the map |
| `site/data/sources.json`, `site/data/meta.json` | Sources, retrieval dates and build metadata |
| `site/data/changes.json` | Change log of the build (the first build is the baseline, so no changes are listed) |
| `data/manifest.json` | Download address, size and SHA-256 checksum of every input file |

The build was made with version 0.2.0 of the code, which was named "Geothermal Repurposing Inventory of Disused Wells" at that time. Version 1.0.0 renamed it "Abandoned Wells" and added the well lookup; the code at commit `fca14b6` is the exact code that produced these files.

Check the files with `sha256sum -c SHA256SUMS` from this folder.

Data: CC BY 4.0 (see `LICENSE-DATA.md` in the repository root). Inputs keep their own terms.
