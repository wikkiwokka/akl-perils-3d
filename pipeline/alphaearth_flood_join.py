"""Tag AlphaEarth change polygons with flood-hazard class via DuckDB spatial joins.

This is the outstanding step that gives alphaearth_change.py its payoff: it takes
the change polygons (high cosine-distance areas between two embedding years) and
asks *which of them fall inside a flood hazard zone* — i.e. "where is the built
environment changing inside places we already know flood".

Deliberately mirrors pipeline/flood_intersect.py so behaviour is identical:
  * work in NZTM (C.CRS_NZTM) for metre-true joins, emit WGS84 (C.CRS_WGS84)
  * read the SAME flood layers from C.FLOOD_LAYERS (GeoJSON in data/raw/)
  * buffer the overland-flow LINE layer by C.OVERLAND_FLOW_BUFFER_M, exactly as
    flood_intersect does — without this, overland_flow barely intersects anything
  * risk priority: flood_plain > flood_prone > overland_flow > none

Unlike the building join, change polygons are areas, not point-in-zone, so we
also record how much of each polygon falls inside its assigned zone
(`overlap_frac`) to let you filter incidental edge clips.

Input:  change polygons GeoJSON from alphaearth_change.py (WGS84; carries
        `change_mean`, the mean cosine distance per polygon).
Output: GeoParquet (analysis) + GeoJSONL (tippecanoe input). The GeoJSONL is
        tiled by make_tiles.py into a 'change' layer the frontend toggles.
        Each feature carries flood_class + change_mean for styling.

Run as a module (like the rest of the pipeline), NOT as a bare script:
  uv run python -m pipeline.alphaearth_flood_join --change data/interim/change.geojson
"""

import argparse
import json
from pathlib import Path

import duckdb
import geopandas as gpd

from pipeline import config as C
from pipeline.util import die, log

# Outputs live alongside the other processed artefacts.
CHANGE_FLOOD_PARQUET = C.PROCESSED / "change_flood.parquet"
CHANGE_FLOOD_GEOJSONL = C.PROCESSED / "change_flood.geojsonl"

