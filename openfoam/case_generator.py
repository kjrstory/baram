#!/usr/bin/env python
# -*- coding: utf-8 -*-

from PySide6.QtCore import QCoreApplication

from coredb import coredb
from coredb.cell_zone_db import RegionDB
from coredb.material_db import Phase
from coredb.boundary_db import BoundaryDB
from openfoam.constant.thermophysical_properties import ThermophysicalProperties
from openfoam.constant.operating_conditions import OperatingConditions
from openfoam.constant.MRF_properties import MRFProperties
from openfoam.constant.turbulence_properties import TurbulenceProperties
from openfoam.constant.transport_properties import TransportProperties
from openfoam.constant.g import G
from openfoam.boundary_conditions.p import P
from openfoam.boundary_conditions.u import U
from openfoam.boundary_conditions.t import T
from openfoam.boundary_conditions.k import K
from openfoam.boundary_conditions.epsilon import Epsilon
from openfoam.boundary_conditions.omega import Omega
from openfoam.boundary_conditions.nut import Nut
from openfoam.boundary_conditions.nuTilda import NuTilda
from openfoam.boundary_conditions.alphat import Alphat
from openfoam.system.fv_solution import FvSolution
from openfoam.system.control_dict import ControlDict
from openfoam.system.fv_schemes import FvSchemes
from openfoam.system.fv_options import FvOptions
from openfoam.system.decomposePar_dict import DecomposeParDict
from openfoam.polymesh.boundary import Boundary
from openfoam.file_system import FileSystem


class CaseGenerator:
    def __init__(self):
        self._db = coredb.CoreDB()
        self._errors = None

    def getErrors(self):
        return self._errors

    def generateFiles(self):
        if self._validate():
            return False

        regions = self._db.getRegions()
        for rname in regions:
            FileSystem.initRegionDirs(rname)

            ThermophysicalProperties(rname).build().write()
            OperatingConditions(rname).build().write()
            MRFProperties(rname).build().write()

            if RegionDB.getPhase(rname) != Phase.SOLID:
                TurbulenceProperties(rname).build().write()

            G(rname).build().write()
            P(rname, 'p_rgh').build().write()
            P(rname).build().write()
            U(rname).build().write()

            TransportProperties(rname).build().write()

            T(rname).build().write()
            Alphat(rname).build().write()

            K(rname).build().write()
            Nut(rname).build().write()
            Epsilon(rname).build().write()
            Omega(rname).build().write()
            NuTilda(rname).build().write()

            FvSchemes(rname).build().write()
            FvSolution(rname).build().write()
            FvOptions(rname).build().write()
            DecomposeParDict(rname).build().write()

            Boundary(rname).build().write()

        if len(regions) > 1:
            FvSolution().build().write()

        ControlDict().build().write()

        return True

    @classmethod
    def createCase(cls):
        FileSystem.setupNewCase()
        ControlDict().build().write()

    def _validate(self):
        self._errors = ''

        regions = self._db.getRegions()
        for rname in regions:
            boundaries = self._db.getBoundaryConditions(rname)
            for bcid, bcname, bctype in boundaries:
                xpath = BoundaryDB.getXPath(bcid)
                if BoundaryDB.needsCoupledBoundary(bctype) and self._db.getValue(xpath + '/coupledBoundary') == '0':
                    self._errors += QCoreApplication.translate(
                        'CaseGenerator',
                        f'{BoundaryDB.dbBoundaryTypeToText(bctype)} boundary "{bcname}" needs a coupled boundary.\n')

        return self._errors
