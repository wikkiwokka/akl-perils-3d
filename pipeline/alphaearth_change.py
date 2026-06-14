#!/usr/bin/env python3
"""
alphaearth_change.py
--------------------
Phase 2, Layer 1: AlphaEarth change detection over the Auckland isthmus.

Strategy (bake-down, zero running cost):
  1. Pull two annual AlphaEarth Satellite Embedding images (baseline vs recent).
  2. Compute per-pixel cosine *distance* (1 - dot product) over the 64-D unit
     vectors. Because embeddings are unit-length, the dot product IS cosine
     similarity, so distance = 1 - sum(b_t1 * b_t2).
  3. Threshold to flag "high change" pixels, vectorise.
  4. Export GeoJSON -> alphaearth_flood_join.py (tag with flood class)
     -> tippecanoe -> akl.pmtiles 'change' toggle layer.

Earth Engine free / non-commercial tier. No GCS egress (export via EE -> Drive
or getDownloadURL stays inside the free path for an isthmus-sized AOI).

Datasets:
  GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL  (64-band, 10 m, annual 2017-2024)

Run as a module (like the rest of the pipeline):
  uv run python -m pipeline.alphaearth_change --baseline 2018 --recent 2024 \
      --threshold 0.30 --out data/interim/change.geojson
"""

import argparse
import json
import urllib.request
from pathlib import Path

import ee

from pipeline import config as C
from pipeline.util import die, log

EMBEDDING_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
N_BANDS = 64

# Default output sits in data/interim/, consistent with the rest of the pipeline.
DEFAULT_OUT = C.INTERIM / "change.geojson"


def get_annual_embedding(year, aoi):
    """Return the single 64-band embedding image for a given year over aoi."""
    col = (
        ee.ImageCollection(EMBEDDING_COLLECTION)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(aoi)
    )
    # One image per year per tile; mosaic handles tile seams within the AOI.
    # NOTE: mosaic() drops the native UTM projection -> defaults to WGS84 @ 1deg.
    # That's fine here because every downstream reducer is given scale=10 (m),
    # which forces EE to reproject/operate at 10 m. Do NOT rely on the mosaic's
    # default projection for any area/length math.
    return col.mosaic().clip(aoi)


def cosine_distance(img_a, img_b):
    """
    Per-pixel cosine distance between two unit-length 64-D embedding images.
    Unit-length => dot product == cosine similarity => distance = 1 - dot.
    Result in [0, 2]; for similar land cover it sits near 0.
    """
    dot = img_a.multiply(img_b).reduce(ee.Reducer.sum())
    return ee.Image(1).subtract(dot).rename("change")


def build_change_layer(baseline_year, recent_year, threshold, aoi):
    emb_base = get_annual_embedding(baseline_year, aoi)
    emb_recent = get_annual_embedding(recent_year, aoi)

    dist = cosine_distance(emb_base, emb_recent)

    # Flag high-change pixels.
    high_change = dist.gt(threshold).selfMask().rename("changed")

    # Vectorise to polygons at native 10 m resolution.
    vectors = high_change.reduceToVectors(
        geometry=aoi,
        scale=10,
        geometryType="polygon",
        eightConnected=False,
        labelProperty="changed",
        maxPixels=1e10,
    )

    # Attach the mean change magnitude per polygon for graduated styling.
    vectors = dist.reduceRegions(
        collection=vectors,
        reducer=ee.Reducer.mean().setOutputs(["change_mean"]),
        scale=10,
    )
    return vectors


def _write_local(fc, out_path: Path) -> None:
    """Download the FeatureCollection as GeoJSON straight to disk.

    getDownloadURL returns a temporary URL; we fetch it immediately so the
    pipeline has a real file at a stable path (rather than printing a URL the
    user has to click). Fine for an isthmus-sized output.
    """
    url = fc.getDownloadURL(filetype="GeoJSON")
    log(f"Fetching GeoJSON from EE download URL -> {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, out_path)
    # Sanity-check it parsed as GeoJSON with at least one feature.
    try:
        gj = json.loads(out_path.read_text())
        n = len(gj.get("features", []))
    except Exception as e:  # noqa: BLE001
        die(f"EE download did not return valid GeoJSON: {e}")
    log(f"Wrote {out_path} ({n:,} change polygons)")
    if n == 0:
        log("WARNING: zero change polygons — try lowering --threshold "
            "(e.g. 0.25) or widening the year gap.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", type=int, default=2018)
    ap.add_argument("--recent", type=int, default=2024)
    ap.add_argument("--threshold", type=float, default=0.30,
                    help="cosine-distance cutoff for 'changed' (tune 0.25-0.40)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"output GeoJSON path (default {DEFAULT_OUT})")
    ap.add_argument("--drive", action="store_true",
                    help="export to Google Drive instead of writing locally "
                         "(use for larger AOIs that exceed the sync download limit)")
    ap.add_argument("--project", default=None,
                    help="EE Cloud project for ee.Initialize (free tier ok)")
    args = ap.parse_args()

    ee.Initialize(project=args.project)

    # AOI comes from config so the change layer covers the SAME extent as the
    # buildings/flood layers. (west, south, east, north).
    aoi = ee.Geometry.Rectangle(list(C.BBOX_WGS84))
    fc = build_change_layer(args.baseline, args.recent, args.threshold, aoi)

    if args.drive:
        task = ee.batch.Export.table.toDrive(
            collection=fc,
            description=f"akl_change_{args.baseline}_{args.recent}",
            fileFormat="GeoJSON",
        )
        task.start()
        log(f"Started Drive export task: {task.id}")
        log("Poll with: earthengine task info <id>  (or check the Tasks tab)")
        log("Once it lands in Drive, download it to your --out path and then run "
            "'python -m pipeline.alphaearth_flood_join --change <path>'.")
    else:
        _write_local(fc, Path(args.out))
        log("Next: python -m pipeline.alphaearth_flood_join --change "
            f"{args.out}")


if __name__ == "__main__":
    main()
