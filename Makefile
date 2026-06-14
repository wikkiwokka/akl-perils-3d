# AKL Perils 3D — pipeline orchestration
# Run from WSL2/Ubuntu. See README.md for one-time setup.

PY = uv run python

# 'change' is intentionally NOT in .PHONY's default 'all' chain: it needs Earth
# Engine auth and is run on its own (make change) once, then 'make tiles' picks
# up its output automatically.
.PHONY: all fetch footprints elevation flood heights intersect change canopy tiles clean doctor serve

all: fetch heights intersect tiles
	@echo "Done. Open docs/index.html via 'make serve' or push to GitHub Pages."

fetch: footprints elevation flood

footprints:
	$(PY) -m pipeline.fetch_footprints

elevation:
	$(PY) -m pipeline.fetch_elevation

flood:
	$(PY) -m pipeline.fetch_flood

heights:
	$(PY) -m pipeline.derive_heights

intersect:
	$(PY) -m pipeline.flood_intersect

# AlphaEarth change detection + flood tagging. Needs Earth Engine auth
# (see 'make doctor'). Writes data/interim/change.geojson, then tags each
# change polygon with its flood class. After this, re-run 'make tiles' to
# fold the 'change' layer into the PMTiles archive.
change:
	$(PY) -m pipeline.alphaearth_change --baseline 2018 --recent 2024 \
		--threshold 0.30 --out data/interim/change.geojson
	$(PY) -m pipeline.alphaearth_flood_join --change data/interim/change.geojson
	@echo "Change layer ready. Run 'make tiles' to include it on the map."

# Gridded canopy from LiDAR (reuses the elevation tiles already fetched). No
# external auth needed. Writes data/processed/canopy.geojsonl, then re-run
# 'make tiles' to fold the 'canopy' layer into the PMTiles archive.
canopy:
	$(PY) -m pipeline.derive_canopy
	@echo "Canopy layer ready. Run 'make tiles' to include it on the map."

tiles:
	$(PY) -m pipeline.make_tiles

serve:
	$(PY) -m pipeline.serve

doctor:
	$(PY) -m pipeline.doctor

clean:
	rm -rf data/interim/* data/processed/*
