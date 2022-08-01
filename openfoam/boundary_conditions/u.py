#!/usr/bin/env python
# -*- coding: utf-8 -*-

from coredb import coredb
from coredb.filedb import BcFileRole
from coredb.boundary_db import BoundaryDB, BoundaryType, VelocitySpecification, VelocityProfile
from coredb.boundary_db import FlowRateInletSpecification, WallVelocityCondition, InterfaceMode
from coredb.project import Project
from openfoam.boundary_conditions.boundary_condition import BoundaryCondition
from openfoam.dictionary_file import DataClass


class U(BoundaryCondition):
    DIMENSIONS = '[0 1 -1 0 0 0 0]'

    def __init__(self, rname: str):
        super().__init__(self.boundaryLocation(rname), 'U', DataClass.CLASS_VOL_VECTOR_FIELD)

        self._rname = rname
        self._db = coredb.CoreDB()
        self._initialValue = self._db.getVector('.//initialization/initialValues/velocity')

    def build(self):
        if self._data is not None:
            return self

        self._data = {
            'dimensions': self.DIMENSIONS,
            'internalField': ('uniform', self._initialValue),
            'boundaryField': self._constructBoundaryField()
        }

        return self

    def _constructBoundaryField(self):
        field = {}

        boundaries = self._db.getBoundaryConditions(self._rname)
        for bcid, name, type_ in boundaries:
            xpath = BoundaryDB.getXPath(bcid)

            field[name] = {
                BoundaryType.VELOCITY_INLET.value:      (lambda: self._constructVelocityInletU(xpath, bcid, name)),
                BoundaryType.FLOW_RATE_INLET.value:     (lambda: self._constructFlowRateInletVelocity(xpath + '/flowRateInlet')),
                BoundaryType.PRESSURE_INLET.value:      (lambda: self._constructPressureInletOutletVelocity()),
                BoundaryType.PRESSURE_OUTLET.value:     (lambda: self._constructPressureInletOutletVelocity()),
                BoundaryType.ABL_INLET.value:           (lambda: self._constructAtmBoundaryLayerInletVelocity()),
                BoundaryType.OPEN_CHANNEL_INLET.value:  (lambda: self._constructVariableHeightFlowRateInletVelocity(self._db.getValue(xpath + '/openChannelInlet/volumeFlowRate'))),
                BoundaryType.OPEN_CHANNEL_OUTLET.value: (lambda: self._constructOutletPhaseMeanVelocity(self._db.getValue(xpath + '/openChannelOutlet/meanVelocity'))),
                BoundaryType.OUTFLOW.value:             (lambda: self._constructZeroGradient()),
                BoundaryType.FREE_STREAM.value:         (lambda: self._constructFreestreamVelocity(xpath + '/freeStream')),
                BoundaryType.FAR_FIELD_RIEMANN.value:   (lambda: self._constructFarfieldRiemann(xpath + '/farFieldRiemann')),
                BoundaryType.SUBSONIC_INFLOW.value:     (lambda: self._constructSubsonicInflow(xpath + '/subsonicInflow')),
                BoundaryType.SUBSONIC_OUTFLOW.value:    (lambda: self._constructSubsonicOutflow(xpath + '/subsonicOutflow')),
                BoundaryType.SUPERSONIC_INFLOW.value:   (lambda: self._constructFixedValue(self._db.getVector(xpath + '/supersonicInflow/velocity'))),
                BoundaryType.SUPERSONIC_OUTFLOW.value:  (lambda: self._constructZeroGradient()),
                BoundaryType.WALL.value:                (lambda: self._constructWallU(xpath)),
                BoundaryType.THERMO_COUPLED_WALL.value: (lambda: self._constructNoSlip()),
                BoundaryType.SYMMETRY.value:            (lambda: self._constructSymmetry()),
                BoundaryType.INTERFACE.value:           (lambda: self._constructInterfaceU(xpath)),
                BoundaryType.POROUS_JUMP.value:         (lambda: self._constructCyclic()),
                BoundaryType.FAN.value:                 (lambda: self._constructCyclic()),
                BoundaryType.EMPTY.value:               (lambda: self._constructEmpty()),
                BoundaryType.CYCLIC.value:              (lambda: self._constructCyclic()),
                BoundaryType.WEDGE.value:               (lambda: self._constructWedge()),
            }.get(type_)()

        return field

    def _constructFlowRateInletVelocity(self, xpath):
        spec = self._db.getValue(xpath + '/flowRate/specification')
        if spec == FlowRateInletSpecification.VOLUME_FLOW_RATE.value:
            return {
                'type': 'flowRateInletVelocity',
                'volumetricFlowRate': self._db.getValue(xpath + '/flowRate/volumeFlowRate')
            }
        elif spec == FlowRateInletSpecification.MASS_FLOW_RATE.value:
            return {
                'type': 'flowRateInletVelocity',
                'massFlowRate': self._db.getValue(xpath + '/flowRate/massFlowRate')
            }

    def _constructPressureInletOutletVelocity(self):
        return {
            'type': 'pressureInletOutletVelocity',
            'value': ('uniform', self._initialValue)
        }

    def _constructAtmBoundaryLayerInletVelocity(self):
        return {
            'type': 'atmBoundaryLayerInletVelocity',
            'flowDir': self._db.getVector(BoundaryDB.ABL_INLET_CONDITIONS_XPATH + '/flowDirection'),
            'zDir': self._db.getVector(BoundaryDB.ABL_INLET_CONDITIONS_XPATH + '/groundNormalDirection'),
            'Uref': self._db.getValue(BoundaryDB.ABL_INLET_CONDITIONS_XPATH + '/referenceFlowSpeed'),
            'Zref': self._db.getValue(BoundaryDB.ABL_INLET_CONDITIONS_XPATH + '/referenceHeight'),
            'z0': self._db.getValue(BoundaryDB.ABL_INLET_CONDITIONS_XPATH + '/surfaceRoughnessLength'),
            'd': self._db.getValue(BoundaryDB.ABL_INLET_CONDITIONS_XPATH + '/minimumZCoordinate')
        }

    def _constructVariableHeightFlowRateInletVelocity(self, flowRate):
        return {
            'type': 'variableHeightFlowRateInletVelocity',
            'alpha': 'alpha.liquid',
            'flowRate': flowRate,
            'value': ('uniform', self._initialValue)
        }

    def _constructOutletPhaseMeanVelocity(self, Umean):
        return {
            'type': 'outletPhaseMeanVelocity',
            'alpha': 'alpha.liquid',
            'Umean': Umean
        }

    def _constructFreestreamVelocity(self, xpath):
        return {
            'type': 'freestreamVelocity',
            'U': self._db.getVector(xpath + '/streamVelocity')
        }

    def _constructNoSlip(self):
        # Can set to 'slip' but set to 'fixedValue' for paraview
        return self._constructFixedValue('(0 0 0)')

    def _constructMovingWallVelocity(self):
        return {
            'type': 'movingWallVelocity',
            'value': 'uniform (0 0 0)'
        }

    def _constructRotatingWallVelocity(self, xpath):
        return {
            'type': 'rotatingWallVelocity',
            'origin': self._db.getVector(xpath + '/rotationAxisOrigin'),
            'axis': self._db.getVector(xpath + '/rotationAxisDirection'),
            'omega': self._db.getValue(xpath + '/speed'),
        }

    def _constructVelocityInletU(self, xpath, bcid, name):
        spec = self._db.getValue(xpath + '/velocityInlet/velocity/specification')
        if spec == VelocitySpecification.COMPONENT.value:
            profile = self._db.getValue(xpath + '/velocityInlet/velocity/component/profile')
            if profile == VelocityProfile.CONSTANT.value:
                return self._constructFixedValue(
                    self._db.getVector(xpath + '/velocityInlet/velocity/component/constant'))
            elif profile == VelocityProfile.SPATIAL_DISTRIBUTION.value:
                return self._constructTimeVaryingMappedFixedValue(
                    self._rname, name, 'U',
                    Project.instance().fileDB().getBcFile(bcid, BcFileRole.BC_VELOCITY_COMPONENT))
            elif profile == VelocityProfile.TEMPORAL_DISTRIBUTION.value:
                return self._constructUniformFixedValue(
                    xpath + '/velocityInlet/velocity/component/temporalDistribution/piecewiseLinear',
                    self.TableType.TEMPORAL_VECTOR_LIST)
        elif spec == VelocitySpecification.MAGNITUDE.value:
            profile = self._db.getValue(xpath + '/velocityInlet/velocity/magnitudeNormal/profile')
            if profile == VelocityProfile.CONSTANT.value:
                return self._constructSurfaceNormalFixedValue(
                    self._db.getValue(xpath + '/velocityInlet/velocity/magnitudeNormal/constant'))
            elif profile == VelocityProfile.SPATIAL_DISTRIBUTION.value:
                return self._constructTimeVaryingMappedFixedValue(
                    self._rname, name, 'U',
                    Project.instance().fileDB().getBcFile(bcid, BcFileRole.BC_VELOCITY_MAGNITUDE))
            elif profile == VelocityProfile.TEMPORAL_DISTRIBUTION.value:
                return self._constructUniformNormalFixedValue(
                    xpath + '/velocityInlet/velocity/magnitudeNormal/temporalDistribution/piecewiseLinear',
                    self.TableType.TEMPORAL_SCALAR_LIST)

    def _constructWallU(self, xpath):
        spec = self._db.getValue(xpath + '/wall/velocity/type')
        if spec == WallVelocityCondition.NO_SLIP.value:
            return self._constructNoSlip()
        elif spec == WallVelocityCondition.SLIP.value:
            return self._construcSlip()
        elif spec == WallVelocityCondition.MOVING_WALL.value:
            return self._constructMovingWallVelocity()
        elif spec == WallVelocityCondition.ATMOSPHERIC_WALL.value:
            return self._constructNoSlip()
        elif spec == WallVelocityCondition.TRANSLATIONAL_MOVING_WALL.value:
            return self._constructFixedValue(
                self._db.getVector(xpath + '/wall/velocity/translationalMovingWall/velocity'))
        elif spec == WallVelocityCondition.ROTATIONAL_MOVING_WALL.value:
            return self._constructRotatingWallVelocity(xpath + '/wall/velocity/rotationalMovingWall')

    def _constructInterfaceU(self, xpath):
        spec = self._db.getValue(xpath + '/interface/mode')
        if spec == InterfaceMode.REGION_INTERFACE.value:
            return self._constructNoSlip()
        else:
            return self._constructCyclicAMI()
