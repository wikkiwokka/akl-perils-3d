# AKL Perils 3D — pipeline orchestration
# Run from WSL2/Ubuntu. See README.md for one-time setup.

PY = uv run python

.PHONY: all fetch footprints elevation flood heights intersect tiles clean doctor

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

tiles:
	$(PY) -m pipeline.make_tiles

serve:
	$(PY) -m pipeline.serve

doctor:
	$(PY) -m pipeline.doctor

clean:
	rm -rf data/interim/* data/processed/*
