#!/usr/bin/env python
# -*- coding: utf-8 -*-

import qasync
from PySide6.QtWidgets import QMessageBox, QMenu, QAbstractItemView
from PySide6.QtCore import Signal

from libbaram.run import OpenFOAMError

from baramSnappy.app import app
from baramSnappy.db.configurations_schema import CFDType, Shape, GeometryType
from baramSnappy.view.step_page import StepPage
from .geometry_add_dialog import GeometryAddDialog
from .stl_file_loader import STLFileLoader
from .geometry_import_dialog import ImportDialog
from .volume_dialog import VolumeDialog
from .surface_dialog import SurfaceDialog
from .geometry_list import GeometryList


class ContextMenu(QMenu):
    editActionTriggered = Signal()
    removeActionTriggered = Signal()

    def __init__(self, parent):
        super().__init__(parent)

        self.addAction(self.tr('Edit'), lambda: self.editActionTriggered.emit())
        self.addAction(self.tr('Remove'), lambda: self.removeActionTriggered.emit())


class GeometryPage(StepPage):
    def __init__(self, ui):
        super().__init__(ui, ui.geometryPage)

        self._geometryManager = None
        self._list = None
        self._loaded = False
        self._locked = False

        self._dialog = None
        self._volumeDialog = VolumeDialog(self._widget)
        self._surfaceDialog = SurfaceDialog(self._widget)
        self._menu = ContextMenu(self._list)

    def isNextStepAvailable(self):
        return not app.window.geometryManager.isEmpty()

    def lock(self):
        self._ui.geometryList.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._ui.buttons.setEnabled(False)
        self._locked = True

    def unlock(self):
        self._ui.geometryList.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._ui.buttons.setEnabled(True)
        self._locked = False

    def selected(self):
        if not self._loaded:
            self._geometryManager = app.window.geometryManager
            self._list = GeometryList(self._ui.geometryList, self._geometryManager)

            self._connectSignalsSlots()

            self._loaded = True

        app.window.meshManager.hide()

    def _connectSignalsSlots(self):
        # self._list.itemDoubleClicked.connect(self._openEditDialog)
        # self._ui.geometryList.currentItemChanged.connect(self._currentGeometryChanged)
        self._ui.geometryList.customContextMenuRequested.connect(self._executeContextMenu)
        self._ui.import_.clicked.connect(self._importClicked)
        self._ui.add.clicked.connect(self._addClicked)
        self._menu.editActionTriggered.connect(self._openEditDialog)
        self._menu.removeActionTriggered.connect(self._removeGeometry)
        self._volumeDialog.accepted.connect(self._volumeDialogAccepted)
        self._surfaceDialog.accepted.connect(self._updateSurfaces)

    def _executeContextMenu(self, pos):
        if not self._locked:
            self._menu.exec(self._ui.geometryList.mapToGlobal(pos))

    @qasync.asyncSlot()
    async def _importClicked(self):
        self._dialog = ImportDialog(self._widget)
        self._dialog.accepted.connect(self._importSTL)
        self._dialog.open()

    def _addClicked(self):
        self._dialog = GeometryAddDialog(self._widget)
        self._dialog.accepted.connect(self._openAddDialog)
        self._dialog.open()

    def _openAddDialog(self):
        self._volumeDialog.setupForAdding(*self._dialog.geometryInfo())
        self._volumeDialog.open()

    def _openEditDialog(self):
        gIds = self._list.selectedIDs()

        if len(gIds) == 1 and self._geometryManager.geometry(gIds[0])['gType'] == GeometryType.VOLUME.value:
            self._volumeDialog.setupForEdit(gIds[0])
            self._volumeDialog.open()
        else:
            self._surfaceDialog.setGIds(gIds)
            self._surfaceDialog.open()

    def _removeGeometry(self):
        confirm = QMessageBox.question(self._widget, self.tr("Remove Geometries"),
                                       self.tr('Are you sure you want to remove the selected items?'))
        if confirm != QMessageBox.StandardButton.Yes:
            return

        gIds = self._list.selectedIDs()

        volume = None
        if len(gIds) == 1 and self._geometryManager.geometry(gIds[0])['gType'] == GeometryType.VOLUME.value:
            volume = gIds[0]
            surfaces = [
                g for g in self._geometryManager.geometries() if self._geometryManager.geometry(g)['volume'] == volume]
        elif not any([self._geometryManager.geometry(gId)['volume'] for gId in gIds]):
            surfaces = gIds
        else:
            QMessageBox.information(self._widget, self.tr('Delete Surfaces'),
                                    self.tr('Surfaces contained in a volume cannot be deleted.'))
            return

        db = app.db.checkout()

        for gId in surfaces:
            db.removeGeometryPolyData(self._geometryManager.geometry(gId)['path'])
            db.removeElement('geometry', gId)
            self._list.remove(gId)
        self._geometryManager.removeGeometry(surfaces)

        if volume:
            db.removeElement('geometry', volume)
            self._list.remove(volume)
            self._geometryManager.removeGeometry([volume])

        app.db.commit(db)

        self._updateNextStepAvailable()

    @qasync.asyncSlot()
    async def _importSTL(self):
        try:
            for path in self._dialog.files():
                loader = STLFileLoader()
                volumes, surfaces = await loader.load(path, self._dialog.featureAngle())

                added = []

                db = app.db.checkout()
                name = path.stem
                seq = ''
                for volume in volumes:
                    seq = db.getUniqueSeq('geometry', 'name', name, seq)
                    volumeName = f'{name}{seq}'
                    element = db.newElement('geometry')
                    element.setValue('gType', GeometryType.VOLUME)
                    element.setValue('name', volumeName)
                    element.setValue('shape', Shape.TRI_SURFACE_MESH.value)
                    element.setValue('cfdType', CFDType.NONE.value)
                    volumeId = db.addElement('geometry', element)
                    added.append(volumeId)

                    surfaceName = f'{volumeName}_surface_'
                    sseq = '0'
                    for polyData in volume:
                        sseq = db.getUniqueSeq('geometry', 'name', surfaceName, sseq)
                        element = db.newElement('geometry')
                        element.setValue('gType', GeometryType.SURFACE.value)
                        element.setValue('volume', volumeId)
                        element.setValue('name', f'{surfaceName}{sseq}')
                        element.setValue('shape', Shape.TRI_SURFACE_MESH.value)
                        element.setValue('cfdType', CFDType.BOUNDARY.value)
                        element.setValue('path', db.addGeometryPolyData(polyData))
                        db.addElement('geometry', element)

                for polyData in surfaces:
                    seq = db.getUniqueSeq('geometry', 'name', name, seq)
                    element = db.newElement('geometry')
                    element.setValue('gType', GeometryType.SURFACE.value)
                    element.setValue('name', f'{name}{seq}')
                    element.setValue('shape', Shape.TRI_SURFACE_MESH.value)
                    element.setValue('cfdType', CFDType.BOUNDARY.value)
                    element.setValue('path', db.addGeometryPolyData(polyData))
                    gId = db.addElement('geometry', element)
                    added.append(gId)

                app.db.commit(db)

                for gId in added:
                    self._geometryCreated(gId)
        except OpenFOAMError as ex:
            code, message = ex.args
            QMessageBox.information(self._widget, self.tr('STL Loading Error'), f'{message} [{code}]')

    def _volumeDialogAccepted(self):
        if self._volumeDialog.isForCreation():
            self._geometryCreated(self._volumeDialog.gId())
        else:
            gId = self._volumeDialog.gId()
            volume = app.db.getElement('geometry',  gId)
            self._geometryManager.updateVolume(gId, volume, self._list.childSurfaces(gId))
            self._list.update(gId, volume)

    def _updateSurfaces(self):
        gIds = self._surfaceDialog.gIds()
        for gId, surface in app.db.getElements('geometry', lambda i, e: i in gIds).items():
            self._geometryManager.updateSurface(gId, surface)
            self._list.update(gId, surface)

    def _geometryCreated(self, gId):
        geometry = app.db.getElement('geometry',  gId)
        self._addGeometry(gId, geometry)

        if geometry['gType'] == GeometryType.VOLUME.value:
            surfaces = app.db.getElements('geometry', lambda i, e: e['volume'] == gId)
            for surfaceId in surfaces:
                self._addGeometry(surfaceId, surfaces[surfaceId])

    def _addGeometry(self, gId, geometry):
        self._geometryManager.addGeometry(gId, geometry)
        self._list.add(gId, geometry)
        self._updateNextStepAvailable()
