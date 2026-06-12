# CLAUDE.md — project context for Claude Code

## What this is
Open-data proof of concept: 3D map of Auckland isthmus buildings (heights
derived from LINZ LiDAR DSM−DEM) with Auckland Council flood hazard flags,
served as PMTiles + MapLibre from docs/ on GitHub Pages. Personal,
noncommercial, skill-building project. Owner: wikkiwokka.

## Commands
- `make doctor` — pre-flight checks (run this first)
- `make all` — full pipeline: fetch → heights → intersect → tiles
- `make serve` — local preview at http://localhost:8000
- Individual stages: `make footprints | elevation | flood | heights | intersect | tiles`
- Environment: `uv sync`; secrets in `.env` (never commit; `.env` is git-ignored)

## Architecture
pipeline/config.py holds ALL urls/bbox/thresholds. Scripts are small,
single-purpose, idempotent (re-runs skip existing downloads). Data flows
data/raw → data/processed → docs/tiles/akl.pmtiles. docs/ is the deployed
site (index.html real data, demo.html synthetic).

## Known fragile points (fix these locally if they break)
1. **LINZ WFS axis order** (fetch_footprints.py): tries lat,lon then lon,lat.
   If both return zero, inspect one raw WFS response and adjust.
2. **Auckland Council layer URLs** (fetch_flood.py): Hub item URLs drift.
   If resolution fails, find the layer on
   data-aucklandcouncil.opendata.arcgis.com, copy its FeatureServer/N query
   URL, pin it in config.FLOOD_LAYERS[...]["service_url"].
3. **Elevation STAC layout** (fetch_elevation.py): walks
   nz-elevation.s3-ap-southeast-2.amazonaws.com/catalog.json → auckland →
   */dem_1m|dsm_1m/* collections. If LINZ restructures, adjust the walk;
   fail-loud messages include the URL being read.
4. **DuckDB spatial extension** needs one-off internet access on first
   `INSTALL spatial`.

## Guardrails
- Never commit `.env`, anything in `data/`, or any IAG-related material.
- Keep all data sources free + open (CC-BY etc.); no commercial APIs.
- Keep the disclaimer + attribution footer intact on all pages.
- Aggregate-only analysis is fine to extend; do not add address lookup or
  per-address risk search features without the owner's explicit say-so.
