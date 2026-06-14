"""Derive a gridded canopy layer from LiDAR: vegetation height/cover per grid cell.

Approach (reuses derive_heights.py mechanics)
---------------------------------------------
* Same 1 m DEM/DSM COG pairs, same nDSM = DSM - DEM, same oldest -> newest
  survey ordering (later surveys overwrite earlier cells).
* Instead of sampling nDSM *inside* building footprints, we do the opposite:
  - keep pixels whose nDSM is in the vegetation band
    (CANOPY_MIN_HEIGHT_M .. CANOPY_MAX_HEIGHT_M) — drops grass/cars/noise and
    tall artefacts;
  - knock out building footprints (rasterised, with a small buffer) so roofs
    aren't mistaken for canopy;
  - bin the surviving "vegetation" pixels into a regular grid over the AOI.
* Per cell we record canopy COVER (% of valid ground pixels under vegetation)
  and mean canopy HEIGHT. The frontend extrudes cells by height and colours by
  cover, so the map reads as a 3D green surface beside the buildings.

Output: GeoParquet (analysis) + GeoJSONL (tiling). The GeoJSONL is tiled by
make_tiles.py into a 'canopy' layer the frontend toggles.

CAVEATS (state these wherever the layer is shown):
  * Canopy only exists where LiDAR exists, and reflects the survey date —
    vegetation changes faster than buildings, so it's "as flown".
  * nDSM can't tell a tree from any other tall non-building object; the height
    band catches most, but it's a vegetation PROXY, not a botanical survey.

Run as a module:
  uv run python -m pipeline.derive_canopy
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import box
from tqdm import tqdm

from pipeline import config as C
from pipeline.derive_heights import _pairs_for_survey, _survey_sort_key
from pipeline.util import die, log

# Output paths live in config (alongside the other processed artefacts).
CANOPY_PARQUET = C.CANOPY_PARQUET
CANOPY_GEOJSONL = C.CANOPY_GEOJSONL


def main() -> None:
    manifest_path = C.ELEVATION_DIR / "manifest.json"
    if not manifest_path.exists():
        die("No elevation manifest — run 'make elevation' first.")
    if not C.FOOTPRINTS_RAW.exists():
        die("No footprints — run 'make footprints' first.")

    cell_m = C.CANOPY_CELL_M
    lo, hi = C.CANOPY_MIN_HEIGHT_M, C.CANOPY_MAX_HEIGHT_M

    # AOI in NZTM, snapped to a clean grid origin.
    aoi_wgs = box(*C.BBOX_WGS84)
    aoi_nztm = gpd.GeoSeries([aoi_wgs], crs=C.CRS_WGS84).to_crs(C.CRS_NZTM)
    minx, miny, maxx, maxy = aoi_nztm.total_bounds
    minx, miny = np.floor(minx / cell_m) * cell_m, np.floor(miny / cell_m) * cell_m
    ncols = int(np.ceil((maxx - minx) / cell_m))
    nrows = int(np.ceil((maxy - miny) / cell_m))
    log(f"Grid: {ncols} x {nrows} cells @ {cell_m} m "
        f"({ncols * nrows:,} cells over AOI)")

    # Footprints in NZTM, buffered slightly so roof edges don't leak into canopy.
    foot = gpd.read_parquet(C.FOOTPRINTS_RAW).to_crs(C.CRS_NZTM)
    foot["geometry"] = foot.geometry.buffer(C.CANOPY_FOOTPRINT_BUFFER_M)

    # Per-survey accumulators. We track, per cell: count of valid ground pixels,
    # count of vegetation pixels, and summed veg height (for a mean later).
    # "Latest survey wins" is handled by stamping each cell with the survey that
    # last wrote it and resetting when a newer survey touches it.
    valid_px = np.zeros(nrows * ncols, dtype=np.int64)
    veg_px = np.zeros(nrows * ncols, dtype=np.int64)
    veg_sum = np.zeros(nrows * ncols, dtype=np.float64)
    cell_survey = np.array([""] * (nrows * ncols), dtype=object)

    manifest = json.loads(manifest_path.read_text())
    surveys = sorted(manifest, key=_survey_sort_key)
    log(f"Surveys (oldest -> newest): {surveys}")

    for survey in surveys:
        pairs = _pairs_for_survey(manifest[survey])
        log(f"{survey}: {len(pairs)} DEM/DSM tile pairs")
        for dem_path, dsm_path in tqdm(pairs, desc=survey, unit="tile"):
            with rasterio.open(dsm_path) as dsm, rasterio.open(dem_path) as dem:
                if dsm.shape != dem.shape or dsm.transform != dem.transform:
                    log(f"  grid mismatch, skipping {dsm_path.name}")
                    continue
                a_dsm = dsm.read(1, masked=True).astype("float32")
                a_dem = dem.read(1, masked=True).astype("float32")
                ndsm = (a_dsm - a_dem).filled(np.nan)
                transform = dsm.transform
                t_bounds = dsm.bounds
                h, w = ndsm.shape

            # Rasterise buffered footprints onto this tile's grid (1 = building).
            # Pixels under buildings are excluded from BOTH valid and veg counts.
            tile_geom = box(t_bounds.left, t_bounds.bottom,
                            t_bounds.right, t_bounds.top)
            local = foot[foot.intersects(tile_geom)]
            if len(local):
                bldg_mask = rasterize(
                    ((g, 1) for g in local.geometry),
                    out_shape=(h, w), transform=transform,
                    fill=0, dtype="uint8", all_touched=True,
                ).astype(bool)
            else:
                bldg_mask = np.zeros((h, w), dtype=bool)

            # Valid ground = finite nDSM, not under a building.
            finite = np.isfinite(ndsm)
            ground = finite & ~bldg_mask
            veg = ground & (ndsm >= lo) & (ndsm <= hi)

            # Map each pixel to a grid cell via its world coordinate. Build the
            # per-pixel cell index once, then bincount the masks into it.
            rows_idx, cols_idx = np.nonzero(ground)
            if rows_idx.size == 0:
                continue
            xs = transform.c + (cols_idx + 0.5) * transform.a
            ys = transform.f + (rows_idx + 0.5) * transform.e
            gc = ((xs - minx) / cell_m).astype(np.int64)
            gr = ((ys - miny) / cell_m).astype(np.int64)
            inside = (gc >= 0) & (gc < ncols) & (gr >= 0) & (gr < nrows)
            if not inside.any():
                continue
            flat = (gr[inside] * ncols + gc[inside]).astype(np.int64)

            veg_here = veg[rows_idx[inside], cols_idx[inside]]
            ndsm_here = ndsm[rows_idx[inside], cols_idx[inside]]

            # Cells this tile touches.
            touched = np.unique(flat)
            # Reset cells whose last writer was an older survey (latest wins).
            stale = touched[cell_survey[touched] != survey]
            if stale.size:
                older = stale[cell_survey[stale] != ""]
                valid_px[older] = 0
                veg_px[older] = 0
                veg_sum[older] = 0.0
                cell_survey[stale] = survey

            valid_px += np.bincount(flat, minlength=nrows * ncols)
            veg_px += np.bincount(flat[veg_here], minlength=nrows * ncols)
            veg_sum += np.bincount(flat[veg_here],
                                   weights=ndsm_here[veg_here],
                                   minlength=nrows * ncols)

    # Cover % per cell (vegetation pixels / valid ground pixels). Computed for
    # every cell first so we can filter on density.
    with np.errstate(divide="ignore", invalid="ignore"):
        cover = np.where(valid_px > 0, veg_px / valid_px * 100.0, 0.0)

    # Keep cells with enough valid pixels AND dense enough cover. The cover
    # threshold is the main noise filter: it drops sparse suburban cells (a lone
    # backyard tree covers only a small fraction of a cell) and keeps massed
    # vegetation — parks, forest, tree-lined avenues.
    has = (
        (valid_px >= C.CANOPY_MIN_CELL_PIXELS)
        & (veg_px > 0)
        & (cover >= C.CANOPY_MIN_COVER_PCT)
    )
    n_cells = int(has.sum())
    log(f"Canopy present in {n_cells:,} / {nrows * ncols:,} grid cells "
        f"(cover >= {C.CANOPY_MIN_COVER_PCT:.0f}%).")
    if n_cells == 0:
        die("No canopy cells — lower CANOPY_MIN_COVER_PCT or CANOPY_MIN_HEIGHT_M.")

    idx = np.nonzero(has)[0]
    pct = cover[idx].round(1)
    mean_h = (veg_sum[idx] / veg_px[idx]).round(1)

    rows = idx // ncols
    cols = idx % ncols
    geoms = [box(minx + c * cell_m, miny + r * cell_m,
                 minx + (c + 1) * cell_m, miny + (r + 1) * cell_m)
             for c, r in zip(cols, rows)]

    gdf = gpd.GeoDataFrame(
        {"canopy_pct": pct, "canopy_height_m": mean_h},
        geometry=geoms, crs=C.CRS_NZTM,
    ).to_crs(C.CRS_WGS84)

    gdf.to_parquet(CANOPY_PARQUET)
    log(f"Saved -> {CANOPY_PARQUET}")

    with open(CANOPY_GEOJSONL, "w") as f:
        for _, row in gdf.iterrows():
            f.write(json.dumps({
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": {
                    "canopy_pct": float(row["canopy_pct"]),
                    "canopy_height_m": float(row["canopy_height_m"]),
                },
            }) + "\n")
    log(f"Wrote {CANOPY_GEOJSONL.name} ({n_cells:,} cells for tiling)")


if __name__ == "__main__":
    main()
