#!/usr/bin/env python
# -*- coding: utf-8 -*-

import glob
import re
import typing
from io import StringIO
from pathlib import Path
from dataclasses import dataclass
import logging

import numpy as np
import pandas as pd
from PySide6.QtCore import QTimer, QObject, QThread, Signal


# "solverInfo.dat" sample
#   It is tab separated yet has spaces in it.
"""
# Solver information
# Time          	U_solver        	Ux_initial      	Ux_final        	Ux_iters        	Uy_initial      	Uy_final        	Uy_iters        	Uz_initial      	Uz_final        	Uz_iters        	U_converged     
0.0120482       	DILUPBiCGStab	1.00000000e+00	8.58724200e-08	1	1.00000000e+00	5.78842110e-14	1	1.00000000e+00	6.57355850e-14	1	false
0.0265769       	DILUPBiCGStab	3.66757700e-01	2.17151110e-13	1	9.06273050e-01	3.18900850e-13	1	3.76387760e-01	3.48509970e-13	1	false
0.0439595       	DILUPBiCGStab	2.31957720e-02	2.67950170e-08	1	5.38653860e-01	3.35496420e-13	1	3.79282860e-02	5.53125350e-08	1	false
...
"""

mrRegexPattern = r'(?P<region>[^/\\]+)[/\\]solverInfo_\d+[/\\](?P<time>[0-9]+(?:\.[0-9]+)?)[/\\]solverInfo(?:_(?P<dup>[0-9]+(?:\.[0-9]+)?))?\.dat'
srRegexPattern = r'[/\\]solverInfo_\d+[/\\](?P<time>[0-9]+(?:\.[0-9]+)?)[/\\]solverInfo(?:_(?P<dup>[0-9]+(?:\.[0-9]+)?))?\.dat'


logger = logging.getLogger(__name__)
formatter = logging.Formatter("[%(name)s] %(message)s")
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


@dataclass
class _SolverInfo:
    region: str
    time: float
    dup: str
    size: int
    path: Path
    f: typing.TextIO


def readCompleteLineOnly(f):
    line = f.readline()
    if line.endswith('\n'):
        if hasattr(f, 'incompleteLine'):
            line = f.incompleteLine + line
            f.incompleteLine = ''
        return line
    else:
        if hasattr(f, 'incompleteLine'):
            f.incompleteLine += line
        else:
            f.incompleteLine = line
        return ''


def readOutFile(f: typing.TextIO):
    lines = ''

    while line := readCompleteLineOnly(f):
        if not hasattr(f, 'residualHeader'):  # Initial State
            if not line.startswith('# Solver information'):
                raise RuntimeError
            f.residualHeader = None
        elif not f.residualHeader:  # Waiting residual header
            names = line.split()
            names.pop(0)  # remove '#' from the list
            if names[0] != 'Time':
                raise RuntimeError
            f.residualHeader = names
        else:  # Parse residuals
            lines += line

    if hasattr(f, 'residualHeader'):
        return lines, f.residualHeader
    else:
        return lines, None


def mergeDataFrames(data: [pd.DataFrame]):
    merged = None
    for df in data:
        if merged is None:
            merged = df
        else:
            left_on = {'Time', *(merged.columns.values.tolist())}
            right_on = {'Time', *(df.columns.values.tolist())}
            on = list(left_on.intersection(right_on))
            merged = pd.merge(merged, df, how='outer', on=on)

    return merged


def updateData(target, source):
    if target is None:
        return source
    else:
        # Drop obsoleted rows.
        # Dataframes should be kept PER REGION because of this dropping.
        # If dataframes of regions are merged, updated data in other regions can be lost.
        time = source.first_valid_index()
        filtered = target[target.index < time]
        return mergeDataFrames([filtered, source])


def updateDataFromFile(target: pd.DataFrame, region: str, f: typing.TextIO) -> (bool, pd.DataFrame):
    lines, names = readOutFile(f)
    if not lines:
        return False, target

    if region != '':
        names = [k if k == 'Time' else region + ':' + k for k in names]

    stream = StringIO(lines)
    df = pd.read_csv(stream, sep=r'\s+', names=names, dtype={'Time': np.float64})
    stream.close()

    df.set_index('Time', inplace=True)

    return True, updateData(target, df)


def getDataFrame(region, path) -> pd.DataFrame:
    with path.open(mode='r') as f:
        f.readline()  # skip '# Solver information' comment
        names = f.readline().split()  # read header
        names.pop(0)  # remove '#' from the list
        if names[0] != 'Time':
            raise RuntimeError
        if region != '':
            names = [k if k == 'Time' else region + ':' + k for k in names]
        df = pd.read_csv(f, sep=r'\s+', names=names, skiprows=0)
        df.set_index('Time', inplace=True)
        return df


