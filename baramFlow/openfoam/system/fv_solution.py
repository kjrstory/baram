#!/usr/bin/env python
# -*- coding: utf-8 -*-

from libbaram.openfoam.dictionary.dictionary_file import DictionaryFile

from baramFlow.coredb.coredb_reader import CoreDBReader
from baramFlow.coredb.numerical_db import NumericalDB, PressureVelocityCouplingScheme
from baramFlow.coredb.general_db import GeneralDB
from baramFlow.coredb.models_db import ModelsDB
from baramFlow.coredb.reference_values_db import ReferenceValuesDB
from baramFlow.coredb.material_db import MaterialDB
from baramFlow.openfoam.file_system import FileSystem


class FvSolution(DictionaryFile):
    def __init__(self, rname: str = None):
        """

        Args:
            rname: Region name. None for global fvSolution of multi region case, empty string for single region.
        """
        super().__init__(FileSystem.caseRoot(), self.systemLocation('' if rname is None else rname), 'fvSolution')

        self._db = CoreDBReader()
        if rname is None:
            self._region = None
        else:
            self._region = self._db.getRegionProperties(rname)

    def build(self):
        if self._data is not None:
            return self

        if self._region is None:
            # Global fvSolution in multi region case
            self._data = {
                'PIMPLE': {
                    'nOuterCorrectors':
                        self._db.getValue(NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/maxIterationsPerTimeStep'),
                }

            }

            return self

        # If region name is empty string, the only fvSolution in single region case.
        # Otherwise, fvSolution of specified region.
        scheme = self._db.getValue(NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/pressureVelocityCouplingScheme')
        consistent = 'no'
        momentumPredictor = 'on'
        energyOn = ModelsDB.isEnergyModelOn()

        if scheme == PressureVelocityCouplingScheme.SIMPLEC.value and self._region.isFluid():
            consistent = 'yes'
        if self._db.getValue(NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/useMomentumPredictor') == 'false':
            momentumPredictor = 'off'

        self._data = {
            # For multiphase model
            'solvers': {
                '"alpha.*"': {
                    'nAlphaCorr':
                        self._db.getValue(NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/multiphase/numberOfCorrectors'),
                    'nAlphaSubCycles':
                        self._db.getValue(
                            NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/multiphase/maxIterationsPerTimeStep'),
                    'cAlpha':
                        self._db.getValue(
                            NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/multiphase/phaseInterfaceCompressionFactor'),
                    'icAlpha': 0,
                    'MULESCorr':
                        'yes' if self._db.getValue(
                            NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/multiphase/useSemiImplicitMules') == 'true'
                        else 'no',
                    'nLimiterIter':
                        self._db.getValue(NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/multiphase/numberOfMulesIterations'),
                    'alphaApplyPrevCorr': 'yes',
                    'solver': 'smoothSolver',
                    'smoother': 'symGaussSeidel',
                    'tolerance': '1e-8',
                    'relTol': 0,
                    'minIter': 1,
                    'maxIter': 10,
                },
                '"(p|pcorr)"': (p := self._constructSolversP()),
                '"(p|pcorr)Final"': p,
                'p_rgh': (p_rgh := {
                    'solver': 'PCG',
                    'preconditioner': {
                        'preconditioner': 'GAMG',
                        'smoother': 'DIC',
                        'tolerance': '1e-5',
                        'relTol': '0.1',
                    },
                    'tolerance': '1e-16',
                    'relTol': '0.1',
                    'minIter': '1',
                    'maxIter': '5',
                }),
                'p_rghFinal': p_rgh,
                'h': (h := self._constructSolversH()),
                'hFinal': h,
                'rho': (rho := {
                    'solver': 'PCG',
                    'preconditioner': 'DIC',
                    'tolerance': '1e-16',
                    'relTol': '0.1',
                    'minIter': '1',
                    'maxIter': '5',
                }),
                'rhoFinal': rho,
                '"(U|k|epsilon|omega|nuTilda|scalar)"': (others := {
                    'solver': 'PBiCGStab',
                    'preconditioner': 'DILU',
                    'tolerance': '1e-16',
                    'relTol': '0.1',
                    'minIter': '1',
                    'maxIter': '5',
                }),
                '"(U|k|epsilon|omega|nuTilda|scalar)Final"': others,
            },
            'SIMPLE': {
                'consistent': consistent,
                'nNonOrthogonalCorrectors': '0',
                # only for fluid
                # 'pRefPoint': self._db.getVector(
                #     ReferenceValuesDB.REFERENCE_VALUES_XPATH + '/referencePressureLocation'),
                'pRefCell': 0,
                # only for fluid
                'pRefValue': self._db.getValue(ReferenceValuesDB.REFERENCE_VALUES_XPATH + '/pressure'),
                'solveEnergy': 'yes' if energyOn else 'no',  # NEXTfoam custom option
                'residualControl': {
                    'p': self._db.getValue('.//convergenceCriteria/pressure/absolute'),
                    'p_rgh': self._db.getValue('.//convergenceCriteria/pressure/absolute'),
                    'U': self._db.getValue('.//convergenceCriteria/momentum/absolute'),
                    'h': self._db.getValue('.//convergenceCriteria/energy/absolute'),
                    '"(k|epsilon|omega|nuTilda)"': self._db.getValue('.//convergenceCriteria/turbulence/absolute'),
                    # For multiphase model
                    '"alpha.*"': self._db.getValue('.//convergenceCriteria/volumeFraction/absolute'),
                }
            },
            'PIMPLE': {
                'consistent': consistent,
                'momentumPredictor': momentumPredictor,
                # only for fluid
                'turbOnFinalIterOnly': 'false',
                'nNonOrthogonalCorrectors': '0',
                # only for fluid
                'nCorrectors': self._db.getValue(NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/numberOfCorrectors'),
                # only in single region case
                'nOuterCorrectors':
                    self._db.getValue(NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/maxIterationsPerTimeStep'),
                'nAlphaSpreadIter': 0,
                'nAlphaSweepIter': 0,
                'maxCo': self._db.getValue('.//runConditions/maxCourantNumber'),
                'maxAlphaCo': self._db.getValue('.//runConditions/VoFMaxCourantNumber'),
                'nonOrthogonalityThreshold': '80',
                'skewnessThreshold': '0.95',
                # only for fluid
                # 'pRefPoint': self._db.getVector(
                #     ReferenceValuesDB.REFERENCE_VALUES_XPATH + '/referencePressureLocation'),
                'pRefCell': 0,
                # only for fluid
                'pRefValue': self._db.getValue(ReferenceValuesDB.REFERENCE_VALUES_XPATH + '/pressure'),
                'rDeltaTSmoothingCoeff': '0.5',
                'rDeltaTDampingCoeff': '0.5',
                'solveEnergy': 'yes' if energyOn else 'no',  # NEXTfoam custom option
                'residualControl': {
                    'p': {
                        'tolerance': self._db.getValue('.//convergenceCriteria/pressure/absolute'),
                        'relTol': self._db.getValue('.//convergenceCriteria/pressure/relative'),
                    },
                    'p_rgh': {
                        'tolerance': self._db.getValue('.//convergenceCriteria/pressure/absolute'),
                        'relTol': self._db.getValue('.//convergenceCriteria/pressure/relative'),
                    },
                    'U': {
                        'tolerance': self._db.getValue('.//convergenceCriteria/momentum/absolute'),
                        'relTol': self._db.getValue('.//convergenceCriteria/momentum/relative'),
                    },
                    'h': {
                        'tolerance': self._db.getValue('.//convergenceCriteria/energy/absolute'),
                        'relTol': self._db.getValue('.//convergenceCriteria/energy/relative'),
                    },
                    '"(k|epsilon|omega|nuTilda)"': {
                        'tolerance': self._db.getValue('.//convergenceCriteria/turbulence/absolute'),
                        'relTol': self._db.getValue('.//convergenceCriteria/turbulence/relative'),
                    },
                    # For multiphase model
                    '"alpha.*"': {
                        'tolerance': self._db.getValue('.//convergenceCriteria/volumeFraction/absolute'),
                        'relTol': self._db.getValue('.//convergenceCriteria/volumeFraction/relative'),
                    },
                }
            },
            'relaxationFactors': {
                'fields': {
                    'p': self._db.getValue('.//underRelaxationFactors/pressure'),
                    'pFinal': self._db.getValue('.//underRelaxationFactors/pressureFinal'),
                    'p_rgh': self._db.getValue('.//underRelaxationFactors/pressure'),
                    'p_rghFinal': self._db.getValue('.//underRelaxationFactors/pressureFinal'),
                    'rho': self._db.getValue('.//underRelaxationFactors/density'),
                    'rhoFinal': self._db.getValue('.//underRelaxationFactors/densityFinal'),
                },
                'equations': {
                    'U': self._db.getValue('.//underRelaxationFactors/momentum'),
                    'UFinal': self._db.getValue('.//underRelaxationFactors/momentumFinal'),
                    'h': 1 if self._region.isSolid() else self._db.getValue('.//underRelaxationFactors/energy'),
                    'hFinal':
                        1 if self._region.isSolid() else self._db.getValue('.//underRelaxationFactors/energyFinal'),
                    '"(k|epsilon|omega|nuTilda)"': self._db.getValue('.//underRelaxationFactors/turbulence'),
                    '"(k|epsilon|omega|nuTilda)Final"': self._db.getValue('.//underRelaxationFactors/turbulenceFinal'),
                }
            },
            'LU-SGS': {
                'residualControl': {
                    'rho': self._db.getValue('.//convergenceCriteria/density/absolute'),
                    'rhoU': self._db.getValue('.//convergenceCriteria/momentum/absolute'),
                    'rhoE': self._db.getValue('.//convergenceCriteria/energy/absolute'),
                    '"(k|epsilon|omega|nuTilda)"': self._db.getValue('.//convergenceCriteria/turbulence/absolute'),
                }
            },
            'Riemann': {
                'fluxScheme': self._db.getValue(
                    NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/densityBasedSolverParameters/fluxType'),
                'secondOrder':
                    'yes'
                    if self._db.getValue(NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/discretizationSchemes/momentum')
                       == 'secondOrderUpwind'
                    else 'no',
                'reconGradScheme': 'VKLimited Gauss linear 1',
                'roeFluxCoeffs': {
                    'epsilon': self._db.getValue(
                        NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/densityBasedSolverParameters/entropyFixCoefficient')
                },
                'AUSMplusUpFluxCoeffs': {
                    'MInf': self._db.getValue(
                        NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/densityBasedSolverParameters/cutOffMachNumber'),
                }
            },
            'fieldBounds': {
                'p': '1e-06 1e+10',
                'rho': '1e-06 1e+10',
                'h': '1e-06 1e+10',
                'e': '1e-06 1e+10',
                'rhoE': '1e-06 1e+10',
                'T': '1e-06 3e+4',
                'U': '3e+4',
            }
        }

        # For multiphase model
        for mid in self._region.secondaryMaterials:
            material = MaterialDB.getName(mid)
            self._data['relaxationFactors']['equations'][f'alpha.{material}'] = self._db.getValue(
                NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/underRelaxationFactors/volumeFraction')
            self._data['relaxationFactors']['equations'][f'alpha.{material}Final'] = self._db.getValue(
                NumericalDB.NUMERICAL_CONDITIONS_XPATH + '/underRelaxationFactors/volumeFractionFinal')

        absolute = self._db.getValue(f'{NumericalDB.NUMERICAL_CONDITIONS_XPATH}/convergenceCriteria/scalar/absolute')
        relative = self._db.getValue(f'{NumericalDB.NUMERICAL_CONDITIONS_XPATH}/convergenceCriteria/scalar/relative')
        self._data['SIMPLE']['residualControl']['scalar'] = absolute
        self._data['PIMPLE']['residualControl']['scalar'] = {
            'tolerance': absolute,
            'relTol': relative
        }

        self._data['relaxationFactors']['equations']['scalar'] = self._db.getValue(
            f'{NumericalDB.NUMERICAL_CONDITIONS_XPATH}/underRelaxationFactors/scalar')
        self._data['relaxationFactors']['equations']['scalarFinal'] = self._db.getValue(
            f'{NumericalDB.NUMERICAL_CONDITIONS_XPATH}/underRelaxationFactors/scalarFinal')
        #
        # for scalarID, fieldName in self._db.getUserDefinedScalars():
        #     xpath = f'{NumericalDB.NUMERICAL_CONDITIONS_XPATH}/convergenceCriteria/userDefinedScalars/scalar[scalarID="{scalarID}"]'
        #     absolute = self._db.getValue(xpath + '/absolute')
        #     relative = self._db.getValue(xpath + '/relative')
        #     self._data['SIMPLE']['residualControl'][fieldName] = absolute
        #     self._data['PIMPLE']['residualControl'][fieldName] = {
        #         'tolerance': absolute,
        #         'relTol': relative
        #     }
        #
        #     xpath = f'{NumericalDB.NUMERICAL_CONDITIONS_XPATH}/underRelaxationFactors/userDefinedScalars/scalar[scalarID="{scalarID}"]'
        #     self._data['relaxationFactors']['equations'][fieldName] = self._db.getValue(xpath + '/value')
        #     self._data['relaxationFactors']['equations'][f'{fieldName}Final'] = self._db.getValue(xpath + '/finalValue')

        return self

    def _constructSolversP(self):
        if GeneralDB.isCompressible():
            return {
                'solver': 'PBiCGStab',
                'preconditioner': 'DILU',
                'tolerance': '1e-16',
                'relTol': '0.1',
                'minIter': '1',
                'maxIter': '5',
            }
        else:
            return {
                'solver': 'PCG',
                'preconditioner': {
                    'preconditioner': 'GAMG',
                    'smoother': 'DIC',
                    'tolerance': '1e-5',
                    'relTol': '0.1',
                },
                'tolerance': '1e-16',
                'relTol': '0.1',
                'minIter': '1',
                'maxIter': '5',
            }

    def _constructSolversH(self):
        if self._region.isSolid():
            return {
                'solver': 'PBiCGStab',
                'preconditioner': {
                    'preconditioner': 'GAMG',
                    'smoother': 'DIC',
                    'tolerance': '1e-5',
                    'relTol': '0.1',
                },
                'tolerance': '1e-16',
                'relTol': '0.1',
                'minIter': '1',
                'maxIter': '5',
            }
        else:
            return {
                'solver': 'PBiCGStab',
                'preconditioner': {
                    'preconditioner': 'GAMG',
                    'smoother': 'DILU',
                    'tolerance': '1e-5',
                    'relTol': '0.1',
                },
                'tolerance': '1e-16',
                'relTol': '0.1',
                'minIter': '1',
                'maxIter': '5',
            }
