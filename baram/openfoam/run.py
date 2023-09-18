#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import platform
import subprocess
import psutil
from pathlib import Path
import asyncio

from baram.openfoam import parallel
from baram.openfoam.parallel import ParallelType
from baram import app

# Solver Directory Structure
#
# solvers/
#     mingw64/ : mingw64 library, only on Windows
#         bin/
#         lib/
#     openfoam/
#         bin/ : solvers reside here
#         lib/
#         lib/sys-openmpi
#         lib/dummy
#         etc/ : OpenFOAM system 'etc'
#         tlib/ : Third-Party Library, only for Linux and macOS

MPICMD = 'mpirun'

OPENFOAM = app.APP_PATH / 'solvers' / 'openfoam'

creationflags = 0
startupinfo = None

STDOUT_FILE_NAME = 'stdout.log'
STDERR_FILE_NAME = 'stderr.log'

WM_PROJECT_DIR = str(OPENFOAM)

if platform.system() == 'Windows':
    MPICMD = 'mpiexec'
    MINGW = app.APP_PATH / 'solvers' / 'mingw64'
    library = str(OPENFOAM/'lib') + os.pathsep \
              + str(OPENFOAM/'lib'/'msmpi') + os.pathsep \
              + str(MINGW/'bin') + os.pathsep \
              + str(MINGW/'lib')
    creationflags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
            | subprocess.CREATE_NEW_PROCESS_GROUP
    )
    startupinfo = subprocess.STARTUPINFO(
        dwFlags=subprocess.STARTF_USESHOWWINDOW,
        wShowWindow=subprocess.SW_HIDE
    )

    PATH = library + os.pathsep + os.environ['PATH']

    ENV = os.environ.copy()
    ENV.update({
        'WM_PROJECT_DIR': WM_PROJECT_DIR,
        'PATH': PATH
    })
else:
    library = str(OPENFOAM/'lib') + os.pathsep \
              + str(OPENFOAM/'lib'/'sys-openmpi') + os.pathsep \
              + str(OPENFOAM/'lib'/'dummy') + os.pathsep \
              + str(OPENFOAM/'tlib')

    if platform.system() == 'Darwin':
        LIBRARY_PATH_NAME = 'DYLD_LIBRARY_PATH'
    else:
        LIBRARY_PATH_NAME = 'LD_LIBRARY_PATH'

    if LIBRARY_PATH_NAME not in os.environ:
        os.environ[LIBRARY_PATH_NAME] = ''

    LIBRARY_PATH = library + os.pathsep + os.environ[LIBRARY_PATH_NAME]

    ENV = os.environ.copy()
    ENV.update({
        'WM_PROJECT_DIR': WM_PROJECT_DIR,
        LIBRARY_PATH_NAME: LIBRARY_PATH
    })


def openSolverProcess(cmd, casePath, inParallel):
    stdout = open(casePath / STDOUT_FILE_NAME, 'w')
    stderr = open(casePath / STDERR_FILE_NAME, 'w')

    if inParallel:
        cmd.append('-parallel')

    p = subprocess.Popen(cmd,
                         env=ENV, cwd=casePath,
                         stdout=stdout, stderr=stderr,
                         creationflags=creationflags,
                         startupinfo=startupinfo)

    stdout.close()
    stderr.close()

    return p


def launchSolverOnWindow(solver: str, casePath: Path, np: int = 1) -> (int, float):
    args = [MPICMD, '-np', str(np), OPENFOAM/'bin'/solver]
    if parallel.getParallelType() == ParallelType.CLUSTER:
        hosts = parallel.getHostfile()
        path = casePath / 'hostfile'
        with path.open(mode='w') as f:
            f.write(hosts)
        args[3:3] = ['-env', 'WM_PROJECT_DIR', WM_PROJECT_DIR, '-env', 'PATH', PATH, '-machinefile', str(path)]

    process = openSolverProcess(args, casePath, np > 1)

    ps = psutil.Process(pid=process.pid)
    return ps.pid, ps.create_time()


