# AKL Perils 3D

**Auckland's building stock in 3D against flood hazard — built entirely from free, open data.**

Every building on the Auckland isthmus, extruded to its LiDAR-derived height
(DSM − DEM), rendered over Auckland Council's published flood hazard layers.
A personal proof of concept in cloud-native open geospatial tooling: Python,
DuckDB, GeoParquet, COGs, tippecanoe, PMTiles, MapLibre — zero licence costs,
zero servers, hosted free on GitHub Pages.

> **Live page:** https://wikkiwokka.github.io/akl-perils-3d/
> **Demo (synthetic data, works immediately):** https://wikkiwokka.github.io/akl-perils-3d/demo.html

---

## Purpose

This is an **educational demonstration** — a personal, non-commercial project
built to explore open geospatial data and modern tiling tooling. It is not a
product, not a service, and not affiliated with any organisation.

**Nothing here is advice.** Heights are estimates and the hazard layers are
council models with known limitations. Nothing in this project should be used
to inform property, lending, insurance, or any other real-world decision.

---

## What it does

The map shows, for the Auckland isthmus:

- every building footprint extruded to an estimated height from open LiDAR;
- a colour toggle between building height/storeys and flood exposure;
- Auckland Council's published flood layers (flood plain, flood prone,
  overland flow);
- a hover readout of height, storeys, exposure, and the LiDAR survey used;
- a 2D / 3D pitch toggle and an aerial-imagery basemap.

All processing runs locally and outputs a single static tile archive served
from `/docs` — there is no backend.

---

## Data sources & licences

All inputs are openly licensed and used in accordance with their terms.
Building outlines and elevation come from Toitū Te Whenua LINZ open data;
flood hazard layers from Auckland Council open data; the basemap and aerial
imagery from their respective open providers. New Zealand government open data
is CC-BY 4.0. See [ATTRIBUTION.md](ATTRIBUTION.md) for full attributions.

Code in this repository is MIT licensed. Derived data outputs are CC-BY 4.0.

---

## Known limitations

- Building heights are a per-footprint statistic of (DSM − DEM): overhanging
  trees inflate some buildings, and structures newer than the LiDAR survey
  fall back to a default height (flagged in the hover readout).
- Flood layers are Auckland Council's published models — vintage and
  methodology vary, and they are not a substitute for site-specific
  assessment.
- Exposure flags are simple geometric intersections, not depth- or
  probability-weighted.

These are inherent to a demonstration built on open, generalised data and are
the reason the map is for illustration only.