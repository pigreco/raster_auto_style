def classFactory(iface):  # noqa: N802 (nome richiesto da QGIS)
    from .gui import RasterAutoStylePlugin
    return RasterAutoStylePlugin(iface)
