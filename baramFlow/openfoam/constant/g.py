#!/usr/bin/env python
# -*- coding: utf-8 -*-

from libbaram.openfoam.dictionary.dictionary_file import DictionaryFile

from baramFlow.coredb.coredb_reader import CoreDBReader
from baramFlow.coredb.general_db import GeneralDB
from baramFlow.openfoam.file_system import FileSystem


class G(DictionaryFile):
    DIMENSIONS = '[0 1 -2 0 0 0 0]'

    def __init__(self):
        super().__init__(FileSystem.caseRoot(), self.constantLocation(), 'g')

    def build(self):
        if self._data is not None:
            return self

        db = CoreDBReader()

        self._data = {
            'dimensions': self.DIMENSIONS,
            'value': db.getVector(GeneralDB.OPERATING_CONDITIONS_XPATH + '/gravity/direction')
        }

        return self
