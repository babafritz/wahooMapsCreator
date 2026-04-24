# wahooMapsCreator — codebase guide for Claude

## What this project does
Generates routable map files (`.map.lzma`) for Wahoo ELEMNT cycling computers
from OpenStreetMap data. Takes a country name or tile X/Y coordinate, downloads
the relevant OSM `.pbf` file from Geofabrik, filters tags, splits into 256×256
tiles, merges with land/sea polygons, and compresses with lzma.

## Platform support
**Linux and macOS only.** Windows support was removed. The toolchain assumes
`osmium-tool`, `osmosis`, `lzma`, `zip`, `ogr2ogr`, and Java are on `PATH`.

## Running the tool
```
uv run python -m wahoomc -co malta          # build Malta
uv run python -m wahoomc -xy 134/88         # single tile
uv run python -m wahoomc -co malta -j 4     # 4 parallel workers
uv run python -m wahoomc.init               # copy config files to ~/wahooMapsCreatorData/_config
```

## Running tests and lint
```
python -m unittest                          # unit tests
pylint -j 0 ./wahoomc ./tests              # must score 10.00/10
```

## Key source files
| File | Purpose |
|---|---|
| `wahoomc/main.py` | Entry point — wires up setup, download, and map-building steps |
| `wahoomc/input.py` | CLI argument parsing; `InputData` dataclass |
| `wahoomc/constants.py` | All path constants (`USER_WAHOO_MC`, `USER_DL_DIR`, `USER_OUTPUT_DIR`, …) |
| `wahoomc/constants_functions.py` | `translate_tags_to_keep()` — reads `tags-to-keep.json` and returns the osmium filter list; result is `@lru_cache`d |
| `wahoomc/downloader.py` | Download OSM pbf files, land polygons, geofabrik index, mapwriter plugin |
| `wahoomc/osm_maps_functions.py` | `OsmMaps` class — all tile-building steps: filter, land, sea, elevation, split, merge, create .map, zip |
| `wahoomc/osm_data.py` | `CountryOsmData` / `XYOsmData` — hold tile + border-country state |
| `wahoomc/geofabrik.py` | `CountryGeofabrik` / `XYGeofabrik` — resolve country names and X/Y coords to tile lists |
| `wahoomc/geofabrik_json.py` | Parse Geofabrik index JSON |
| `wahoomc/setup_functions.py` | Check installed tools, manage config file, copy resource files |
| `wahoomc/file_directory_functions.py` | Generic JSON read/write helpers, directory creation |
| `wahoomc/timings.py` | Simple elapsed-time logger |

## Architecture: map-building pipeline
```
InputData (CLI args)
  → CountryOsmData / XYOsmData  (resolve tiles + border countries)
  → Downloader                  (fetch / revalidate .pbf, land polygons, geofabrik.json)
  → OsmMaps
      filter_tags_from_country_osm_pbf_files()  # osmium tags-filter → filtered.o5m.pbf
      generate_land()                            # ogr2ogr + shape2osm.py → land*.osm
      generate_sea()                             # template fill → sea.osm
      generate_elevation()                       # phyghtmap (optional, -con flag)
      split_filtered_country_files_to_tiles()    # osmium extract
      merge_splitted_tiles_with_land_and_sea()   # osmosis merge → merged.osm.pbf
      create_map_files()                         # osmosis --mw → .map, then lzma
      make_and_zip_files()                       # copy + optional zip
```

All per-tile steps run in a `multiprocessing.Pool` (size = `jobs`, default
`cpu_count - 1`).

## User data directory layout
```
~/wahooMapsCreatorData/
  _download/
    maps/                  # downloaded .osm.pbf country files
    land-polygons-split-4326/land_polygons.shp
    geofabrik.json
  _tiles/
    <x>/<y>/               # per-tile intermediates
    <country>/             # per-country filtered .pbf + .config.json
  _config/
    tags-to-keep.json      # override tag filter (user copy wins over package default)
    tag_wahoo_adjusted/    # override tag-wahoo .xml files
  <country>/               # final .map.lzma output tiles
```

## Configuration files (overridable by user)
- `wahoomc/resources/tags-to-keep.json` — OSM tags kept during the osmium
  filter step. User copy at `~/wahooMapsCreatorData/_config/tags-to-keep.json`
  takes priority.
- `wahoomc/resources/tag_wahoo_adjusted/` — XML tag configs passed to the
  mapsforge mapwriter plugin via `-tag`. User copies take priority.

## Dependencies
Managed by `uv` / `pyproject.toml`. Key runtime deps: `requests`, `shapely`,
`geojson`, `gdal`. Dev extras: `pylint`, `autopep8`, `build`, `twine`.

## Conventions to follow
- No Windows-specific code. No `platform.system()` checks. No `os.name` checks.
- External tools are called via `subprocess` list form through
  `run_subprocess_and_log_output()` — never shell strings.
- `sys.exit(1)` (not `sys.exit()`) on all error paths.
- `translate_tags_to_keep()` returns a list suitable for `cmd.extend()` —
  do not join or reformat it.
- Per-tile worker functions must be module-level (not methods) to be picklable
  for `multiprocessing.Pool`.