class Worker(QObject):
    start = Signal()
    stop = Signal()
    updateResiduals = Signal()
    residualsUpdated = Signal(pd.DataFrame)

    def __init__(self, casePath: Path, regions: [str]):
        super().__init__()

        self.mrGlobPattern = casePath / 'postProcessing' / '*' / 'solverInfo_*' / '*' / 'solverInfo*.dat'
        self.srGlobPattern = casePath / 'postProcessing' / 'solverInfo_*' / '*' / 'solverInfo*.dat'

        self.regions = regions
        self.changingFiles = {r: None for r in regions}

        self.data = {r: None for r in regions}

        self.collectionReady = False

        self.infoFiles = None

        self.timer = None
        self.running = False

        self.start.connect(self.startRun)
        self.stop.connect(self.stopRun)

    def startRun(self):
        if self.running:
            return

        self.running = True

        # Get current snapshot of info files
        self.infoFiles = self.getInfoFiles()

        self.timer = QTimer()
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.process)
        self.timer.start()

    def stopRun(self):
        self.timer.stop()
        for s in self.changingFiles.values():
            s.f.close()
        self.running = False

    def process(self):
        updatedFiles = self.getUpdatedFiles(self.infoFiles)
        for p, s in updatedFiles.items():
            if p in self.infoFiles:
                self.infoFiles[p].size = s.size
            else:
                self.infoFiles[p] = s

            if self.changingFiles[s.region] is None:
                self.changingFiles[s.region] = self.infoFiles[p]

        if not self.collectionReady:
            collectionReady = all(self.changingFiles.values())
            if not collectionReady:
                return
            else:  # Now, Ready to collect
                self.collectionReady = True
                hasUpdate = False
                for s in self.infoFiles.values():
                    if s not in self.changingFiles.values():  # not-changing files
                        df = getDataFrame(s.region, s.path)
                        if df is not None:
                            self.data[s.region] = updateData(self.data[s.region], df)
                            hasUpdate = True

                for s in self.changingFiles.values():
                    s.f = open(s.path, 'r')
                    updated, df = updateDataFromFile(self.data[s.region], s.region, s.f)
                    if updated:
                        self.data[s.region] = updateData(self.data[s.region], df)
                        hasUpdate = True

                if hasUpdate:
                    self.residualsUpdated.emit(mergeDataFrames(self.data.values()))

                return

        # regular update routine
        hasUpdate = False
        for s in updatedFiles.values():
            updated, df = updateDataFromFile(self.data[s.region], s.region, self.infoFiles[s.path].f)
            if updated:
                self.data[s.region] = df
                hasUpdate = True

        if hasUpdate:
            self.residualsUpdated.emit(mergeDataFrames(self.data.values()))

    def getUpdatedFiles(self, current: {Path: _SolverInfo}) -> {Path: _SolverInfo}:
        infoFiles = self.getInfoFiles()

        updatedFiles = {}

        for p, s in infoFiles.items():
            if (p not in current) or (s.size != current[p].size):
                updatedFiles[p] = s

        return updatedFiles

    def _getInfoFilesMultiRegion(self) -> {Path: _SolverInfo}:
        mrFiles = [((p := Path(pstr)), p.stat().st_size) for pstr in glob.glob(str(self.mrGlobPattern))]
        infoFiles = {}
        for path, size in mrFiles:
            m = re.search(mrRegexPattern, str(path))
            if m.group('region') not in self.data:
                continue
            infoFiles[path] = _SolverInfo(m.group('region'), float(m.group('time')), m.group('dup'), size, path, None)
        return infoFiles

    def _getInfoFilesSingleRegion(self) -> {Path: _SolverInfo}:
        srFiles = [((p := Path(pstr)), p.stat().st_size) for pstr in glob.glob(str(self.srGlobPattern))]
        infoFiles = {}
        for path, size in srFiles:
            m = re.search(srRegexPattern, str(path))
            infoFiles[path] = _SolverInfo('', float(m.group('time')), m.group('dup'), size, path, None)
        return infoFiles

    def getInfoFiles(self) -> {Path: _SolverInfo}:
        if len(self.regions) > 1:
            infoFiles = self._getInfoFilesMultiRegion()
        else:
            infoFiles = self._getInfoFilesSingleRegion()

        # Drop obsoleted info file, which has newer info file in the same directory
        newerFiles = [p for p, s in infoFiles.items() if s.dup is not None]
        infoFiles = {p: s for p, s in infoFiles.items() if s.dup is not None or s.path not in newerFiles}

        infoFiles = dict(sorted(infoFiles.items(), key=lambda x: (x[1].region, x[1].time)))

        return infoFiles

    def update(self):
        self.residualsUpdated.emit(mergeDataFrames(self.data.values()))


class SolverInfoManager(QObject):
    residualsUpdated = Signal(pd.DataFrame)

    def __init__(self):
        super().__init__()

        self.worker = None
        self.thread = None

    def startCollecting(self, casePath: Path, regions: [str]):
        if self.thread is not None:
            return

        if not casePath.is_absolute():
            raise AssertionError

        self.thread = QThread()
        self.worker = Worker(casePath, regions)

        self.worker.moveToThread(self.thread)

        self.worker.residualsUpdated.connect(self.residualsUpdated)

        self.thread.start()

        self.worker.start.emit()

    def stopCollecting(self):
        if self.thread is None:
            return

        self.worker.stop.emit()
        self.thread.quit()

        self.worker = None
        self.thread = None

    def updateResiduals(self):
        if self.thread is None:
            raise FileNotFoundError

        self.worker.updateResiduals.emit()
