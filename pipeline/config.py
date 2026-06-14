"""Central configuration for the AKL Perils 3D pipeline.

Everything geographic, every URL, and every tunable lives here so the rest
of the pipeline stays free of magic numbers.
"""

from pathlib import Path

import os

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Area of interest: the Auckland isthmus (proof-of-concept extent).
# WGS84 lon/lat: (west, south, east, north).
# Roughly Avondale -> St Heliers, Waitematā Harbour -> Onehunga.
# To scale up later, widen this box — everything downstream follows it.
# ---------------------------------------------------------------------------
BBOX_WGS84 = (174.69, -36.94, 174.87, -36.83)

# NZ Transverse Mercator — all metric processing happens in this CRS.
CRS_NZTM = "EPSG:2193"
CRS_WGS84 = "EPSG:4326"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
DOCS = ROOT / "docs"
TILES = DOCS / "tiles"

for p in (RAW, INTERIM, PROCESSED, TILES):
    p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# LINZ Data Service (requires free API key in .env)
# ---------------------------------------------------------------------------
LINZ_API_KEY = os.getenv("LINZ_API_KEY", "")

# NZ Building Outlines — LDS layer 101290 (CC-BY 4.0, Toitū Te Whenua LINZ)
LINZ_WFS_URL = "https://data.linz.govt.nz/services;key={key}/wfs"
BUILDING_OUTLINES_LAYER = "layer-101290"
WFS_PAGE_SIZE = 10_000

FOOTPRINTS_RAW = RAW / "footprints_isthmus.parquet"

# ---------------------------------------------------------------------------
# LINZ National Elevation Programme — open S3 bucket with STAC metadata.
# 1 m DEM (bare earth) + 1 m DSM (surface incl. buildings), CC-BY 4.0.
# Anonymous HTTPS access, no key needed.
# ---------------------------------------------------------------------------
ELEVATION_STAC_ROOT = "https://nz-elevation.s3-ap-southeast-2.amazonaws.com/catalog.json"
ELEVATION_REGION = "auckland"  # match against child catalog ids/hrefs
ELEVATION_DIR = RAW / "elevation"  # downloads land in dem/<survey>/ and dsm/<survey>/

# ---------------------------------------------------------------------------
# Auckland Council open data — flood hazard layers (CC-BY 4.0).
#
# NOTE: ArcGIS Hub item URLs occasionally change when the council republishes
# layers. If a request 404s, find the current layer on
# https://data-aucklandcouncil.opendata.arcgis.com (search the layer name),
# open "View API Resources" -> copy the FeatureServer/0 query URL here.
# This is a known fragile point — see CLAUDE.md.
# ---------------------------------------------------------------------------
AC_HUB_SEARCH = (
    "https://data-aucklandcouncil.opendata.arcgis.com/api/search/v1/collections/all/items"
)

FLOOD_LAYERS = {
    # key: (human name as published, geometry kind, output filename)
    "flood_plains": {
        "search_name": "Flood Plains",
        "kind": "polygon",
        "out": RAW / "flood_plains.geojson",
        # Direct service URL — leave blank to let fetch_flood.py resolve it
        # via the Hub search API, or paste a known-good URL to pin it.
        "service_url": "",
    },
    "flood_prone": {
        "search_name": "Flood Prone Areas",
        "kind": "polygon",
        "out": RAW / "flood_prone.geojson",
        "service_url": "",
    },
    "overland_flow": {
        "search_name": "Overland Flow Paths",
        "kind": "line",
        "out": RAW / "overland_flow.geojson",
        "service_url": "",
    },
}

ARCGIS_PAGE_SIZE = 2_000

# ---------------------------------------------------------------------------
# Height derivation
# ---------------------------------------------------------------------------
HEIGHT_STAT = "percentile_90"  # robust roof-height estimator within footprint
MIN_HEIGHT_M = 2.0             # clamp: nothing habitable is shorter
MAX_HEIGHT_M = 120.0           # clamp: taller than this on the isthmus = artefact
METRES_PER_STOREY = 3.0
MIN_PIXELS = 4                 # ignore zonal stats with fewer valid 1m pixels

HEIGHTS_OUT = PROCESSED / "buildings_heights.parquet"

# ---------------------------------------------------------------------------
# Flood intersection
# ---------------------------------------------------------------------------
OVERLAND_FLOW_BUFFER_M = 5.0   # building within 5 m of a flow path = flagged

BUILDINGS_FINAL = PROCESSED / "buildings_final.parquet"
BUILDINGS_GEOJSONL = PROCESSED / "buildings_final.geojsonl"
FLOOD_MERGED_GEOJSONL = PROCESSED / "flood_layers.geojsonl"

# ---------------------------------------------------------------------------
# Canopy layer (derive_canopy.py) — gridded vegetation from LiDAR nDSM
# ---------------------------------------------------------------------------
CANOPY_CELL_M = 25.0            # grid cell size in metres (tune for detail vs tile size)
CANOPY_MIN_HEIGHT_M = 5.0       # nDSM at/above this counts as canopy (drops shrubs/garden trees)
CANOPY_MAX_HEIGHT_M = 40.0      # nDSM above this is treated as artefact, not canopy
CANOPY_MIN_COVER_PCT = 50.0     # only keep cells at least this % under canopy (drops lone trees)
CANOPY_FOOTPRINT_BUFFER_M = 2.0 # buffer on building footprints when masking them out
CANOPY_MIN_CELL_PIXELS = 30     # ignore grid cells with fewer valid ground pixels

CANOPY_PARQUET = PROCESSED / "canopy.parquet"
CANOPY_GEOJSONL = PROCESSED / "canopy.geojsonl"

# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------
PMTILES_OUT = TILES / "akl.pmtiles"
