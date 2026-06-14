"""Build the PMTiles archive with tippecanoe.

One archive, up to three named layers:
  buildings — polygons with height/risk attributes (z11–z16)
  flood     — merged hazard polygons/lines (z10–z16)
  change    — AlphaEarth change polygons inside flood zones (z10–z16),
              included only if pipeline.alphaearth_flood_join has been run.

tippecanoe must be on PATH (built from source — see README).
"""

import shutil
import subprocess

from pipeline import config as C
from pipeline.alphaearth_flood_join import CHANGE_FLOOD_GEOJSONL
from pipeline.util import die, log


def main() -> None:
    if shutil.which("tippecanoe") is None:
        die("tippecanoe not found on PATH. See README 'One-time setup' to build it.")
    for p in (C.BUILDINGS_GEOJSONL, C.FLOOD_MERGED_GEOJSONL):
        if not p.exists():
            die(f"Missing {p} — run 'make intersect' first.")

    cmd = [
        "tippecanoe",
        "-o", str(C.PMTILES_OUT),
        "--force",
        "--minimum-zoom=10",
        "--maximum-zoom=16",
        "--drop-densest-as-needed",
        "--extend-zooms-if-still-dropping",
        "--simplification=4",
        "--detect-shared-borders",
        "-L", f"buildings:{C.BUILDINGS_GEOJSONL}",
        "-L", f"flood:{C.FLOOD_MERGED_GEOJSONL}",
    ]

    # The change layer is optional: it only exists after 'make change'. Tiling
    # it when present means index.html's toggle has data; when absent the rest
    # of the map is unaffected.
    if CHANGE_FLOOD_GEOJSONL.exists() and CHANGE_FLOOD_GEOJSONL.stat().st_size > 0:
        cmd += ["-L", f"change:{CHANGE_FLOOD_GEOJSONL}"]
        log(f"Including change layer: {CHANGE_FLOOD_GEOJSONL.name}")
    else:
        log("No change layer found (run 'make change' to add it) — "
            "building buildings + flood only.")

    log(" ".join(cmd))
    subprocess.run(cmd, check=True)

    size_mb = C.PMTILES_OUT.stat().st_size / 1e6
    log(f"Built {C.PMTILES_OUT} ({size_mb:.1f} MB)")
    if size_mb > 95:
        log("WARNING: file exceeds GitHub's 100 MB per-file limit. Options: "
            "raise --minimum-zoom, lower --maximum-zoom, or host the PMTiles "
            "on Cloudflare R2 (free tier) and point docs/index.html at it.")


if __name__ == "__main__":
    main()
