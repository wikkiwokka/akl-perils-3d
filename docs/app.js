/* AKL Perils 3D — shared map application.
 * Used by index.html (PMTiles) and demo.html (inline synthetic GeoJSON).
 */

window.AKL = (() => {
  const COLORS = {
    sand: "#d9cbaa",
    ochre: "#c98a3d",
    scoria: "#a63d2a",
    plain: "#1d6fb0",
    prone: "#3fa7a0",
    flow: "#7c5fbe",
    none: "#c9bfae",
  };

  const HEIGHT_COLOR = [
    "interpolate", ["linear"], ["coalesce", ["get", "height_m"], 3],
    3, COLORS.sand,
    12, COLORS.ochre,
    30, COLORS.scoria,
    70, "#5c1f14",
  ];

  const RISK_COLOR = [
    "match", ["get", "risk"],
    "flood_plain", COLORS.plain,
    "flood_prone", COLORS.prone,
    "overland_flow", COLORS.flow,
    COLORS.none,
  ];

  const CENTER = [174.78, -36.885];

  let map;

  function boot(opts) {
    map = new maplibregl.Map({
      container: "map",
      style: "https://tiles.openfreemap.org/styles/liberty",
      center: CENTER,
      zoom: 13.6,
      pitch: 55,
      bearing: -15,
      maxPitch: 70,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");

    map.on("load", () => {
      if (opts.mode === "pmtiles") {
        const protocol = new pmtiles.Protocol();
        maplibregl.addProtocol("pmtiles", protocol.tile);
        map.addSource("akl", { type: "vector", url: "pmtiles://" + opts.url });
        addFloodLayers({ source: "akl", sourceLayer: "flood" });
        addBuildingLayer({ source: "akl", sourceLayer: "buildings" });
      } else if (opts.mode === "geojson") {
        map.addSource("flood-geo", { type: "geojson", data: opts.flood });
        map.addSource("bld-geo", { type: "geojson", data: opts.buildings });
        addFloodLayers({ source: "flood-geo" });
        addBuildingLayer({ source: "bld-geo" });
      }
      wireUi();
      wireReadout();
    });
  }

  function addFloodLayers({ source, sourceLayer }) {
    const sl = sourceLayer ? { "source-layer": sourceLayer } : {};
    map.addLayer({
      id: "flood-fill",
      type: "fill",
      source, ...sl,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: {
        "fill-color": [
          "match", ["get", "layer_key"],
          "flood_prone", COLORS.prone,
          COLORS.plain,
        ],
        "fill-opacity": 0.28,
      },
    });
    map.addLayer({
      id: "flood-line",
      type: "line",
      source, ...sl,
      filter: ["==", ["geometry-type"], "LineString"],
      paint: { "line-color": COLORS.flow, "line-width": 1.6, "line-opacity": 0.75 },
    });
  }

  function addBuildingLayer({ source, sourceLayer }) {
    const sl = sourceLayer ? { "source-layer": sourceLayer } : {};
    map.addLayer({
      id: "bld",
      type: "fill-extrusion",
      source, ...sl,
      paint: {
        "fill-extrusion-color": HEIGHT_COLOR,
        "fill-extrusion-height": ["coalesce", ["get", "height_m"], 3],
        "fill-extrusion-base": 0,
        "fill-extrusion-opacity": 0.92,
      },
    });
  }

  function wireUi() {
    document.querySelectorAll('input[name="mode"]').forEach((el) =>
      el.addEventListener("change", (e) => {
        const risk = e.target.value === "risk";
        map.setPaintProperty("bld", "fill-extrusion-color", risk ? RISK_COLOR : HEIGHT_COLOR);
        document.getElementById("legend-height").style.display = risk ? "none" : "";
        document.getElementById("legend-risk").style.display = risk ? "" : "none";
      })
    );

    const floodToggle = document.getElementById("toggle-flood");
    if (floodToggle)
      floodToggle.addEventListener("change", (e) => {
        const vis = e.target.checked ? "visible" : "none";
        ["flood-fill", "flood-line"].forEach((id) => {
          if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis);
        });
      });

    const tilt = document.getElementById("tilt");
    if (tilt)
      tilt.addEventListener("click", () => {
        const flat = map.getPitch() > 5;
        map.easeTo({ pitch: flat ? 0 : 55, bearing: flat ? 0 : -15, duration: 600 });
      });
  }

  function wireReadout() {
    const el = document.getElementById("readout");
    if (!el) return;
    const idle = () => {
      el.innerHTML =
        '<div class="title">Building readout</div><div class="idle">hover a building…</div>';
    };
    const riskLabel = {
      flood_plain: "flood plain",
      flood_prone: "flood prone",
      overland_flow: "overland flow",
      none: "none flagged",
    };

    map.on("mousemove", "bld", (e) => {
      const f = e.features && e.features[0];
      if (!f) return idle();
      const p = f.properties;
      const h = p.height_m != null ? Number(p.height_m).toFixed(1) : "—";
      const st = p.storeys != null ? p.storeys : "—";
      const r = p.risk || "none";
      const src = p.height_source === "default" ? " (no LiDAR — default)" : "";
      el.innerHTML = `
        <div class="title">Building readout</div>
        <div class="kv"><span class="k">height</span><span class="v">${h} m${src}</span></div>
        <div class="kv"><span class="k">storeys</span><span class="v">≈ ${st}</span></div>
        <div class="kv"><span class="k">exposure</span><span class="v risk-${r}">${riskLabel[r] || r}</span></div>
        ${p.lidar_survey ? `<div class="kv"><span class="k">survey</span><span class="v">${p.lidar_survey}</span></div>` : ""}`;
      map.getCanvas().style.cursor = "crosshair";
    });
    map.on("mouseleave", "bld", () => {
      idle();
      map.getCanvas().style.cursor = "";
    });
    idle();
  }

  return { boot };
})();
