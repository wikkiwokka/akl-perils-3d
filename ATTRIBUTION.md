# Data sources and attribution

All input data is free, open, and used under its published licence.
This page satisfies the CC-BY 4.0 attribution requirements.

| Dataset | Publisher | Licence | Used for |
|---|---|---|---|
| NZ Building Outlines (layer 101290) | Toitū Te Whenua Land Information New Zealand | CC-BY 4.0 | Building footprints |
| NZ 1 m DEM & DSM (National Elevation Programme, `nz-elevation` open bucket) | Toitū Te Whenua LINZ and survey co-funders (licensors listed per-survey in STAC metadata) | CC-BY 4.0 | LiDAR-derived building heights |
| Flood Plains, Flood Prone Areas, Overland Flow Paths | Auckland Council (open data / GeoMaps) | CC-BY 4.0 | Flood hazard overlays and per-building flags |
| Basemap tiles & style | OpenFreeMap; map data © OpenStreetMap contributors | ODbL (data), open styles | Web map background |

Software: MapLibre GL JS (BSD), PMTiles (BSD), tippecanoe (BSD), DuckDB (MIT),
GeoPandas/Shapely/Rasterio (BSD), rasterstats (BSD), uv (MIT/Apache).

Derived outputs in this repository (heights, flags, tiles) are published under
CC-BY 4.0; please attribute "wikkiwokka / akl-perils-3d" plus the upstream
sources above.

**Disclaimer:** educational demonstration only. Height values are estimates
derived from LiDAR surfaces; flood layers are Auckland Council's published
hazard models and carry their own assumptions and limitations. Not suitable
for property, lending, valuation or insurance decisions.
