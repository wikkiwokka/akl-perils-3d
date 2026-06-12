# AKL Perils 3D

**Auckland's building stock in 3D against flood hazard — built entirely from free, open data.**

Every building on the Auckland isthmus, extruded to its LiDAR-derived height
(DSM − DEM), rendered over Auckland Council's published flood hazard layers.
A proof of concept in cloud-native open geospatial tooling: Python, DuckDB,
GeoParquet, COGs, tippecanoe, PMTiles, MapLibre — zero licence costs, zero
servers, hosted free on GitHub Pages.

> **Live page:** https://wikkiwokka.github.io/akl-perils-3d/
> **Demo (synthetic data, works immediately):** https://wikkiwokka.github.io/akl-perils-3d/demo.html

**This is an educational demonstration, not advice.** Heights are estimates;
hazard layers are council models with known limitations. Nothing here should
inform property, lending or insurance decisions.

---

## How it works

```
LINZ Building Outlines (WFS) ─────────┐
LINZ 1m DEM + DSM COGs (open S3/STAC) ┼─► heights = p90(DSM − DEM) per footprint
Auckland Council flood layers (ArcGIS)┘        │
                                               ▼
                              DuckDB spatial joins → per-building flags
                                               │
                                               ▼
                         tippecanoe → PMTiles → MapLibre 3D web map
```

| Stage | Script | Output |
|---|---|---|
| Fetch footprints | `pipeline/fetch_footprints.py` | `data/raw/footprints_isthmus.parquet` |
| Fetch elevation | `pipeline/fetch_elevation.py` | `data/raw/elevation/…` + manifest |
| Fetch flood layers | `pipeline/fetch_flood.py` | `data/raw/*.geojson` |
| Derive heights | `pipeline/derive_heights.py` | `data/processed/buildings_heights.parquet` |
| Flood intersect | `pipeline/flood_intersect.py` | final parquet + GeoJSONL |
| Build tiles | `pipeline/make_tiles.py` | `docs/tiles/akl.pmtiles` |

All knobs (bounding box, URLs, thresholds) live in `pipeline/config.py`.

---

## One-time setup (Windows + WSL2)

WSL2 runs Ubuntu *inside* Windows — it does not replace or modify your
Windows install, and you can remove it any time.

**1. Install WSL2** — in an *administrator* PowerShell:

```powershell
wsl --install
```

Reboot when prompted, then open "Ubuntu" from the Start menu and create a
Linux username/password when asked.

**2. Inside Ubuntu**, install the toolchain:

```bash
sudo apt update && sudo apt install -y build-essential git make gcc g++ \
    libsqlite3-dev zlib1g-dev

# uv (Python environment manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# tippecanoe (vector tile builder) — built from source
git clone https://github.com/felt/tippecanoe.git ~/tippecanoe
cd ~/tippecanoe && make -j && sudo make install
tippecanoe --version

# Claude Code inside WSL (optional but recommended — it can drive everything below)
curl -fsSL https://claude.ai/install.sh | bash
```

**3. Clone this repo and configure:**

```bash
git clone https://github.com/wikkiwokka/akl-perils-3d.git
cd akl-perils-3d
cp .env.example .env
nano .env        # paste your LINZ API key, save (Ctrl+O, Enter, Ctrl+X)
uv sync          # creates the Python environment
```

**4. Pre-flight check, then run everything:**

```bash
make doctor      # verifies key, source reachability, tippecanoe
make all         # fetch → heights → intersect → tiles  (expect well under an hour)
make serve       # then open http://localhost:8000 in your Windows browser
```

---

## Deploy to GitHub Pages

```bash
git add -A
git commit -m "Build isthmus tiles"
git push
```

Then on github.com → repo → **Settings → Pages** → Source: *Deploy from a
branch* → Branch: `main`, folder: `/docs` → Save. The page appears at
`https://wikkiwokka.github.io/akl-perils-3d/` within a couple of minutes.

`docs/tiles/akl.pmtiles` is committed deliberately so Pages can serve it.
If the file ever exceeds ~95 MB, see the warning printed by `make tiles`
(host it on Cloudflare R2 free tier instead and update the URL in
`docs/index.html`).

---

## Driving this with Claude Code (recommended)

This repo includes a `CLAUDE.md` with project context. From the repo root in
Ubuntu, run `claude` and try:

> "Read CLAUDE.md, run `make doctor`, fix anything that fails, then run
> `make all` and resolve any errors as they come up. Ask me before changing
> anything outside this repo."

The three places most likely to need a live fix (and that Claude Code handles
well) are documented in `CLAUDE.md`: WFS axis order, Auckland Council layer
URLs, and the elevation STAC layout.

---

## Data sources & licences

See [ATTRIBUTION.md](ATTRIBUTION.md). Everything is CC-BY 4.0 (NZ government
open data) or openly licensed software. Code in this repo is MIT.

## Known limitations

- Heights are p90(DSM − DEM) per footprint: overhanging trees inflate some
  buildings; structures newer than the LiDAR survey show default heights
  (flagged `height_source = "default"` and visible in the hover readout).
- Flood layers are Auckland Council's published models — vintage and
  methodology vary, and they are not a substitute for site-specific
  assessment.
- The flood flags are simple geometric intersections, not depth- or
  probability-weighted exposure.

## Roadmap (v2 ideas)

- AlphaEarth / Sentinel change detection: new buildings inside flood-prone
  areas by year (Google Earth Engine, noncommercial).
- SA2-level aggregation joined to Stats NZ census income (affordability lens).
- Full Auckland region extent.