# Keep only change polygons whose share inside a flood zone clears this fraction.
# Edge clips (a polygon barely grazing a zone boundary) fall below it. Tune
# alongside the upstream cosine-distance threshold against known sites.
DEFAULT_MIN_OVERLAP_FRAC = 0.10


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--change", required=True,
                    help="Change polygons GeoJSON from alphaearth_change.py (WGS84)")
    ap.add_argument("--min-overlap-frac", type=float, default=DEFAULT_MIN_OVERLAP_FRAC,
                    help="Min share of a change polygon inside a flood zone to keep it "
                         "as in-zone (filters edge clips). Default 0.10")
    ap.add_argument("--keep-none", action="store_true",
                    help="Also write change polygons that fall in NO flood zone. "
                         "Default off: the map layer is about change *in* hazard zones, "
                         "so out-of-zone polygons are dropped to keep tiles small.")
    args = ap.parse_args()

    change_path = Path(args.change)
    if not change_path.is_absolute():
        change_path = C.ROOT / change_path
    if not change_path.exists():
        die(f"Change polygons not found: {change_path} — run 'make change' first.")

    for spec in C.FLOOD_LAYERS.values():
        if not spec["out"].exists():
            die(f"Missing {spec['out']} — run 'make flood' first.")

    # ---- read change polygons, reproject to NZTM --------------------------
    chg = gpd.read_file(change_path)
    if chg.empty:
        die(f"No change polygons in {change_path} — nothing to join.")
    chg = chg.to_crs(C.CRS_NZTM).reset_index(drop=True)
    chg["cid"] = chg.index
    # Area in NZTM (chg was reprojected to C.CRS_NZTM above), used for
    # overlap_frac after the merge. Computed here in pandas so it lives on the
    # frame the DuckDB results merge back onto.
    chg["change_area"] = chg.geometry.area
    # alphaearth_change.py attaches change_mean; tolerate its absence.
    if "change_mean" not in chg.columns:
        chg["change_mean"] = None

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")

    con.register(
        "chg_raw",
        chg.assign(wkb=chg.geometry.to_wkb())[["cid", "change_mean", "wkb"]],
    )
    con.execute("""
        CREATE TEMP TABLE change AS
        SELECT cid,
               change_mean,
               ST_MakeValid(ST_GeomFromWKB(wkb))            AS geom,
               ST_Area(ST_MakeValid(ST_GeomFromWKB(wkb)))   AS change_area
        FROM chg_raw
    """)
    con.execute("CREATE INDEX c_idx ON change USING RTREE (geom)")

    # ---- load flood layers exactly as flood_intersect.py does -------------
    def load_layer(name: str, path, buffer_m: float = 0.0):
        g = gpd.read_file(path)
        if g.empty:
            log(f"  {name}: empty layer")
            con.execute(f"CREATE TEMP TABLE {name} (geom GEOMETRY)")
            return
        g = g.to_crs(C.CRS_NZTM)
        if buffer_m > 0:
            g["geometry"] = g.geometry.buffer(buffer_m)
        con.register(f"{name}_raw", g.assign(wkb=g.geometry.to_wkb())[["wkb"]])
        # ST_MakeValid repairs self-intersecting / bowtie rings before any
        # ST_Intersection runs. Buffering the overland-flow LINE layer in
        # particular can emit slightly invalid polygons, which makes GEOS throw
        # "side location conflict" during exact-overlap computation. Cleaning on
        # load fixes it once for every downstream operation.
        con.execute(f"""
            CREATE TEMP TABLE {name} AS
            SELECT ST_MakeValid(ST_GeomFromWKB(wkb)) AS geom FROM {name}_raw
        """)
        con.execute(f"CREATE INDEX {name}_idx ON {name} USING RTREE (geom)")
        log(f"  {name}: {len(g):,} features loaded")

    log("Loading hazard layers into DuckDB...")
    load_layer("flood_plain", C.FLOOD_LAYERS["flood_plains"]["out"])
    load_layer("flood_prone", C.FLOOD_LAYERS["flood_prone"]["out"])
    load_layer("overland_flow", C.FLOOD_LAYERS["overland_flow"]["out"],
               buffer_m=C.OVERLAND_FLOW_BUFFER_M)

    # ---- intersect: per zone, area of each change polygon inside it --------
    # Aggregating area (not just a boolean) lets us compute overlap_frac and
    # break severity ties by how much of the polygon sits in each zone.
    log("Spatial joins...")
    inter = con.execute("""
        WITH hits AS (
            SELECT c.cid, 'flood_plain' AS flood_class, 1 AS rank,
                   SUM(ST_Area(ST_Intersection(c.geom, fp.geom))) AS ia
            FROM change c JOIN flood_plain fp ON ST_Intersects(c.geom, fp.geom)
            GROUP BY c.cid
            UNION ALL
            SELECT c.cid, 'flood_prone', 2,
                   SUM(ST_Area(ST_Intersection(c.geom, fr.geom)))
            FROM change c JOIN flood_prone fr ON ST_Intersects(c.geom, fr.geom)
            GROUP BY c.cid
            UNION ALL
            SELECT c.cid, 'overland_flow', 3,
                   SUM(ST_Area(ST_Intersection(c.geom, of.geom)))
            FROM change c JOIN overland_flow of ON ST_Intersects(c.geom, of.geom)
            GROUP BY c.cid
        ),
        ranked AS (
            SELECT *, row_number() OVER (
                       PARTITION BY cid ORDER BY rank ASC, ia DESC) AS rn
            FROM hits
        )
        SELECT cid, flood_class, ia AS intersect_area
        FROM ranked WHERE rn = 1
    """).df()

    # ---- assemble back onto the change frame (in NZTM) --------------------
    out = chg.merge(inter, on="cid", how="left")
    out["flood_class"] = out["flood_class"].fillna("none")
    out["intersect_area"] = out["intersect_area"].fillna(0.0)
    out["overlap_frac"] = (out["intersect_area"] / out["change_area"]).where(
        out["change_area"] > 0, 0.0)

    # Drop incidental edge clips: in-zone polygons must clear the threshold.
    in_zone = out["flood_class"] != "none"
    clears = out["overlap_frac"] >= args.min_overlap_frac
    out = out[(~in_zone) | clears].copy()

    n = len(out)
    log("Change-in-flood summary:")
    for k, v in out["flood_class"].value_counts().items():
        log(f"  {k:>14}: {v:,} ({100 * v / max(n, 1):.1f}%)")
    n_in = int((out["flood_class"] != "none").sum())
    log(f"  in-zone total: {n_in:,}")

    # ---- write GeoParquet (full set, WGS84, for analysis) -----------------
    out = out.to_crs(C.CRS_WGS84)
    out.to_parquet(CHANGE_FLOOD_PARQUET)
    log(f"Saved -> {CHANGE_FLOOD_PARQUET}")

    # ---- write GeoJSONL for tiling ---------------------------------------
    # By default only in-zone polygons go to the tiles — the map layer is
    # "change inside flood hazard". layer_key mirrors flood_layers.geojsonl so
    # the frontend can style by class with the same expressions.
    tiling = out if args.keep_none else out[out["flood_class"] != "none"].copy()
    cols = ["change_mean", "flood_class", "overlap_frac"]
    cols = [c for c in cols if c in tiling.columns]
    with open(CHANGE_FLOOD_GEOJSONL, "w") as f:
        for _, row in tiling.iterrows():
            props = {c: (row[c].item() if hasattr(row[c], "item") else row[c]) for c in cols}
            if props.get("change_mean") is not None:
                props["change_mean"] = round(float(props["change_mean"]), 4)
            if props.get("overlap_frac") is not None:
                props["overlap_frac"] = round(float(props["overlap_frac"]), 3)
            # layer_key lets make_tiles/app.js treat this like the flood export.
            props["layer_key"] = row["flood_class"]
            f.write(json.dumps({
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": props,
            }) + "\n")
    log(f"Wrote {CHANGE_FLOOD_GEOJSONL.name} ({len(tiling):,} features for tiling)")


if __name__ == "__main__":
    main()