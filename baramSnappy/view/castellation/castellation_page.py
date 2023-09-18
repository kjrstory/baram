#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio

import qasync
from vtkmodules.vtkFiltersCore import vtkAppendPolyData, vtkCleanPolyData, vtkFeatureEdges
from vtkmodules.vtkIOGeometry import vtkSTLWriter, vtkOBJWriter
from PySide6.QtWidgets import QMessageBox

from baramSnappy.app import app
from baramSnappy.db.configurations_schema import GeometryType, Shape, CFDType
from baramSnappy.db.simple_schema import DBError
from baramSnappy.openfoam.system.snappy_hex_mesh_dict import SnappyHexMeshDict
from baramSnappy.libbaram.run import runUtility
from baramSnappy.libbaram.process import Processor, ProcessError
from baramSnappy.view.step_page import StepPage
from baramSnappy.view.widgets.progress_dialog_simple import ProgressDialogSimple
from baramSnappy.view.widgets.list_table import ListItemWithButtons
from .surface_refinement_dialog import SurfaceRefinementDialog
from .volume_refinement_dialog import VolumeRefinementDialog


class CastellationPage(StepPage):
    OUTPUT_TIME = 1

    def __init__(self, ui):
        super().__init__(ui, ui.castellationPage)

        self._ui = ui
        self._loaded = False
        self._db = None
        self._dialog = None

        ui.castellationConfigurationHeader.setContents(ui.castellationConfiguration)
        ui.castellationAdvancedHeader.setContents(ui.castellationAdvanced)
        ui.surfaceRefinementHeader.setContents(ui.surfaceRefinement)
        ui.volumeRefinementHeader.setContents(ui.volumeRefinement)

        ui.surfaceRefinement.setHeaderWithWidth([0, 0, 16, 16])
        ui.volumeRefinement.setHeaderWithWidth([0, 0, 16, 16])

        self._connectSignalsSlots()

    def lock(self):
        self._ui.castellationConfiguration.setEnabled(False)
        self._ui.castellationAdvanced.setEnabled(False)
        self._ui.surfaceRefinementAdd.setEnabled(False)
        self._ui.surfaceRefinement.setEnabled(False)
        self._ui.volumeRefinementAdd.setEnabled(False)
        self._ui.volumeRefinement.setEnabled(False)
        self._ui.castellationButtons.setEnabled(False)

    def unlock(self):
        self._ui.castellationConfiguration.setEnabled(True)
        self._ui.castellationAdvanced.setEnabled(True)
        self._ui.surfaceRefinementAdd.setEnabled(True)
        self._ui.surfaceRefinement.setEnabled(True)
        self._ui.volumeRefinementAdd.setEnabled(True)
        self._ui.volumeRefinement.setEnabled(True)
        self._ui.castellationButtons.setEnabled(True)

    def open(self):
        self._load()

    def selected(self):
        if not self._loaded:
            self._load()

        self._updateControlButtons()
        self._updateMesh()

    def save(self):
        try:
            castellation = self._db.checkout('castellation')

            castellation.setValue('nCellsBetweenLevels', self._ui.nCellsBetweenLevels.text(),
                              self.tr('Number of Cells between Levels'))
            castellation.setValue('resolveFeatureAngle', self._ui.resolveFeatureAngle.text(),
                              self.tr('Feature Angle Threshold'))
            castellation.setValue('vtkNonManifoldEdges', self._ui.keepNonManifoldEdges.isChecked())
            castellation.setValue('vtkBoundaryEdges', self._ui.keepOpenEdges.isChecked())

            castellation.setValue('maxGlobalCells', self._ui.maxGlobalCells.text(), self.tr('Max. Global Cell Count'))
            castellation.setValue('maxLocalCells', self._ui.maxLocalCells.text(), self.tr('Max. Local Cell Count'))
            castellation.setValue('minRefinementCells', self._ui.minRefinementCells.text(),
                              self.tr('Min.Refinement Cell Count'))
            castellation.setValue('maxLoadUnbalance', self._ui.maxLoadUnbalance.text(), self.tr('Max. Load Unbalance'))
            castellation.setValue('allowFreeStandingZoneFaces', self._ui.allowFreeStandingZoneFaces.isChecked())

            self._db.commit(castellation)
            app.db.commit(self._db)

            self._db = app.db.checkout()

            return True
        except DBError as e:
            QMessageBox.information(self._widget, self.tr('Input Error'), e.toMessage())
            return False

    def _connectSignalsSlots(self):
        self._ui.surfaceRefinementAdd.clicked.connect(lambda: self._openSurfaceRefinementDialog())
        self._ui.volumeRefinementAdd.clicked.connect(lambda: self._openVolumeRefinementDialog())
        self._ui.refine.clicked.connect(self._refine)
        self._ui.castellationReset.clicked.connect(self._reset)

    def _load(self):
        self._db = app.db.checkout()

        castellation = self._db.checkout('castellation')
        self._ui.nCellsBetweenLevels.setText(castellation.getValue('nCellsBetweenLevels'))
        self._ui.resolveFeatureAngle.setText(castellation.getValue('resolveFeatureAngle'))
        self._ui.keepNonManifoldEdges.setChecked(castellation.getValue('vtkNonManifoldEdges'))
        self._ui.keepOpenEdges.setChecked(castellation.getValue('vtkBoundaryEdges'))

        self._ui.maxGlobalCells.setText(castellation.getValue('maxGlobalCells'))
        self._ui.maxLocalCells.setText(castellation.getValue('maxLocalCells'))
        self._ui.minRefinementCells.setText(castellation.getValue('minRefinementCells'))
        self._ui.maxLoadUnbalance.setText(castellation.getValue('maxLoadUnbalance'))
        self._ui.allowFreeStandingZoneFaces.setChecked(castellation.getValue('allowFreeStandingZoneFaces'))

        self._ui.surfaceRefinement.clear()
        self._ui.volumeRefinement.clear()

        groups = {GeometryType.SURFACE.value: set(), GeometryType.VOLUME.value: set()}
        for gId, geometry in app.window.geometryManager.geometries().items():
            if group := geometry['castellationGroup']:
                groups[geometry['gType']].add(group)

        for groupId, element in castellation.getElements('refinementSurfaces').items():
            if groupId in groups[GeometryType.SURFACE.value]:
                self._addSurfaceRefinementItem(groupId, element['groupName'], element['surfaceRefinementLevel'])
            else:
                self._db.removeElement('castellation/refinementSurfaces', groupId)

        for groupId, element in castellation.getElements('refinementVolumes').items():
            if groupId in groups[GeometryType.VOLUME.value]:
                self._addVolumeRefinementItem(groupId, element['groupName'], element['volumeRefinementLevel'])
            else:
                self._db.removeElement('castellation/refinementVolumes', groupId)

        self._loaded = True
        self._updateControlButtons()

    def _openSurfaceRefinementDialog(self, groupId=None):
        self._dialog = SurfaceRefinementDialog(self._widget, self._db, groupId)
        self._dialog.accepted.connect(self._surfaceRefinementDialogAccepted)
        self._dialog.open()

    def _openVolumeRefinementDialog(self, groupId=None):
        self._dialog = VolumeRefinementDialog(self._widget, self._db, groupId)
        self._dialog.accepted.connect(self._volumeRefinementDialogAccepted)
        self._dialog.open()

    @qasync.asyncSlot()
    async def _refine(self):
        try:
            self.lock()

            if not self.save():
                return

            progressDialog = ProgressDialogSimple(self._widget, self.tr('Castellation Refinement'))
            progressDialog.setLabelText(self.tr('Updating Configurations'))
            progressDialog.open()

            progressDialog.setLabelText(self.tr('Writing Geometry Files'))
            self._writeGeometryFiles(progressDialog)
            SnappyHexMeshDict(castellationMesh=True).build().write()

            progressDialog.close()

            console = app.consoleView
            console.clear()
            proc = await runUtility('snappyHexMesh', cwd=app.fileSystem.caseRoot(),
                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            processor = Processor(proc)
            processor.outputLogged.connect(console.append)
            processor.errorLogged.connect(console.appendError)
            await processor.run()

            await app.window.meshManager.load(self.OUTPUT_TIME)
            self._updateControlButtons()
        except ProcessError as e:
            self.clearResult()
            QMessageBox.information(self._widget, self.tr('Error'),
                                    self.tr('Castellation Refinement Failed. [') + str(e.returncode) + ']')
        finally:
            self.unlock()

    def _reset(self):
        self._showPreviousMesh()
        self.clearResult()
        self._updateControlButtons()

    def _surfaceRefinementDialogAccepted(self):
        element = self._dialog.dbElement()
        if self._dialog.isCreationMode():
            self._addSurfaceRefinementItem(self._dialog.groupId(), element.getValue('groupName'),
                                           element.getValue('surfaceRefinementLevel'))
        else:
            self._ui.surfaceRefinement.item(self._dialog.groupId()).update(
                [element.getValue('groupName'), element.getValue('surfaceRefinementLevel')])

    def _addSurfaceRefinementItem(self, groupId, name, level):
        item = ListItemWithButtons(groupId, [name, level])
        item.editClicked.connect(lambda: self._openSurfaceRefinementDialog(groupId))
        item.removeClicked.connect(lambda: self._removeSurfaceRefinement(groupId))
        self._ui.surfaceRefinement.addItem(item)

    def _removeSurfaceRefinement(self, groupId):
        self._db.removeElement('castellation/refinementSurfaces', groupId)
        gIds = self._db.updateElements('geometry', 'castellationGroup', None,
                                       lambda i, e: e['castellationGroup'] == groupId)
        for gId in gIds:
            app.window.geometryManager.updateGeometryPropety(gId, 'castellationGroup', None)

        self._ui.surfaceRefinement.removeItem(groupId)

    def _volumeRefinementDialogAccepted(self):
        element = self._dialog.dbElement()
        if self._dialog.isCreationMode():
            self._addVolumeRefinementItem(self._dialog.groupId(), element.getValue('groupName'),
                                          element.getValue('volumeRefinementLevel'))
        else:
            self._ui.volumeRefinement.item(self._dialog.groupId()).update(
                [element.getValue('groupName'), element.getValue('volumeRefinementLevel')])

    def _addVolumeRefinementItem(self, groupId, name, level):
        item = ListItemWithButtons(groupId, [name, level])
        item.editClicked.connect(lambda: self._openVolumeRefinementDialog(groupId))
        item.removeClicked.connect(lambda: self._removeVolumeRefinement(groupId))
        self._ui.volumeRefinement.addItem(item)

    def _removeVolumeRefinement(self, groupId):
        self._db.removeElement('castellation/refinementVolumes', groupId)
        gIds = self._db.updateElements('geometry', 'castellationGroup', None,
                                       lambda i, e: e['castellationGroup'] == groupId)
        for gId in gIds:
            app.window.geometryManager.updateGeometryPropety(gId, 'castellationGroup', None)

        self._ui.volumeRefinement.removeItem(groupId)

    def _writeGeometryFiles(self, progressDialog):
        def writeGeometryFile(name, pd):
            writer = vtkSTLWriter()
            writer.SetFileName(str(filePath / f'{name}.stl'))
            writer.SetInputData(pd)
            writer.Write()

        def writeFeatureFile(name, pd):
            edges = vtkFeatureEdges()
            edges.SetInputData(pd)
            edges.SetNonManifoldEdges(app.db.getValue('castellation/vtkNonManifoldEdges'))
            edges.SetBoundaryEdges(app.db.getValue('castellation/vtkBoundaryEdges'))
            edges.Update()

            writer = vtkOBJWriter()
            writer.SetFileName(str(filePath / f"{name}.obj"))
            writer.SetInputData(edges.GetOutput())
            writer.Write()

        filePath = app.fileSystem.triSurfacePath()
        geometryManager = app.window.geometryManager

        for gId, geometry in geometryManager.geometries().items():
            if progressDialog.isCanceled():
                return

            if geometry['gType'] == GeometryType.SURFACE.value:
                if geometry['cfdType'] != CFDType.NONE.value or geometry['castellationGroup']:
                    polyData = geometryManager.polyData(gId)
                    if geometry['shape'] == Shape.TRI_SURFACE_MESH.value:
                        writeGeometryFile(geometry['name'], polyData)
                        writeFeatureFile(geometry['name'], polyData)
                    else:
                        writeFeatureFile(geometry['name'], polyData)
            else:
                if geometry['shape'] == Shape.TRI_SURFACE_MESH.value and geometry['castellationGroup']:
                    appendFilter = vtkAppendPolyData()
                    for surfaceId in geometryManager.subSurfaces(geometry['gId']):
                        appendFilter.AddInputData(geometryManager.polyData(surfaceId))

                    cleanFilter = vtkCleanPolyData()
                    cleanFilter.SetInputConnection(appendFilter.GetOutputPort())
                    cleanFilter.Update()

                    writeGeometryFile(geometry['name'], cleanFilter.GetOutput())

    def _updateControlButtons(self):
        if self.isNextStepAvailable():
            self._ui.refine.hide()
            self._ui.castellationReset.show()
            self._setNextStepEnabled(True)
        else:
            self._ui.refine.show()
            self._ui.castellationReset.hide()
            self._setNextStepEnabled(False)