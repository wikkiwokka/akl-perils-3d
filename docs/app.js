/* AKL Perils 3D — shared map application.
 * Used by index.html (PMTiles) and demo.html (inline synthetic GeoJSON).
 */
const protocol =  new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);


window.AKL = (() => {
  const COLORS = {
    sand: "#d9cbaa",
    ochre: "#c98a3d",
    scoria: "#a63d2a",
    plain: "#1d6fb0",
    prone: "#3fa7a0",
    flow: "#7c5fbe",
    none: "#c9bfae",
    // Flood-severity ramp (sequential blue: darker = more severe). Used to
    // colour building footprints by exposure so the map reads as a hazard
    // gradient rather than four unrelated categories.
    sev_plain: "#08306b",  // in flood plain (1% AEP) — most severe
    sev_prone: "#2b7bba",  // in flood prone area
    sev_flow: "#9ecae1",   // near overland flow path
    sev_none: "#cdc6b8",   // no flagged exposure — neutral grey, recedes
    // AlphaEarth "change inside a flood zone" polygons. A warm outline that
    // sits apart from the cool flood ramp so it reads as an alert overlay.
    change_line: "#e85d2f",
    change_fill: "#f08a5d",
  };

  // Canopy cover ramp (sequential green: paler = sparse, deeper = dense cover).
  // Keyed on canopy_pct so denser cells read darker; height comes separately
  // from canopy_height_m so the extrusion shows actual vegetation height.
  const CANOPY_COLOR = [
    "interpolate", ["linear"], ["coalesce", ["get", "canopy_pct"], 0],
    10, "#c6e0a8",
    40, "#7cb342",
    70, "#386c1f",
    100, "#1b3d0c",
  ];

  const HEIGHT_COLOR = [
    "interpolate", ["linear"], ["coalesce", ["get", "height_m"], 3],
    3, COLORS.sand,
    12, COLORS.ochre,
    30, COLORS.scoria,
    70, "#5c1f14",
  ];

  const RISK_COLOR = [
    "match", ["get", "risk"],
    "flood_plain", COLORS.sev_plain,
    "flood_prone", COLORS.sev_prone,
    "overland_flow", COLORS.sev_flow,
    COLORS.sev_none,
  ];

  const CENTER = [174.78, -36.885];

  // LINZ Basemaps aerial imagery (XYZ, WebMercatorQuad). Public CC-BY service;
  // the key is exposed in client JS by design for this free basemap. Swap this
  // for a LINZ "developer" key (free, request from LINZ) for public-app use.
  // Get keys at https://basemaps.linz.govt.nz/
  const LINZ_API_KEY = "c01kv0e1bxwsczjntmek31bdv6t";
  const LINZ_AERIAL_URL =
    "https://basemaps.linz.govt.nz/v1/tiles/aerial/WebMercatorQuad/{z}/{x}/{y}.webp?api=" +
    LINZ_API_KEY;

  let map;

  // --- LINZ aerial imagery swap state -------------------------------------
  // Set of layer ids that belong to the Liberty base style. Captured once,
  // right after the style first loads, so the aerial swap can hide exactly
  // those (and nothing of ours). hideBasemapBuildings() already permanently
  // hides the basemap's own 3D extrusions; we must NOT resurrect those when
  // swapping back, so the swap toggles visibility per-id and remembers it.
  let baseStyleLayerIds = null;
  let aerialOn = false;

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

    window.__map = map;

    wireChrome();

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");

    map.on("load", () => {
      if (opts.mode === "pmtiles") {
        map.addSource("akl", { type: "vector", url: "pmtiles://" + new URL(opts.url, window.location.href).href });
        hideBasemapBuildings();
        captureBaseStyleLayers();
        addSatelliteLayer();
        addFloodLayers({ source: "akl", sourceLayer: "flood" });
        addChangeLayer({ source: "akl", sourceLayer: "change" });
        addCanopyLayer({ source: "akl", sourceLayer: "canopy" });
        addBuildingLayer({ source: "akl", sourceLayer: "buildings" });
      } else if (opts.mode === "geojson") {
        map.addSource("flood-geo", { type: "geojson", data: opts.flood });
        map.addSource("bld-geo", { type: "geojson", data: opts.buildings });
        addFloodLayers({ source: "flood-geo" });
        addBuildingLayer({ source: "bld-geo" });
      }
      if (opts.mode === "pmtiles" || opts.mode === "geojson") {
        wireUi();
        wireReadout();
      }
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

  // AlphaEarth change polygons that fall inside a flood hazard zone. Rendered
  // as a hatched-looking warm overlay above the flood fills but below the 3D
  // buildings, hidden by default (it's a focused analytical layer, not part of
  // the default read). Opacity is graduated by change_mean so stronger change
  // reads darker. Safe to add even when the 'change' source-layer is absent
  // (no 'make change' run yet) — it simply renders nothing.
  function addChangeLayer({ source, sourceLayer }) {
    const sl = sourceLayer ? { "source-layer": sourceLayer } : {};
    map.addLayer({
      id: "change-fill",
      type: "fill",
      source, ...sl,
      layout: { visibility: "none" },
      paint: {
        "fill-color": COLORS.change_fill,
        "fill-opacity": [
          "interpolate", ["linear"],
          ["coalesce", ["get", "change_mean"], 0.3],
          0.3, 0.25,
          0.6, 0.55,
        ],
      },
    });
    map.addLayer({
      id: "change-outline",
      type: "line",
      source, ...sl,
      layout: { visibility: "none" },
      paint: { "line-color": COLORS.change_line, "line-width": 1.2, "line-opacity": 0.9 },
    });
  }

  // Gridded canopy from LiDAR. A 3D green surface extruded by canopy_height_m
  // and coloured by canopy_pct (cover density), sitting among the buildings.
  // Hidden by default. Safe to add when the 'canopy' source-layer is absent
  // (no 'make canopy' yet) — it just renders nothing. Rendered as extrusions
  // like the buildings so the two read as one 3D scene.
  function addCanopyLayer({ source, sourceLayer }) {
    const sl = sourceLayer ? { "source-layer": sourceLayer } : {};
    map.addLayer({
      id: "canopy",
      type: "fill-extrusion",
      source, ...sl,
      layout: { visibility: "none" },
      paint: {
        "fill-extrusion-color": CANOPY_COLOR,
        "fill-extrusion-height": ["coalesce", ["get", "canopy_height_m"], 0],
        "fill-extrusion-base": 0,
        "fill-extrusion-opacity": 0.85,
      },
    });
  }

  function hideBasemapBuildings() {
    // OpenFreeMap "Liberty" renders its own OSM-derived 3D building
    // extrusions (layer "building-3d" today). Hide every fill-extrusion
    // that isn't ours so they don't clash with our LiDAR buildings.
    // Matching by layer type (not a hardcoded id) survives upstream
    // renames. The basemap style loads over the network, so its
    // extrusion layers may not exist yet when this first runs — that
    // race is why it worked locally but not on GitHub Pages. So we retry
    // on styledata until at least one layer is hidden, then stop.
    const hide = () => {
      let hidden = false;
      for (const layer of map.getStyle().layers) {
        if (layer.type === "fill-extrusion" && layer.id !== "bld") {
          map.setLayoutProperty(layer.id, "visibility", "none");
          hidden = true;
        }
      }
      if (hidden) map.off("styledata", hide);
    };
    hide();
    map.on("styledata", hide);
  }

  // Record the ids of all layers that came from the Liberty base style,
  // BEFORE we add any of our own (satellite/flood/buildings). These are the
  // only layers the satellite swap is allowed to toggle.
  function captureBaseStyleLayers() {
    baseStyleLayerIds = map.getStyle().layers.map((l) => l.id);
  }

  // Add the LINZ aerial imagery as a hidden raster layer beneath the buildings.
  function addSatelliteLayer() {
    map.addSource("aerial", {
      type: "raster",
      tiles: [LINZ_AERIAL_URL],
      tileSize: 256,
      attribution:
        '© <a href="https://www.linz.govt.nz/linz-copyright">LINZ CC BY 4.0</a> © Imagery Basemap contributors',
    });
    map.addLayer({
      id: "aerial-raster",
      type: "raster",
      source: "aerial",
      layout: { visibility: "none" },
      paint: { "raster-opacity": 1 },
    });
  }

  // Show/hide every Liberty base-style layer. Skips any layer hideBasemap-
  // Buildings() already turned off, so swapping back doesn't resurrect the
  // basemap's clashing 3D buildings.
  function setBaseStyleVisible(visible) {
    if (!baseStyleLayerIds) return;
    const vis = visible ? "visible" : "none";
    for (const id of baseStyleLayerIds) {
      if (!map.getLayer(id)) continue;
      // Don't re-show the basemap extrusions we permanently hid.
      const layer = map.getStyle().layers.find((l) => l.id === id);
      if (visible && layer && layer.type === "fill-extrusion" && id !== "bld") {
        continue;
      }
      map.setLayoutProperty(id, "visibility", vis);
    }
  }

  // The single swap toggle: Liberty <-> LINZ aerial imagery. Our buildings +
  // flood stay visible in both modes.
  function toggleSatellite() {
    aerialOn = !aerialOn;
    if (map.getLayer("aerial-raster")) {
      map.setLayoutProperty("aerial-raster", "visibility", aerialOn ? "visible" : "none");
    }
    setBaseStyleVisible(!aerialOn);
    return aerialOn;
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

  // Panel collapse + footer-card dismiss. Independent of the map, so it runs
  // for every mode. No persistence — dismissals last the session only.
  function wireChrome() {
    const collapseBtn = document.getElementById("panel-collapse");
    const panel = document.querySelector(".panel");
    if (collapseBtn && panel) {
      collapseBtn.addEventListener("click", () => {
        const collapsed = panel.classList.toggle("collapsed");
        collapseBtn.textContent = collapsed ? "+" : "−";
        collapseBtn.setAttribute("aria-expanded", String(!collapsed));
      });
    }
    document.querySelectorAll(".card-dismiss").forEach((btn) => {
      btn.addEventListener("click", () => {
        const card = btn.closest(".card");
        if (card) card.classList.add("is-dismissed");
      });
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

    const bldToggle = document.getElementById("toggle-buildings");
    if (bldToggle)
      bldToggle.addEventListener("change", (e) => {
        const vis = e.target.checked ? "visible" : "none";
        if (map.getLayer("bld")) map.setLayoutProperty("bld", "visibility", vis);
      });

    const changeToggle = document.getElementById("toggle-change");
    if (changeToggle)
      changeToggle.addEventListener("change", (e) => {
        const vis = e.target.checked ? "visible" : "none";
        ["change-fill", "change-outline"].forEach((id) => {
          if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis);
        });
      });

    const canopyToggle = document.getElementById("toggle-canopy");
    if (canopyToggle)
      canopyToggle.addEventListener("change", (e) => {
        const vis = e.target.checked ? "visible" : "none";
        if (map.getLayer("canopy")) map.setLayoutProperty("canopy", "visibility", vis);
      });

    const tilt = document.getElementById("tilt");
    if (tilt)
      tilt.addEventListener("click", () => {
        const flat = map.getPitch() > 5;
        map.easeTo({ pitch: flat ? 0 : 55, bearing: flat ? 0 : -15, duration: 600 });
      });

    const sat = document.getElementById("satellite");
    if (sat)
      sat.addEventListener("click", () => {
        const on = toggleSatellite();
        sat.classList.toggle("active", on);
        sat.textContent = on ? "Map basemap" : "Aerial imagery";
        sat.setAttribute("aria-pressed", String(on));
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
