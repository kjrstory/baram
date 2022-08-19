#!/usr/bin/env python
# -*- coding: utf-8 -*-

import shutil
import asyncio

from coredb.project import Project


class FileLoadingError(Exception):
    pass


class FileSystem:
    CASE_DIRECTORY_NAME = 'case'
    CONSTANT_DIRECTORY_NAME = 'constant'
    BOUNDARY_CONDITIONS_DIRECTORY_NAME = '0'
    SYSTEM_DIRECTORY_NAME = 'system'
    POLY_MESH_DIRECTORY_NAME = 'polyMesh'
    BOUNDARY_DATA_DIRECTORY_NAME = 'boundaryData'
    REGION_PROPERTIES_FILE_NAME = 'regionProperties'

    _casePath = None
    _constantPath = None
    _boundaryConditionsPath = None
    _systemPath = None

    @classmethod
    def setup(cls):
        cls._casePath = cls.makeDir(Project.instance().path, cls.CASE_DIRECTORY_NAME)
        cls._constantPath = cls._casePath / cls.CONSTANT_DIRECTORY_NAME
        cls._boundaryConditionsPath = cls.makeDir(cls._casePath, cls.BOUNDARY_CONDITIONS_DIRECTORY_NAME)
        cls._systemPath = cls.makeDir(cls._casePath, cls.SYSTEM_DIRECTORY_NAME)

    @classmethod
    def initRegionDirs(cls, rname):
        cls.makeDir(cls._boundaryConditionsPath, rname)
        cls.makeDir(cls._constantPath, rname)
        cls.makeDir(cls._systemPath, rname)

    @classmethod
    def caseRoot(cls):
        return cls._casePath

    @classmethod
    def constantPath(cls, rname=None):
        return cls._constantPath / rname if rname else cls._constantPath

    @classmethod
    def boundaryConditionsPath(cls, rname=None):
        return cls._boundaryConditionsPath / rname if rname else cls._boundaryConditionsPath

    @classmethod
    def systemPath(cls, rname=None):
        return cls._systemPath / rname if rname else cls._systemPath

    @classmethod
    def boundaryFilePath(cls, rname):
        return cls.constantPath(rname) / cls.POLY_MESH_DIRECTORY_NAME / 'boundary'

    @classmethod
    def cellZonesFilePath(cls, rname):
        return cls.constantPath(rname) / cls.POLY_MESH_DIRECTORY_NAME / 'cellZones'

    @classmethod
    def boundaryDataPath(cls, rname):
        return cls.constantPath(rname) / rname / cls.BOUNDARY_DATA_DIRECTORY_NAME

    @classmethod
    def foamFilePath(cls):
        return cls._casePath / 'baram.foam'

    @classmethod
    def makeDir(cls, parent, directory):
        path = parent / directory
        path.mkdir(exist_ok=True)
        return path

    @classmethod
    def isPolyMesh(cls, path):
        return all([path.joinpath(f).is_file() for f in ['boundary', 'faces', 'neighbour', 'owner', 'points']])

    @classmethod
    def _copyMeshFromInternal(cls, directory, regions):
        if cls._constantPath.exists():
            shutil.rmtree(cls._constantPath)
        cls._constantPath.mkdir(exist_ok=True)

        srcFile = directory / cls.REGION_PROPERTIES_FILE_NAME
        if srcFile.is_file():
            objFile = cls.constantPath(cls.REGION_PROPERTIES_FILE_NAME)
            shutil.copyfile(srcFile, objFile)

            for rname in regions:
                srcPath = directory / rname / cls.POLY_MESH_DIRECTORY_NAME
                objPath = cls.constantPath(rname) / cls.POLY_MESH_DIRECTORY_NAME
                shutil.copytree(srcPath, objPath, copy_function=shutil.copyfile)
        else:
            polyMeshPath = cls.constantPath(cls.POLY_MESH_DIRECTORY_NAME)
            shutil.copytree(directory, polyMeshPath, copy_function=shutil.copyfile)

        with open(cls.foamFilePath(), 'a'):
            pass

    @classmethod
    async def copyMeshFrom(cls, directory, regions):
        await asyncio.to_thread(cls._copyMeshFromInternal, directory, regions)
