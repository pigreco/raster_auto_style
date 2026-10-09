# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

QGIS plugin (QGIS ≥ 3.22, `metadata.txt`) that rescales a "Singola banda falso colore" (single-band pseudocolor) style to the min/max of each raster, using one QML with relative 0–1 stops. UI strings, comments and docs are in Italian; keep that convention. See [README.md](README.md) for user-facing behavior.

There is no build system, test suite or linter config. The repo root *is* the plugin directory (`__init__.py` → `classFactory`). To try it, symlink/copy the folder into the QGIS plugins dir (as `raster_auto_style`) or zip it, and reload with Plugin Reloader. For headless checks of `core.py` use the `qgis-headless` skill (needs `osgeo.gdal` and `qgis.core`; nothing runs outside QGIS Python).

## Architecture

Two modules with a strict split:

- [core.py](core.py) — all logic, GUI-independent (only `qgis.core`, `QColor`, `gdal`). Raises `DynamicStyleError` for user-presentable errors.
- [gui.py](gui.py) — `RasterAutoStylePlugin`: actions/menu/toolbar, dialogs, and the automatic-rescale signal wiring. It catches `DynamicStyleError` and shows it in the message bar.

Key mechanics in core:

- A layer is "dynamic" if the custom property `dynamic_minmax=true` is set (persisted in the QML). Related `PROP_*` constants define mode (`minmax`/`percentile`), percentile bounds, and internal state.
- `PROP_STOPS` stores the *relative* stops as JSON on the layer; `apply_dynamic` reads them (`relative_stops`) and writes absolute values into the renderer/shader/color-ramp function (`value = min + rel*(max-min)`). On the first application stops are derived from the QML items, so re-applying must not re-derive from already-scaled items — hence `gui._on_style_loaded` removes `PROP_STOPS` when a fresh QML is loaded.
- Statistics source priority in `granule_range`: embedded `STATISTICS_MINIMUM/MAXIMUM` tags in the file (matches GeoServer) → `.aux.xml` sidecar → sampled estimate (`SAMPLE_SIZE`). Embedded tags deliberately win over the sidecar because QGIS itself writes `.aux.xml`. Percentile mode always estimates via `cumulativeCut`.
- `force_stats` writes exact stats to the `.aux.xml` sidecar, never into the TIFF.
- SLD import (`read_sld_colormap`/`apply_sld_colormap`) exists because QGIS can't import raster SLD; `export_template` is the inverse (layer style → dynamic 0–1 QML).
- `_minmax_flags` handles the QGIS 3.40 enum move (`Qgis.RasterBandStatistic`); keep such version shims when touching statistic flags. There is also a `qgis4-port` skill for Qt6/QGIS 4 work.

GUI wiring: `layersAdded` → `_watch` connects each raster's `styleLoaded` signal; `_busy` guards against re-entrancy while applying; the auto behavior is toggled by the first menu action and stored in `QgsSettings`. `unload()` must disconnect these slots.

`template_esempio.qml` is a sample 10-class viridis dynamic template (a good reference for the expected QML shape).

## Notes

- `metadata.txt` author/email are still placeholders ("Da compilare"); `experimental=True`.
- Per the README, only tested headless on QGIS 3.34; GUI behavior is unverified.
