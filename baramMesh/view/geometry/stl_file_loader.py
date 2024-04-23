#!/usr/bin/env python
# -*- coding: utf-8 -*-
from vtkmodules.vtkFiltersModeling import vtkSelectEnclosedPoints
from vtkmodules.vtkFiltersCore import vtkAppendPolyData, vtkCleanPolyData

from libbaram.run import OpenFOAMError, RunUtility

from baramMesh.app import app
from baramMesh.openfoam.system.surface_patch_dict import SurfacePatchDict, SurfacePatchData
from baramMesh.rendering.vtk_loader import loadSTLFile


import qasync

SURFACE_PATCH_SRC_FILE_NAME = 'geometry.stl'
SURFACE_PATCHED_FILE_NAME = 'geometry_patched.stl'


class STLFileLoader:
    def __init__(self):
        self._fileSystem = app.fileSystem
        self._triSurfacePath = self._fileSystem.triSurfacePath() / SURFACE_PATCHED_FILE_NAME

    @qasync.asyncSlot()
    async def load(self, path, featureAngle):
        volumes = []
        surfaces = []

        solids = None
        if featureAngle:
            patchSrcFile = await self._fileSystem.copyTriSurfaceFrom(path, SURFACE_PATCH_SRC_FILE_NAME)

            SurfacePatchDict().build(SurfacePatchData(SURFACE_PATCH_SRC_FILE_NAME, featureAngle)).write()

            patchedFile = self._fileSystem.triSurfacePath() / SURFACE_PATCHED_FILE_NAME
            patchedFile.unlink(missing_ok=True)

            cm = RunUtility('surfacePatch', cwd=self._fileSystem.caseRoot())
            await cm.start()
            result = await cm.wait()

            if result != 0:
                raise OpenFOAMError(result, 'An error occurred while running surfacePatch.')

            if patchedFile.exists():
                solids = loadSTLFile(patchedFile)
                patchedFile.unlink()

            patchSrcFile.unlink()

        if solids is None:
            solids = loadSTLFile(path)

        appendFilter = vtkAppendPolyData()

        for data in solids:
            solid, name = data
            if vtkSelectEnclosedPoints.IsSurfaceClosed(solid):
                if solid.GetNumberOfPoints() > 0:
                    volumes.append(([data], None))
            else:
                surfaces.append(data)
                appendFilter.AddInputData(solid)

        if surfaces:
            cleanFilter = vtkCleanPolyData()
            cleanFilter.SetInputConnection(appendFilter.GetOutputPort())
            cleanFilter.Update()
            if vtkSelectEnclosedPoints.IsSurfaceClosed(cleanFilter.GetOutput()):
                volumes.append((surfaces, None))
                surfaces = []

        return volumes, surfaces