def launchSolverOnLinux(solver: str, casePath: Path, uuid, np: int = 1) -> (int, float):
    args = [OPENFOAM/'bin'/'baramd', '-project', uuid, '-cmdline', MPICMD, '-np', str(np), OPENFOAM/'bin'/solver]
    if parallel.getParallelType() == ParallelType.CLUSTER:
        hosts = parallel.getHostfile()
        path = casePath / 'hostfile'
        with path.open(mode='w') as f:
            f.write(hosts)
        args[7:7] = ['-x', 'WM_PROJECT_DIR', '-x', LIBRARY_PATH_NAME, '-hostfile', str(path)]

    process = openSolverProcess(args, casePath, np > 1)
    process.wait()

    processes = [p for p in psutil.process_iter(['pid', 'cmdline', 'create_time']) if (p.info['cmdline'] is not None) and (uuid in p.info['cmdline'])]
    if processes:
        ps = max(processes, key=lambda p: p.create_time())
        return ps.pid, ps.create_time()

    return None


def launchSolver(solver: str, casePath: Path, uuid, np: int = 1) -> (int, float):
    """Launch solver

    Launch solver in case folder
    Solver runs by mpirun/mpiexec by default

    Solver standard output file
        casePath/stdout.log
    Solver standard error file
        casePath/stderr.log

    Args:
        solver: solver name
        casePath: case folder absolute path
        uuid: UUID for the process
        np: number of process

    Returns:
        pid: process id of mpirun/mpiexec
        create_time: process creation time
    """
    if not isinstance(casePath, Path) or not casePath.is_absolute():
        raise AssertionError

    if platform.system() == 'Windows':
        return launchSolverOnWindow(solver, casePath, np)
    else:
        return launchSolverOnLinux(solver, casePath, uuid, np)


async def runUtility(program: str, *args, cwd=None, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL):
    global creationflags
    global startupinfo

    if platform.system() == 'Windows':
        creationflags = subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO(
            dwFlags=subprocess.STARTF_USESHOWWINDOW,
            wShowWindow=subprocess.SW_HIDE
        )

    proc = await asyncio.create_subprocess_exec(OPENFOAM/'bin'/program, *args,
                                                env=ENV, cwd=cwd,
                                                creationflags=creationflags,
                                                startupinfo=startupinfo,
                                                stdout=stdout,
                                                stderr=stderr)

    return proc


async def runParallelUtility(program: str, *args, np: int = 1, cwd: Path = None, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL):
    global creationflags
    global startupinfo

    if platform.system() == 'Windows':
        creationflags = subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO(
            dwFlags=subprocess.STARTF_USESHOWWINDOW,
            wShowWindow=subprocess.SW_HIDE
        )

    if np > 1:
        args = list(args)
        args.append('-parallel')

    cmdline = [MPICMD, '-np', str(np)]
    if parallel.getParallelType() == ParallelType.CLUSTER:
        hosts = parallel.getHostfile()
        path = cwd / 'hostfile'
        with path.open(mode='w') as f:
            f.write(hosts)
        if platform.system() == 'Windows':
            cmdline[-1:-1] = ['-env', 'WM_PROJECT_DIR', WM_PROJECT_DIR, '-env', 'PATH', PATH, '-machinefile', str(path)]
        else:
            cmdline[-1:-1] = ['-x', 'WM_PROJECT_DIR', '-x', LIBRARY_PATH_NAME, '-hostfile', str(path)]

    proc = await asyncio.create_subprocess_exec(*cmdline, OPENFOAM/'bin'/program, *args,
                                                env=ENV, cwd=cwd,
                                                creationflags=creationflags,
                                                startupinfo=startupinfo,
                                                stdout=stdout,
                                                stderr=stderr)

    return proc


def hasUtility(program: str):
    return (OPENFOAM / 'bin' / program).is_file()