# Quickstart Guide (uv)

wahooMapsCreator uses [`uv`](https://docs.astral.sh/uv/) as its Python
environment manager. `uv` replaces conda for this project — it is faster,
produces a reproducible `uv.lock`, and does not require a separate Anaconda
install.

#### Table of contents
- [1. Install system prerequisites](#1-install-system-prerequisites)
  - [Linux](#linux)
  - [macOS](#macos)
  - [Windows](#windows)
- [2. Install `uv`](#2-install-uv)
- [3. Install wahooMapsCreator](#3-install-wahoomapscreator)
- [4. Contour lines (optional)](#4-contour-lines-optional)
- [5. Run wahooMapsCreator](#5-run-wahoomapscreator)

## 1. Install system prerequisites

wahooMapsCreator shells out to a handful of native tools that are not Python
packages. Install them through your OS package manager.

### Linux

```
sudo apt update
sudo apt install -y osmium-tool osmosis default-jre gdal-bin
```

`gdal-bin` provides `ogr2ogr` and pulls in the `libgdal` runtime the Python
`gdal==3.6.*` binding links against. If your distro ships a different GDAL
major version, install the matching Python binding instead of 3.6.

### macOS

```
brew install osmium-tool osmosis openjdk gdal
```

### Windows

On Windows nothing has to be installed by hand: `wahooMapsCreator` will
auto-download `osmosis`, `osmfilter` and `7za` on first run. You still need a
Java runtime (see [Oracle JRE](https://www.oracle.com/java/technologies/downloads/)
or any OpenJDK distribution) on `PATH`.

## 2. Install `uv`

```
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

## 3. Install wahooMapsCreator

Clone the repository and let `uv` create the virtual env and install the
pinned dependencies:

```
git clone https://github.com/treee111/wahooMapsCreator.git
cd wahooMapsCreator
uv sync
```

`uv sync` reads `pyproject.toml` + `uv.lock` and creates `.venv/` with the
exact dependency versions. Re-run `uv sync` after pulling changes.

If you only want to install the published package into an existing env:

```
uv pip install wahoomc
```

## 4. Contour lines (optional)

Contour lines (elevation) require the extra Python package `phyghtmap` and a
free USGS EarthExplorer account.

```
uv pip install phyghtmap
```

Verify:

```
uv run phyghtmap --help
```

Register at https://earthexplorer.usgs.gov/ and store the credentials as
described in [USAGE.md](USAGE.md).

## 5. Run wahooMapsCreator

```
uv run python -m wahoomc.init                       # first-run setup
uv run python -m wahoomc -co malta                  # build Malta
uv run python -m wahoomc -co malta -j 8             # parallel build (8 workers)
uv run python -m wahoomc -co malta -ci              # also delete intermediates
```

Useful new flags:

- `-j / --jobs N` — number of parallel workers for per-tile processing
  (default `cpu_count - 1`; set `1` for serial).
- `-ci / --cleanup_intermediate` — delete `split-*.osm.pbf` files after
  merge to save disk.
- `-fd / --forcedownload` — force a full re-fetch (bypasses the HTTP
  conditional GETs; normally unnecessary, cached files are revalidated
  automatically).

See [USAGE.md](USAGE.md) for the full list of options.
