"""Derive per-building heights: zonal stats of (DSM - DEM) within each footprint.

Approach
--------
* Tiles are 1 m COGs in EPSG:2193, paired DEM/DSM by identical tile filename
  within a survey.
* For each pair: read both arrays, compute nDSM = DSM - DEM, run zonal stats
  (90th percentile) for footprints intersecting the tile.
* Surveys are processed oldest -> newest; later surveys overwrite earlier
  values, so the most recent LiDAR wins wherever coverage overlaps.
* A building split across tiles keeps the max of its per-tile estimates.

Output: GeoParquet of footprints + height_m, storeys, n_pixels, survey.
"""

import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterstats import zonal_stats
from tqdm import tqdm

from pipeline import config as C
from pipeline.util import die, log


def _survey_sort_key(name: str) -> tuple:
    """Sort surveys by the latest year mentioned in their name (oldest first)."""
    years = [int(y) for y in re.findall(r"(20\d\d)", name)]
    return (max(years) if years else 0, name)


def _pairs_for_survey(spec: dict) -> list[tuple[Path, Path]]:
    dems = {Path(p).name: Path(p) for p in spec.get("dem", [])}
    dsms = {Path(p).name: Path(p) for p in spec.get("dsm", [])}
    common = sorted(set(dems) & set(dsms))
    return [(dems[n], dsms[n]) for n in common]


def main() -> None:
    manifest_path = C.ELEVATION_DIR / "manifest.json"
    if not manifest_path.exists():
        die("No elevation manifest — run 'make elevation' first.")
    if not C.FOOTPRINTS_RAW.exists():
        die("No footprints — run 'make footprints' first.")

    manifest = json.loads(manifest_path.read_text())
    surveys = sorted(manifest, key=_survey_sort_key)
    log(f"Surveys (oldest -> newest): {surveys}")

    gdf = gpd.read_parquet(C.FOOTPRINTS_RAW).to_crs(C.CRS_NZTM)
    gdf = gdf.reset_index(drop=True)
    gdf["_idx"] = gdf.index
    sindex = gdf.sindex

    height = np.full(len(gdf), np.nan)
    npix = np.zeros(len(gdf), dtype=int)
    src_survey = np.array([""] * len(gdf), dtype=object)

    for survey in surveys:
        pairs = _pairs_for_survey(manifest[survey])
        log(f"{survey}: {len(pairs)} DEM/DSM tile pairs")
        for dem_path, dsm_path in tqdm(pairs, desc=survey, unit="tile"):
            with rasterio.open(dsm_path) as dsm, rasterio.open(dem_path) as dem:
                if dsm.shape != dem.shape or dsm.transform != dem.transform:
                    # mismatched grids within a survey are rare; skip loudly
                    log(f"  grid mismatch, skipping {dsm_path.name}")
                    continue
                a_dsm = dsm.read(1, masked=True).astype("float32")
                a_dem = dem.read(1, masked=True).astype("float32")
                ndsm = (a_dsm - a_dem).filled(np.nan)
                transform = dsm.transform
                bounds = dsm.bounds

            cand = list(sindex.intersection((bounds.left, bounds.bottom,
                                             bounds.right, bounds.top)))
            if not cand:
                continue
            sub = gdf.iloc[cand]

            stats = zonal_stats(
                sub.geometry,
                ndsm,
                affine=transform,
                stats=["count"],
                add_stats=None,
                percent_cover_selection=None,
                nodata=np.nan,
                all_touched=False,
                # rasterstats percentile syntax:
                # request percentile via 'percentile_90'
            )
            p90 = zonal_stats(
                sub.geometry, ndsm, affine=transform,
                stats=[C.HEIGHT_STAT], nodata=np.nan,
            )

            for row_i, st_c, st_p in zip(sub["_idx"].to_numpy(), stats, p90):
                cnt = st_c.get("count") or 0
                val = st_p.get(C.HEIGHT_STAT)
                if cnt < C.MIN_PIXELS or val is None or not np.isfinite(val):
                    continue
                # newer survey overwrites; within a survey keep the max
                if src_survey[row_i] != survey:
                    height[row_i] = val
                    npix[row_i] = cnt
                    src_survey[row_i] = survey
                else:
                    if val > height[row_i]:
                        height[row_i] = val
                    npix[row_i] += cnt

    have = np.isfinite(height)
    log(f"Heights derived for {have.sum():,} / {len(gdf):,} footprints "
        f"({100 * have.mean():.1f}%).")

    gdf["height_m"] = np.clip(height, C.MIN_HEIGHT_M, C.MAX_HEIGHT_M)
    gdf.loc[~have, "height_m"] = np.nan
    gdf["storeys"] = np.where(
        have,
        np.clip(np.round(gdf["height_m"] / C.METRES_PER_STOREY), 1, 40),
        np.nan,
    )
    gdf["n_pixels"] = npix
    gdf["lidar_survey"] = src_survey

    # Buildings with no LiDAR coverage get a default 1-storey assumption,
    # flagged so the map can show them differently.
    gdf["height_source"] = np.where(have, "lidar", "default")
    gdf["height_m"] = gdf["height_m"].fillna(3.0)
    gdf["storeys"] = gdf["storeys"].fillna(1)

    gdf = gdf.drop(columns=["_idx"]).to_crs(C.CRS_WGS84)
    gdf.to_parquet(C.HEIGHTS_OUT)
    log(f"Saved -> {C.HEIGHTS_OUT}")


if __name__ == "__main__":
    main()
