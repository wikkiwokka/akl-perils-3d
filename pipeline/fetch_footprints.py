"""Fetch LINZ NZ Building Outlines (layer 101290) for the area of interest.

Uses the LINZ Data Service WFS with paging. Output: GeoParquet in EPSG:4326.

Known quirk: WFS 2.0 axis order. Koordinates-based services generally expect
bbox as lat,lon (y,x) when the CRS is urn-form EPSG:4326. We try that first
and fall back to lon,lat if the first attempt returns zero features.
"""

import geopandas as gpd
import pandas as pd

from pipeline import config as C
from pipeline.util import die, get_with_retry, log, session


def _fetch_page(s, bbox_str: str, start_index: int) -> dict:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": C.BUILDING_OUTLINES_LAYER,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "bbox": bbox_str,
        "count": C.WFS_PAGE_SIZE,
        "startIndex": start_index,
    }
    url = C.LINZ_WFS_URL.format(key=C.LINZ_API_KEY)
    r = get_with_retry(s, url, params=params)
    return r.json()


def _download_all(s, bbox_str: str) -> list[dict]:
    features: list[dict] = []
    start = 0
    while True:
        log(f"  page startIndex={start} ...")
        data = _fetch_page(s, bbox_str, start)
        page = data.get("features", [])
        features.extend(page)
        log(f"    +{len(page)} features (total {len(features)})")
        if len(page) < C.WFS_PAGE_SIZE:
            break
        start += C.WFS_PAGE_SIZE
    return features


def main() -> None:
    if not C.LINZ_API_KEY:
        die("LINZ_API_KEY is not set. Copy .env.example to .env and add your key.")

    w, sth, e, n = C.BBOX_WGS84
    s = session()

    # Attempt 1: lat,lon order with explicit CRS URI (Koordinates convention)
    bbox_latlon = f"{sth},{w},{n},{e},urn:ogc:def:crs:EPSG::4326"
    log("Fetching building footprints (axis order attempt 1: lat,lon)...")
    features = _download_all(s, bbox_latlon)

    if not features:
        # Attempt 2: lon,lat order
        bbox_lonlat = f"{w},{sth},{e},{n},EPSG:4326"
        log("Zero features returned — retrying with lon,lat axis order...")
        features = _download_all(s, bbox_lonlat)

    if not features:
        die(
            "No footprints returned in either axis order. Check the API key, the "
            "layer id (101290) and the bbox in pipeline/config.py."
        )

    gdf = gpd.GeoDataFrame.from_features(features, crs=C.CRS_WGS84)

    # Keep a stable id and a lean schema
    if "building_id" not in gdf.columns:
        gdf["building_id"] = pd.RangeIndex(len(gdf)).astype("int64")
    keep = [c for c in ("building_id", "name", "use", "suburb_locality", "town_city",
                        "capture_source_name", "last_modified") if c in gdf.columns]
    gdf = gdf[keep + ["geometry"]]

    # Clip precisely to the AOI (bbox query returns boundary-crossers)
    gdf = gdf.clip_by_rect(w, sth, e, n).pipe(
        lambda geoms: gdf.assign(geometry=geoms)
    )
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]

    gdf.to_parquet(C.FOOTPRINTS_RAW)
    log(f"Saved {len(gdf):,} footprints -> {C.FOOTPRINTS_RAW}")


if __name__ == "__main__":
    main()
