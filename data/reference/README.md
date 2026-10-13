# Pinned reference inputs

These are byte-for-byte copies of the federal reference files that GRIDWELL Atlas is built on. They are kept in the repository so that a monthly refresh never depends on a federal server being up, and so that anyone can rebuild a past release exactly.

`pipeline/fetch.py` uses them in this order for every source in `sources.json` with `"group": "reference"`:

1. a file already in `data/raw` whose SHA-256 matches the pin in `sources.json`;
2. the copy in this folder (files ending in `.gz` were compressed with gzip, `mtime=0`, only to keep the repository small, and are decompressed first);
3. a fresh download from the agency URL.

Whichever route is used, the file must hash to the pin in `sources.json`; otherwise the build stops and a review issue is opened. When an agency publishes a new vintage (for example EIA-860 2026 or Census Vintage 2026), the refresh opens an issue; adopting it means replacing the file here, updating its `sha256`, `url` and `vintage` in `sources.json`, and noting the change in `CHANGELOG.md`.

The state well registries are **not** stored here. They are downloaded fresh every month because their changes are what the refresh is looking for.

| Stored as | Layer | Publisher | Licence | Original URL | SHA-256 of the uncompressed file |
|---|---|---|---|---|---|
| `Bottom_Hole_Temperature_Data.csv.gz` | Bottom-hole temperatures | Stanford University / DOE Geothermal Data Repository (Aljubran & Horne) | CC BY 4.0 | <https://gdr.openei.org/files/1592/Raw_BHT_aggregated_data.csv> | `39ceb29f7baec558…` |
| `cb_2025_us_county_500k.zip` | County boundaries | U.S. Census Bureau | Public domain | <https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_500k.zip> | `aa976c00b1819397…` |
| `2025_Gaz_counties_national.zip` | County internal points | U.S. Census Bureau | Public domain | <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_counties_national.zip> | `4c90d0f805779923…` |
| `2025_Gaz_place_national.zip` | Incorporated places | U.S. Census Bureau | Public domain | <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip> | `49644173a453469d…` |
| `sub-est2025.csv.gz` | Place population | U.S. Census Bureau, Population Estimates Program | Public domain | <https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/cities/totals/sub-est2025.csv> | `e3508f5201465913…` |
| `eia8602025.zip` | Grid tie-in points | U.S. Energy Information Administration | Public domain | <https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip> | `2b27929d26cc1da9…` |
| `EC_MSA_FFE_U2025_AllCounties.xlsx` | Energy communities, 2026 status | U.S. Department of the Treasury | Public domain | <https://home.treasury.gov/system/files/131/EC_MSA_FFE_U2025_AllCounties.xlsx> | `60e27818264533ad…` |
| `EC_MSA_FFE_U2024_AllCounties.xlsx` | Energy communities, 2025 status | U.S. Department of the Treasury | Public domain | <https://home.treasury.gov/system/files/131/EC_MSA_FFE_U2024_AllCounties.xlsx> | `54cab8cc59c5dda2…` |
| `EC_MSA_FFE_U2023_AllCounties.xlsx` | Energy communities, 2024 status | U.S. Department of the Treasury | Public domain | <https://home.treasury.gov/system/files/131/EC_MSA_FFE_U2023_AllCounties.xlsx> | `ac7df20d4d53c559…` |
| `EC_MSA_FFE_U2022_AllCounties.xlsx` | Energy communities, 2023 status | U.S. Department of the Treasury | Public domain | <https://home.treasury.gov/system/files/131/EC_MSA_FFE_U2022_AllCounties.xlsx> | `8fe428964872ae45…` |
| `EC_AllTracts_V5.xlsx` | Coal-closure tracts (cumulative) | U.S. Department of the Treasury | Public domain | <https://home.treasury.gov/system/files/131/EC_AllTracts_V5.xlsx> | `95148f860ea2e3e3…` |
| `EC_CC_V5.xlsx` | Coal-closure tract basis | U.S. Department of the Treasury | Public domain | <https://home.treasury.gov/system/files/131/EC_CC_V5.xlsx> | `5d44b59f82c1e44c…` |
| `n-26-39-appendix-1.xlsx` | Energy communities, 2026 (cross-check) | Internal Revenue Service | Public domain | <https://www.irs.gov/pub/irs-drop/n-26-39-appendix-1.xlsx> | `eff46d36709ba85b…` |

## Licences

- U.S. Census Bureau, U.S. Energy Information Administration, U.S. Department of the Treasury and Internal Revenue Service files are works of the U.S. Government and are in the public domain in the United States (17 U.S.C. § 105).
- The bottom-hole-temperature compilation is distributed by the DOE Geothermal Data Repository under CC BY 4.0: Aljubran, M. J., & Horne, R. N., Stanford Thermal Earth Model input data, doi:10.15121/2324793. Redistribution here keeps that licence; cite the original when you reuse it.

Nothing in this folder has been edited. The derived data that GRIDWELL publishes is licensed separately (see `LICENSE-DATA.md`).
