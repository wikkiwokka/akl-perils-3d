"""Download 1 m DEM and DSM tiles from the LINZ National Elevation Programme.

The data sits in a public S3 bucket (anonymous HTTPS) with a STAC catalog:
    root catalog -> region catalogs (e.g. auckland) -> dataset collections
    (e.g. <survey>/dem_1m/2193, <survey>/dsm_1m/2193) -> items -> COG assets.

Strategy:
  * Walk every Auckland collection whose id/href marks it as dem_1m or dsm_1m.
  * Keep items whose WGS84 bbox intersects our AOI.
  * Download tiles grouped by survey; derive_heights.py processes surveys
    oldest -> newest so newer LiDAR wins where surveys overlap.

If LINZ restructures the catalog this script may need a path tweak — it
fails loudly with the URL it was reading. See CLAUDE.md.
"""

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from tqdm import tqdm

from pipeline import config as C
from pipeline.util import die, get_with_retry, log, session


def _read_json(s, url: str) -> dict:
    return get_with_retry(s, url).json()


def _abs(base_url: str, href: str) -> str:
    if href.startswith("http"):
        return href
    return urljoin(base_url, href)


def _bbox_intersects(b: list[float]) -> bool:
    w, sth, e, n = C.BBOX_WGS84
    bw, bs, be, bn = b[0], b[1], b[2], b[3]
    return not (be < w or bw > e or bn < sth or bs > n)


def _walk_region_collections(s, root_url: str) -> list[tuple[str, str]]:
    """Return [(collection_url, kind)] for kind in {'dem','dsm'} in the region."""
    root = _read_json(s, root_url)
    region_links = [
        l for l in root.get("links", [])
        if l.get("rel") == "child" and C.ELEVATION_REGION in l.get("href", "").lower()
    ]
    if not region_links:
        die(f"No '{C.ELEVATION_REGION}' child catalog found at {root_url}")

    out: list[tuple[str, str]] = []
    stack = [_abs(root_url, l["href"]) for l in region_links]
    while stack:
        url = stack.pop()
        doc = _read_json(s, url)
        for l in doc.get("links", []):
            href = l.get("href", "")
            absu = _abs(url, href)
            if l.get("rel") == "child":
                stack.append(absu)
            # collections appear either as child links ending in collection.json
            # or as rel=child catalogs one level up — handle both
        if doc.get("type") == "Collection" or "extent" in doc:
            low = url.lower()
            if "dem_1m" in low:
                out.append((url, "dem"))
            elif "dsm_1m" in low:
                out.append((url, "dsm"))
    return out


def _items_of(s, collection_url: str) -> list[str]:
    doc = _read_json(s, collection_url)
    return [
        _abs(collection_url, l["href"])
        for l in doc.get("links", [])
        if l.get("rel") == "item"
    ]


def _survey_name(collection_url: str) -> str:
    # .../auckland/<survey>/dem_1m/2193/collection.json -> <survey>
    m = re.search(r"/auckland/([^/]+)/d[se]m_1m/", collection_url)
    return m.group(1) if m else "unknown_survey"


def main() -> None:
    s = session()
    log(f"Walking elevation STAC from {C.ELEVATION_STAC_ROOT} ...")
    collections = _walk_region_collections(s, C.ELEVATION_STAC_ROOT)
    if not collections:
        die("Found no dem_1m/dsm_1m collections for the region — catalog layout may have changed.")
    log(f"Found {len(collections)} DEM/DSM collections in region '{C.ELEVATION_REGION}'.")

    manifest: dict[str, dict] = {}
    n_downloaded = 0

    for coll_url, kind in collections:
        survey = _survey_name(coll_url)
        item_urls = _items_of(s, coll_url)
        wanted = []
        for iu in item_urls:
            item = _read_json(s, iu)
            if "bbox" in item and _bbox_intersects(item["bbox"]):
                wanted.append(item)
        if not wanted:
            continue
        log(f"  {survey} / {kind}: {len(wanted)} intersecting tiles")

        dest_dir = C.ELEVATION_DIR / kind / survey
        dest_dir.mkdir(parents=True, exist_ok=True)

        for item in tqdm(wanted, desc=f"{survey}/{kind}", unit="tile"):
            assets = item.get("assets", {})
            # the COG asset is the one with a .tiff/.tif href
            cog = next(
                (a for a in assets.values() if str(a.get("href", "")).lower().endswith((".tif", ".tiff"))),
                None,
            )
            if cog is None:
                continue
            url = _abs(coll_url, cog["href"])
            fname = Path(url).name
            dest = dest_dir / fname
            if not dest.exists():
                r = get_with_retry(s, url, timeout=300)
                dest.write_bytes(r.content)
                n_downloaded += 1
            manifest.setdefault(survey, {}).setdefault(kind, []).append(str(dest))

    if not manifest:
        die("No elevation tiles intersected the AOI — check BBOX_WGS84 and region name.")

    # Only keep surveys that have BOTH dem and dsm (we need the pair)
    paired = {k: v for k, v in manifest.items() if "dem" in v and "dsm" in v}
    dropped = set(manifest) - set(paired)
    if dropped:
        log(f"  note: dropping surveys without a DEM+DSM pair: {sorted(dropped)}")

    out = C.ELEVATION_DIR / "manifest.json"
    out.write_text(json.dumps(paired, indent=2))
    log(f"Downloaded {n_downloaded} new tiles. Manifest ({len(paired)} surveys) -> {out}")


if __name__ == "__main__":
    main()
