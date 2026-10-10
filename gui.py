"""Interfaccia del plugin "Raster Auto Style": menu Raster, azioni e aggancio automatico."""
from __future__ import annotations

import os

from qgis.core import (Qgis, QgsApplication, QgsProject, QgsRasterLayer, QgsSettings,
                       QgsTask)
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QInputDialog, QMenu, QToolButton

from . import core

MENU = "&Raster Auto Style"
ICON = os.path.join(os.path.dirname(__file__), "icon.svg")
SETTING_AUTO = "raster_auto_style/auto_apply"
GUIDE_URL = "https://github.com/pigreco/raster_auto_style/blob/main/docs/GUIDA.md"


class RasterAutoStylePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.actions: list[QAction] = []
        self._busy = False  # evita doppie applicazioni durante le nostre operazioni
        self._slots = {}    # layer id -> slot collegato a styleLoaded
        self._tasks = []    # task in corso, tenuti vivi finche' non terminano

    # ------------------------------------------------------------------ GUI
    def initGui(self):
        self.action_auto = self._add_action(
            "Applica automaticamente agli stili dinamici", self._toggle_auto, checkable=True)
        self.action_auto.setChecked(self._auto_enabled())
        self._add_action("Applica template dinamico ai layer selezionati…", self.apply_template)
        self._add_action("Importa SLD di GeoServer come stile dinamico…", self.import_sld)
        self._add_action("Ricalcola stile dinamico", self.refresh_selected)
        self._add_action("Forza statistiche (sidecar .aux.xml)", self.force_stats_selected)
        self._add_action("Esporta stile come template dinamico…", self.export_template)
        self._add_action("Guida…", self.open_guide)  # sempre ultima in self.actions

        # pulsante in barra strumenti con tutte le azioni in un menu a tendina
        self.icon = QIcon(ICON)
        self.menu = QMenu(self.iface.mainWindow())
        self.menu.addActions(self.actions[1:-1])
        self.menu.addSeparator()
        self.menu.addAction(self.actions[0])
        self.menu.addAction(self.actions[-1])
        self.button = QToolButton()
        self.button.setIcon(self.icon)
        self.button.setToolTip("Raster Auto Style")
        self.button.setMenu(self.menu)
        self.button.setPopupMode(QToolButton.InstantPopup)
        self.toolbar = self.iface.addToolBar("Raster Auto Style")
        self.toolbar.setObjectName("RasterAutoStyleToolbar")
        self.toolbar.addWidget(self.button)
        for action in self.actions[1:]:
            action.setIcon(self.icon)

        project = QgsProject.instance()
        project.layersAdded.connect(self._on_layers_added)
        project.layersWillBeRemoved.connect(self._on_layers_removed)
        self._on_layers_added(project.mapLayers().values())

    def unload(self):
        try:
            QgsProject.instance().layersAdded.disconnect(self._on_layers_added)
            QgsProject.instance().layersWillBeRemoved.disconnect(self._on_layers_removed)
        except TypeError:
            pass
        for task in self._tasks:
            task.cancel()
        for layer in QgsProject.instance().mapLayers().values():
            self._unwatch(layer)
        for action in self.actions:
            self.iface.removePluginRasterMenu(MENU, action)
        self.actions.clear()
        if getattr(self, "toolbar", None) is not None:
            self.toolbar.deleteLater()
            self.toolbar = None

    def _add_action(self, text, callback, checkable=False) -> QAction:
        action = QAction(text, self.iface.mainWindow())
        action.setCheckable(checkable)
        (action.toggled if checkable else action.triggered).connect(callback)
        self.iface.addPluginToRasterMenu(MENU, action)
        self.actions.append(action)
        return action

    # ------------------------------------------------------- aggancio auto
    def _auto_enabled(self) -> bool:
        return QgsSettings().value(SETTING_AUTO, True, type=bool)

    def _toggle_auto(self, checked: bool):
        QgsSettings().setValue(SETTING_AUTO, checked)

    def _on_layers_added(self, layers):
        for layer in layers:
            if not isinstance(layer, QgsRasterLayer):
                continue
            self._watch(layer)
            if self._auto_enabled() and core.is_dynamic(layer):
                self._apply(layer, quiet=True, force=False)

    def _on_layers_removed(self, layer_ids):
        for layer_id in layer_ids:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer is not None:
                self._unwatch(layer)

    def _watch(self, layer):
        # styleLoaded: l'utente ha caricato una QML da Proprieta' > Stile
        if hasattr(layer, "styleLoaded") and layer.id() not in self._slots:
            slot = lambda _categories, lyr=layer: self._on_style_loaded(lyr)
            layer.styleLoaded.connect(slot)
            self._slots[layer.id()] = slot

    def _unwatch(self, layer):
        slot = self._slots.pop(layer.id(), None)
        if slot is not None:
            try:
                layer.styleLoaded.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def _on_style_loaded(self, layer):
        if self._busy or not self._auto_enabled():
            return
        if core.is_dynamic(layer):
            # una QML appena caricata porta i suoi item: si riparte da quelli
            layer.removeCustomProperty(core.PROP_STOPS)
            self._apply(layer, quiet=True)

    # --------------------------------------------------------------- azioni
    def _selected_rasters(self):
        layers = [l for l in self.iface.layerTreeView().selectedLayers()
                  if isinstance(l, QgsRasterLayer)]
        if not layers:
            self._bar("Seleziona uno o piu' layer raster nel pannello Layer", Qgis.Warning)
        return layers

    def _apply(self, layer, quiet=False, force=True) -> bool:
        try:
            vmin, vmax, source = core.apply_dynamic(layer, force=force)
        except core.DynamicStyleError as exc:
            self._bar(str(exc), Qgis.Warning)
            return False
        self.iface.layerTreeView().refreshLayerSymbology(layer.id())
        if not quiet:
            self._bar(f"{layer.name()}: {vmin:g} – {vmax:g} ({source})", Qgis.Success)
        return True

    def apply_template(self):
        layers = self._selected_rasters()
        if not layers:
            return
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(), "Template dinamico", "", "Stile QGIS (*.qml)")
        if not path:
            return
        ok_count = 0
        self._busy = True
        try:
            for layer in layers:
                message, ok = layer.loadNamedStyle(path)
                if not ok:
                    self._bar(f"{layer.name()}: {message}", Qgis.Warning)
                    continue
                layer.removeCustomProperty(core.PROP_STOPS)
                if not core.is_dynamic(layer):
                    self._bar(f"{os.path.basename(path)} non e' un template dinamico "
                              "(manca dynamic_minmax=true)", Qgis.Warning)
                    break
                ok_count += self._apply(layer, quiet=len(layers) > 1)
        finally:
            self._busy = False
        if len(layers) > 1:
            self._bar(f"Template applicato a {ok_count} layer su {len(layers)}", Qgis.Info)

    def import_sld(self):
        layers = self._selected_rasters()
        if not layers:
            return
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(), "SLD di GeoServer", "", "SLD (*.sld *.xml)")
        if not path:
            return
        n, ok = QInputDialog.getInt(
            self.iface.mainWindow(), "Numero di classi",
            "Classi della rampa (0 = mantieni quelle dell'SLD):", 10, 0, 255)
        if not ok:
            return
        self._busy = True
        try:
            for layer in layers:
                try:
                    count = core.apply_sld_colormap(layer, path, n_classes=n or None)
                except core.DynamicStyleError as exc:
                    self._bar(f"{layer.name()}: {exc}", Qgis.Warning)
                    continue
                self.iface.layerTreeView().refreshLayerSymbology(layer.id())
                self._bar(f"{layer.name()}: SLD importato, {count} classi", Qgis.Success)
        finally:
            self._busy = False

    def refresh_selected(self):
        for layer in self._selected_rasters():
            if core.is_dynamic(layer):
                self._apply(layer)
            else:
                self._bar(f"{layer.name()}: lo stile non e' dinamico", Qgis.Warning)

    def force_stats_selected(self):
        # scansione completa in background: su raster grandi bloccherebbe la GUI
        for layer in self._selected_rasters():
            self._start_force_stats(layer)

    def _start_force_stats(self, layer):
        outcome = {}
        layer_id = layer.id()

        def run(task):
            try:
                outcome["sidecar"] = core.force_stats(layer, approx=False, feedback=task)
            except core.DynamicStyleError as exc:
                outcome["error"] = str(exc)
                return False
            return True

        def done(_exception, _result=None):
            if task in self._tasks:
                self._tasks.remove(task)
            if "error" in outcome:
                self._bar(outcome["error"], Qgis.Warning)
                return
            if "sidecar" not in outcome:  # task annullato
                return
            self._bar(f"Statistiche salvate in {os.path.basename(outcome['sidecar'])}",
                      Qgis.Success)
            current = QgsProject.instance().mapLayer(layer_id)  # puo' essere stato rimosso
            if current is not None and core.is_dynamic(current):
                self._apply(current, quiet=True)

        task = QgsTask.fromFunction(f"Statistiche {layer.name()}", run, on_finished=done)
        self._tasks.append(task)
        QgsApplication.taskManager().addTask(task)
        self._bar(f"{layer.name()}: calcolo statistiche in background…", Qgis.Info)

    def export_template(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsRasterLayer):
            self._bar("Seleziona un layer raster", Qgis.Warning)
            return
        modes = ["Min/Max del file", "Percentili (configurabili)"]
        choice, ok = QInputDialog.getItem(
            self.iface.mainWindow(), "Template dinamico",
            "Come calcolare il range di ogni raster:", modes, 0, False)
        if not ok:
            return
        p_low, p_high = 2.0, 98.0
        if choice == modes[1]:
            p_low, ok = QInputDialog.getDouble(
                self.iface.mainWindow(), "Percentile inferiore",
                "Percentile inferiore (%):", p_low, 0, 49.9, 1)
            if not ok:
                return
            p_high, ok = QInputDialog.getDouble(
                self.iface.mainWindow(), "Percentile superiore",
                "Percentile superiore (%):", p_high, p_low + 0.1, 100, 1)
            if not ok:
                return
        path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(), "Salva template dinamico",
            f"{layer.name()}_dinamico.qml", "Stile QGIS (*.qml)")
        if not path:
            return
        if not path.lower().endswith(".qml"):
            path += ".qml"
        try:
            count = core.export_template(
                layer, path, mode="percentile" if choice == modes[1] else "minmax",
                p_low=p_low, p_high=p_high)
        except core.DynamicStyleError as exc:
            self._bar(str(exc), Qgis.Warning)
            return
        self._bar(f"Template salvato ({count} classi): {os.path.basename(path)}", Qgis.Success)

    def open_guide(self):
        if not QDesktopServices.openUrl(QUrl(GUIDE_URL)):
            self._bar(f"Impossibile aprire il browser. Guida: {GUIDE_URL}", Qgis.Warning)

    # --------------------------------------------------------------- utilita'
    def _bar(self, text, level=Qgis.Info):
        self.iface.messageBar().pushMessage(core.TAG, text, level=level, duration=6)
        core.log(text, level)
