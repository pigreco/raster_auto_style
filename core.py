"""
Logica del plugin "Raster Auto Style", indipendente dall'interfaccia grafica.

Uno stile e' "dinamico" quando il layer ha la custom property
dynamic_minmax=true (salvata nella QML). In quel caso gli stop della rampa
sono interpretati come valori relativi (0 = minimo, 1 = massimo del granulo)
e vengono riscalati sul range reale del raster:

    valore = min + rel * (max - min)
"""
from __future__ import annotations

import json
import math
import os

from osgeo import gdal
from qgis.core import (
    Qgis,
    QgsColorRampShader,
    QgsMessageLog,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor

TAG = "Raster Auto Style"

# QColor.HexArgb in Qt5, QColor.NameFormat.HexArgb in Qt6
_HEX_ARGB = getattr(QColor, "NameFormat", QColor).HexArgb

PROP_FLAG = "dynamic_minmax"
PROP_MODE = "dynamic_minmax_mode"            # "minmax" | "percentile"
PROP_P_LOW = "dynamic_percentile_low"        # es. "2"
PROP_P_HIGH = "dynamic_percentile_high"      # es. "98"
PROP_STOPS = "dynamic_minmax_stops"          # stop relativi (JSON), uso interno
PROP_RANGE = "dynamic_minmax_range"          # ultimo range applicato, informativo

SAMPLE_SIZE = 250_000  # pixel campionati quando le statistiche vanno stimate


class DynamicStyleError(Exception):
    """Errore comprensibile da mostrare all'utente."""


def log(message: str, level=Qgis.Info) -> None:
    QgsMessageLog.logMessage(message, TAG, level)


# --------------------------------------------------------------------------
# Riconoscimento
# --------------------------------------------------------------------------
def is_dynamic(layer) -> bool:
    return (isinstance(layer, QgsRasterLayer)
            and str(layer.customProperty(PROP_FLAG, "")).lower() == "true")


def _pseudocolor(layer: QgsRasterLayer):
    renderer = layer.renderer()
    if not isinstance(renderer, QgsSingleBandPseudoColorRenderer):
        raise DynamicStyleError(
            f"{layer.name()}: lo stile dinamico richiede il renderer "
            "'Singola banda falso colore'")
    shader = renderer.shader()
    function = shader.rasterShaderFunction() if shader else None
    if not isinstance(function, QgsColorRampShader):
        raise DynamicStyleError(f"{layer.name()}: rampa colori non trovata")
    return renderer, shader, function


# --------------------------------------------------------------------------
# Stop relativi
# --------------------------------------------------------------------------
def _relative_from_items(function: QgsColorRampShader):
    """Normalizza gli item sul range della classificazione (0-1 per i template)."""
    items = function.colorRampItemList()
    if not items:
        raise DynamicStyleError("La rampa colori non contiene item")
    lo, hi = function.minimumValue(), function.maximumValue()
    finite = [i.value for i in items if math.isfinite(i.value)]
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        lo, hi = min(finite), max(finite)
    span = (hi - lo) or 1.0
    return [((i.value - lo) / span if math.isfinite(i.value) else i.value, i.color)
            for i in items]


def relative_stops(layer: QgsRasterLayer, function: QgsColorRampShader):
    """
    Stop relativi del layer. Se il layer e' gia' stato riscalato, sono salvati
    in PROP_STOPS; altrimenti si ricavano dagli item del template.
    """
    raw = layer.customProperty(PROP_STOPS)
    if raw:
        try:
            stored = [(float(rel), QColor(color)) for rel, color in json.loads(raw)]
        except (ValueError, TypeError):
            log(f"{layer.name()}: stop salvati non validi, li ricalcolo", Qgis.Warning)
        else:
            # Gli stop memorizzati valgono solo se nel frattempo l'utente non ha
            # cambiato palette o classi da Proprieta' > Simbologia.
            current = [i.color.name(_HEX_ARGB) for i in function.colorRampItemList()]
            if current == [c.name(_HEX_ARGB) for _, c in stored]:
                return stored
            log(f"{layer.name()}: palette modificata, uso i colori attuali")
    return _relative_from_items(function)


def _store_stops(layer: QgsRasterLayer, stops) -> None:
    payload = [[rel, color.name(_HEX_ARGB)] for rel, color in stops]
    layer.setCustomProperty(PROP_STOPS, json.dumps(payload))


# --------------------------------------------------------------------------
# Statistiche
# --------------------------------------------------------------------------
def gdal_path(layer: QgsRasterLayer) -> str | None:
    """Percorso GDAL del layer, solo per il provider gdal."""
    if layer.providerType() != "gdal":
        return None
    return layer.source().split("|")[0]


def _read_stats(path: str, band: int, use_sidecar: bool):
    # opzione limitata al thread corrente: non tocca i thread di rendering di QGIS
    if not use_sidecar:
        gdal.SetThreadLocalConfigOption("GDAL_PAM_ENABLED", "NO")
    try:
        ds = gdal.Open(path, gdal.GA_ReadOnly)
        if ds is None or band > ds.RasterCount:
            return None
        b = ds.GetRasterBand(band)
        mn = b.GetMetadataItem("STATISTICS_MINIMUM")
        mx = b.GetMetadataItem("STATISTICS_MAXIMUM")
        ds = None
    finally:
        if not use_sidecar:
            gdal.SetThreadLocalConfigOption("GDAL_PAM_ENABLED", None)
    if mn is None or mx is None:
        return None
    return float(mn), float(mx)


_STATS_CACHE: dict = {}  # (path, banda, mtime file, mtime sidecar) -> risultato


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def stored_stats(layer: QgsRasterLayer, band: int):
    """
    Statistiche gia' disponibili, in quest'ordine:
    1. tag incorporati nel file (scritti dal produttore, gli stessi di GeoServer);
    2. sidecar .aux.xml (scritto da "Forza statistiche" o da QGIS stesso),
       ignorato se piu' vecchio del file.
    Il sidecar viene letto per secondo perche' QGIS lo scrive anche con
    statistiche stimate, che non devono prevalere su quelle del produttore.
    Il risultato e' in cache finche' file e sidecar non cambiano.
    """
    path = gdal_path(layer)
    if not path:
        return None
    sidecar = path + ".aux.xml"
    key = (path, band, _mtime(path), _mtime(sidecar))
    if key in _STATS_CACHE:
        return _STATS_CACHE[key]

    result = None
    stats = _read_stats(path, band, use_sidecar=False)
    if stats:
        result = (stats[0], stats[1], "metadati del file")
    elif _mtime(sidecar) and _mtime(sidecar) < _mtime(path):
        log(f"{os.path.basename(path)}: sidecar piu' vecchio del file, ignorato",
            Qgis.Warning)
    else:
        stats = _read_stats(path, band, use_sidecar=True)
        if stats:
            result = (stats[0], stats[1], "sidecar .aux.xml")
    if len(_STATS_CACHE) > 512:
        _STATS_CACHE.clear()
    _STATS_CACHE[key] = result
    return result


def _minmax_flags():
    stat = getattr(Qgis, "RasterBandStatistic", None)  # QGIS >= 3.40
    if stat is not None:
        return stat.Min | stat.Max
    return QgsRasterBandStats.Min | QgsRasterBandStats.Max


def granule_range(layer: QgsRasterLayer, band: int):
    """Restituisce (min, max, fonte) secondo la modalita' dello stile."""
    provider = layer.dataProvider()
    mode = str(layer.customProperty(PROP_MODE, "minmax")).lower()

    if mode == "percentile":
        p_low = float(layer.customProperty(PROP_P_LOW, 2))
        p_high = float(layer.customProperty(PROP_P_HIGH, 98))
        lo, hi = provider.cumulativeCut(band, p_low / 100, p_high / 100,
                                        layer.extent(), SAMPLE_SIZE)
        return lo, hi, f"percentili {p_low:g}-{p_high:g} (stima)"

    stats = stored_stats(layer, band)
    if stats:
        return stats

    s = provider.bandStatistics(band, _minmax_flags(), layer.extent(), SAMPLE_SIZE)
    return s.minimumValue, s.maximumValue, "stima su campione"


# --------------------------------------------------------------------------
# Applicazione
# --------------------------------------------------------------------------
def _up_to_date(layer, function, vmin, vmax, source) -> bool:
    """True se rampa e range del layer sono gia' quelli che applicherei."""
    if layer.customProperty(PROP_RANGE) != f"{vmin!r};{vmax!r};{source}":
        return False
    if (function.minimumValue(), function.maximumValue()) != (vmin, vmax):
        return False
    raw = layer.customProperty(PROP_STOPS)
    if not raw:
        return False
    try:
        stored = [color for _, color in json.loads(raw)]
    except (ValueError, TypeError):
        return False
    return stored == [i.color.name(_HEX_ARGB) for i in function.colorRampItemList()]


def apply_dynamic(layer: QgsRasterLayer, force: bool = True):
    """
    Riscala la rampa sul range del layer. Restituisce (min, max, fonte).
    Con force=False non tocca il layer se e' gia' aggiornato (evita di
    marcare il progetto come modificato a ogni apertura).
    """
    renderer, shader, function = _pseudocolor(layer)
    stops = relative_stops(layer, function)
    vmin, vmax, source = granule_range(layer, renderer.band())

    if not (math.isfinite(vmin) and math.isfinite(vmax)):
        raise DynamicStyleError(f"{layer.name()}: statistiche non valide")
    if vmax <= vmin:  # raster costante: evito una rampa degenere
        vmax = vmin + (abs(vmin) * 1e-6 or 1e-6)

    if not force and _up_to_date(layer, function, vmin, vmax, source):
        return vmin, vmax, source

    precision = max(function.labelPrecision(), 0)
    items = []
    for rel, color in stops:
        value = vmin + rel * (vmax - vmin) if math.isfinite(rel) else rel
        label = f"{value:.{precision}f}" if math.isfinite(value) else ""
        items.append(QgsColorRampShader.ColorRampItem(value, color, label))

    function.setColorRampItemList(items)
    function.setMinimumValue(vmin)
    function.setMaximumValue(vmax)
    shader.setMinimumValue(vmin)
    shader.setMaximumValue(vmax)
    renderer.setClassificationMin(vmin)
    renderer.setClassificationMax(vmax)

    _store_stops(layer, stops)
    layer.setCustomProperty(PROP_RANGE, f"{vmin!r};{vmax!r};{source}")
    layer.triggerRepaint()
    layer.emitStyleChanged()

    if source == "stima su campione":
        log(f"{layer.name()}: statistiche stimate, gli estremi potrebbero essere "
            "tagliati; usa 'Forza statistiche' per valori esatti", Qgis.Warning)
    log(f"{layer.name()}: rampa riscalata su {vmin:g} / {vmax:g} ({source})")
    return vmin, vmax, source


# --------------------------------------------------------------------------
# Forza statistiche (sidecar .aux.xml)
# --------------------------------------------------------------------------
def force_stats(layer: QgsRasterLayer, approx: bool = True, feedback=None) -> str:
    """
    Calcola le statistiche di tutte le bande con GDAL. Aprendo il file in sola
    lettura, GDAL le salva nel sidecar <file>.aux.xml senza modificare il TIFF.
    Restituisce il percorso del sidecar.
    """
    path = gdal_path(layer)
    if not path:
        raise DynamicStyleError(f"{layer.name()}: non e' un raster GDAL")
    if path.startswith("/vsi"):
        raise DynamicStyleError(
            f"{layer.name()}: file remoto, impossibile scrivere il sidecar")

    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise DynamicStyleError(f"Impossibile aprire {path}")
    total = ds.RasterCount
    for i in range(1, total + 1):
        if feedback is not None and feedback.isCanceled():
            ds = None
            raise DynamicStyleError("Calcolo statistiche annullato")
        ds.GetRasterBand(i).ComputeStatistics(approx)
        if feedback is not None:
            feedback.setProgress(100 * i / total)
    ds = None  # la chiusura scrive il .aux.xml
    _STATS_CACHE.clear()

    sidecar = path + ".aux.xml"
    if not os.path.exists(sidecar):
        raise DynamicStyleError(
            f"Statistiche calcolate ma sidecar non scritto (cartella in sola lettura?): {sidecar}")
    log(f"{layer.name()}: statistiche salvate in {sidecar}")
    return sidecar


# --------------------------------------------------------------------------
# Esporta template
# --------------------------------------------------------------------------
def export_template(layer: QgsRasterLayer, out_path: str,
                    mode: str = "minmax", p_low: float = 2, p_high: float = 98) -> int:
    """
    Salva lo stile del layer come template dinamico: item relativi 0-1,
    classificazione 0-1 e custom properties. Il layer originale non cambia.
    Restituisce il numero di item.
    """
    _, _, function = _pseudocolor(layer)
    stops = relative_stops(layer, function)

    clone = layer.clone()
    _, c_shader, c_function = _pseudocolor(clone)
    c_renderer = clone.renderer()
    c_function.setColorRampItemList([
        QgsColorRampShader.ColorRampItem(rel, color, f"{rel:g}" if math.isfinite(rel) else "")
        for rel, color in stops])
    for setter_min, setter_max in ((c_function.setMinimumValue, c_function.setMaximumValue),
                                   (c_shader.setMinimumValue, c_shader.setMaximumValue),
                                   (c_renderer.setClassificationMin, c_renderer.setClassificationMax)):
        setter_min(0.0)
        setter_max(1.0)

    clone.setCustomProperty(PROP_FLAG, "true")
    clone.setCustomProperty(PROP_MODE, mode)
    clone.setCustomProperty(PROP_P_LOW, str(p_low))
    clone.setCustomProperty(PROP_P_HIGH, str(p_high))
    clone.removeCustomProperty(PROP_STOPS)
    clone.removeCustomProperty(PROP_RANGE)

    message, ok = clone.saveNamedStyle(out_path)
    if not ok:
        raise DynamicStyleError(f"Salvataggio non riuscito: {message}")
    log(f"Template dinamico salvato in {out_path} ({len(stops)} item)")
    return len(stops)


# --------------------------------------------------------------------------
# Import della ColorMap da un SLD (GeoServer)
# --------------------------------------------------------------------------
_SLD_TYPES = {
    "ramp": QgsColorRampShader.Interpolated,
    "intervals": QgsColorRampShader.Discrete,
    "values": QgsColorRampShader.Exact,
}


def read_sld_colormap(sld_path: str):
    """Legge la prima ColorMap dell'SLD: (tipo, [(quantity, QColor), ...])."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(sld_path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise DynamicStyleError(f"SLD non leggibile: {exc}") from exc
    colormap = next((el for el in root.iter() if el.tag.split("}")[-1] == "ColorMap"), None)
    if colormap is None:
        raise DynamicStyleError("Nessuna ColorMap trovata nell'SLD")

    entries = []
    for el in colormap:
        if el.tag.split("}")[-1] != "ColorMapEntry":
            continue
        color = QColor(el.get("color", "#000000"))
        if not color.isValid():
            raise DynamicStyleError(f"Colore non valido nell'SLD: {el.get('color')!r}")
        try:
            color.setAlphaF(float(el.get("opacity", 1)))
            quantity = float(el.get("quantity"))
        except (TypeError, ValueError) as exc:
            raise DynamicStyleError(
                f"ColorMapEntry non valida (quantity/opacity): {el.attrib}") from exc
        entries.append((quantity, color))
    if len(entries) < 2:
        raise DynamicStyleError("La ColorMap deve contenere almeno 2 voci")

    entries.sort(key=lambda e: e[0])
    return colormap.get("type", "ramp").lower(), entries


def _interpolate(stops, rel: float) -> QColor:
    for (r0, c0), (r1, c1) in zip(stops, stops[1:]):
        if r0 <= rel <= r1:
            f = 0 if r1 == r0 else (rel - r0) / (r1 - r0)
            return QColor.fromRgbF(*(a + (b - a) * f for a, b in zip(c0.getRgbF(), c1.getRgbF())))
    return QColor(stops[-1][1])


def apply_sld_colormap(layer: QgsRasterLayer, sld_path: str,
                       n_classes: int | None = None, dynamic: bool = True) -> int:
    """
    Applica al layer la ColorMap di un SLD come renderer pseudocolore.
    n_classes ricampiona la rampa su N stop equidistanti (solo tipo "ramp").
    Con dynamic=True lo stile diventa dinamico e viene riscalato sul layer.
    Restituisce il numero di item.
    """
    from qgis.core import QgsRasterShader

    kind, entries = read_sld_colormap(sld_path)
    lo, hi = entries[0][0], entries[-1][0]
    span = (hi - lo) or 1.0
    stops = [((q - lo) / span, c) for q, c in entries]

    if n_classes and n_classes >= 2 and kind == "ramp":
        stops = [(i / (n_classes - 1), _interpolate(stops, i / (n_classes - 1)))
                 for i in range(n_classes)]

    function = QgsColorRampShader(lo, hi)
    function.setColorRampType(_SLD_TYPES.get(kind, QgsColorRampShader.Interpolated))
    function.setClassificationMode(QgsColorRampShader.EqualInterval)
    function.setColorRampItemList([
        QgsColorRampShader.ColorRampItem(lo + r * span, c, f"{lo + r * span:.4f}")
        for r, c in stops])

    shader = QgsRasterShader(lo, hi)
    shader.setRasterShaderFunction(function)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    renderer.setClassificationMin(lo)
    renderer.setClassificationMax(hi)
    previous = layer.renderer().clone() if layer.renderer() else None
    layer.setRenderer(renderer)

    layer.removeCustomProperty(PROP_STOPS)
    layer.removeCustomProperty(PROP_RANGE)
    if dynamic:
        layer.setCustomProperty(PROP_FLAG, "true")
        layer.setCustomProperty(PROP_MODE, "minmax")
        try:
            apply_dynamic(layer)
        except DynamicStyleError:
            # non lascio il layer a meta': ripristino il renderer precedente
            if previous is not None:
                layer.setRenderer(previous)
            layer.removeCustomProperty(PROP_FLAG)
            layer.triggerRepaint()
            raise
    else:
        layer.triggerRepaint()
        layer.emitStyleChanged()

    log(f"{layer.name()}: ColorMap SLD applicata ({len(stops)} item, tipo {kind})")
    return len(stops)
