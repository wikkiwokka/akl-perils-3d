"""Fetch Auckland Council flood hazard layers as GeoJSON.

Layers: Flood Plains (1% AEP), Flood Prone Areas, Overland Flow Paths.
All CC-BY 4.0 via Auckland Council's open data (ArcGIS Hub).

Resolution strategy:
  1. If a service_url is pinned in config.FLOOD_LAYERS, use it.
  2. Otherwise query the Hub search API for the layer name and take the
     best-matching Feature Service.

ArcGIS feature services are paged with resultOffset; geometry filter uses
our AOI bbox so we only pull isthmus features.
"""

import json

from pipeline import config as C
from pipeline.util import die, get_with_retry, log, session


def _resolve_service_url(s, search_name: str) -> str:
    params = {"q": search_name, "limit": 20}
    r = get_with_retry(s, C.AC_HUB_SEARCH, params=params)
    doc = r.json()
    feats = doc.get("features", doc.get("items", []))
    candidates = []
    for f in feats:
        props = f.get("properties", f)
        title = (props.get("title") or props.get("name") or "").strip()
        # Hub items expose the ArcGIS REST url in various fields
        url = (
            props.get("url")
            or (props.get("links") or {}).get("service")
            or ""
        )
        if title.lower() == search_name.lower() and "FeatureServer" in str(url):
            candidates.append(str(url))
    if not candidates:
        # fall back: any title containing the name
        for f in feats:
            props = f.get("properties", f)
            title = (props.get("title") or props.get("name") or "").lower()
            url = str(props.get("url") or "")
            if search_name.lower() in title and "FeatureServer" in url:
                candidates.append(url)
    if not candidates:
        raise LookupError(
            f"Could not resolve a FeatureServer for '{search_name}' via the Hub API. "
            f"Find it manually on data-aucklandcouncil.opendata.arcgis.com and pin "
            f"service_url in pipeline/config.py."
        )
    url = candidates[0].rstrip("/")
    if not url.split("/")[-1].isdigit():
        url = url + "/0"
    return url


def _fetch_layer(s, service_url: str, out_path) -> int:
    w, sth, e, n = C.BBOX_WGS84
    features = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "geometry": json.dumps(
                {"xmin": w, "ymin": sth, "xmax": e, "ymax": n,
                 "spatialReference": {"wkid": 4326}}
            ),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "outSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "resultOffset": offset,
            "resultRecordCount": C.ARCGIS_PAGE_SIZE,
        }
        r = get_with_retry(s, f"{service_url}/query", params=params)
        doc = r.json()
        if "error" in doc:
            raise RuntimeError(f"ArcGIS error from {service_url}: {doc['error']}")
        page = doc.get("features", [])
        features.extend(page)
        log(f"    +{len(page)} (total {len(features)})")
        if len(page) < C.ARCGIS_PAGE_SIZE:
            break
        offset += C.ARCGIS_PAGE_SIZE

    out_path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return len(features)


def main() -> None:
    s = session()
    failures = []
    for key, spec in C.FLOOD_LAYERS.items():
        log(f"Layer: {key} ({spec['search_name']})")
        try:
            url = spec["service_url"] or _resolve_service_url(s, spec["search_name"])
            log(f"  service: {url}")
            n = _fetch_layer(s, url, spec["out"])
            log(f"  saved {n:,} features -> {spec['out']}")
        except Exception as e:  # keep going; report at the end
            log(f"  FAILED: {e}")
            failures.append(key)

    if failures:
        die(
            f"Could not fetch: {', '.join(failures)}. Pin the current FeatureServer "
            f"URL(s) in pipeline/config.py (see comments there) and re-run "
            f"'make flood'. The Auckland Council open data portal is the source "
            f"of truth for current URLs."
        )
    log("All flood layers fetched.")


if __name__ == "__main__":
    main()
