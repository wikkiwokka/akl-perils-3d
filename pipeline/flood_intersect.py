"""Assign flood-hazard flags to each building via DuckDB spatial joins.

Flags (all derived from Auckland Council's published hazard layers):
  flood_plain   — footprint intersects the 1% AEP flood plain
  flood_prone   — footprint intersects a flood prone area (ponding depression)
  overland_flow — footprint within OVERLAND_FLOW_BUFFER_M of an overland flow path

risk = highest-priority flag (flood_plain > flood_prone > overland_flow > none)

Outputs:
  * GeoParquet (analysis)
  * buildings GeoJSONL + merged flood-layers GeoJSONL (tippecanoe input)
"""

import json

import duckdb
import geopandas as gpd

from pipeline import config as C
from pipeline.util import die, log


def main() -> None:
    if not C.HEIGHTS_OUT.exists():
        die("No heights file — run 'make heights' first.")
    for spec in C.FLOOD_LAYERS.values():
        if not spec["out"].exists():
            die(f"Missing {spec['out']} — run 'make flood' first.")

    # Work in NZTM for metre-true buffering/joins
    bld = gpd.read_parquet(C.HEIGHTS_OUT).to_crs(C.CRS_NZTM)
    bld = bld.reset_index(drop=True)
    bld["bid"] = bld.index

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")

    con.register("bld_raw", bld.assign(wkb=bld.geometry.to_wkb()).drop(columns="geometry"))
    con.execute("""
        CREATE TEMP TABLE buildings AS
        SELECT bid, ST_GeomFromWKB(wkb) AS geom FROM bld_raw
    """)
    con.execute("CREATE INDEX b_idx ON buildings USING RTREE (geom)")

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
        con.execute(f"""
            CREATE TEMP TABLE {name} AS
            SELECT ST_GeomFromWKB(wkb) AS geom FROM {name}_raw
        """)
        con.execute(f"CREATE INDEX {name}_idx ON {name} USING RTREE (geom)")
        log(f"  {name}: {len(g):,} features loaded")

    log("Loading hazard layers into DuckDB...")
    load_layer("flood_plain", C.FLOOD_LAYERS["flood_plains"]["out"])
    load_layer("flood_prone", C.FLOOD_LAYERS["flood_prone"]["out"])
    load_layer("overland_flow", C.FLOOD_LAYERS["overland_flow"]["out"],
               buffer_m=C.OVERLAND_FLOW_BUFFER_M)

    log("Spatial joins...")
    flags = con.execute("""
        SELECT b.bid,
               BOOL_OR(fp.geom IS NOT NULL)  AS flood_plain,
               BOOL_OR(fr.geom IS NOT NULL)  AS flood_prone,
               BOOL_OR(of.geom IS NOT NULL)  AS overland_flow
        FROM buildings b
        LEFT JOIN flood_plain  fp ON ST_Intersects(b.geom, fp.geom)
        LEFT JOIN flood_prone  fr ON ST_Intersects(b.geom, fr.geom)
        LEFT JOIN overland_flow of ON ST_Intersects(b.geom, of.geom)
        GROUP BY b.bid
    """).df()

    out = bld.merge(flags, on="bid", how="left")
    for c in ("flood_plain", "flood_prone", "overland_flow"):
        out[c] = out[c].fillna(False).astype(bool)

    out["risk"] = "none"
    out.loc[out.overland_flow, "risk"] = "overland_flow"
    out.loc[out.flood_prone, "risk"] = "flood_prone"
    out.loc[out.flood_plain, "risk"] = "flood_plain"

    n = len(out)
    log("Risk summary:")
    for k, v in out["risk"].value_counts().items():
        log(f"  {k:>14}: {v:,} ({100 * v / n:.1f}%)")

    out = out.to_crs(C.CRS_WGS84)
    out.to_parquet(C.BUILDINGS_FINAL)
    log(f"Saved -> {C.BUILDINGS_FINAL}")

    # ---- exports for tippecanoe -------------------------------------------
    log("Writing GeoJSONL for tiling...")
    cols = ["height_m", "storeys", "risk", "flood_plain", "flood_prone",
            "overland_flow", "height_source", "lidar_survey"]
    cols = [c for c in cols if c in out.columns]
    with open(C.BUILDINGS_GEOJSONL, "w") as f:
        for _, row in out.iterrows():
            props = {c: (row[c].item() if hasattr(row[c], "item") else row[c]) for c in cols}
            if props.get("height_m") is not None:
                props["height_m"] = round(float(props["height_m"]), 1)
            if props.get("storeys") is not None:
                props["storeys"] = int(props["storeys"])
            f.write(json.dumps({
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": props,
            }) + "\n")

    with open(C.FLOOD_MERGED_GEOJSONL, "w") as f:
        for key, spec in C.FLOOD_LAYERS.items():
            g = gpd.read_file(spec["out"])
            if g.empty:
                continue
            g = g.to_crs(C.CRS_WGS84)
            for _, row in g.iterrows():
                f.write(json.dumps({
                    "type": "Feature",
                    "geometry": row.geometry.__geo_interface__,
                    "properties": {"layer_key": key},
                }) + "\n")

    log(f"Wrote {C.BUILDINGS_GEOJSONL.name} and {C.FLOOD_MERGED_GEOJSONL.name}")


if __name__ == "__main__":
    main()
