#!/usr/bin/env python
# -*- coding: utf-8 -*-

from enum import IntEnum, auto

from PySide6.QtWidgets import QTreeWidgetItem, QHeaderView
from PySide6.QtCore import Signal, QObject, QCoreApplication
from PySide6.QtGui import QIcon

from db.configurations_schema import CFDType, GeometryType

VOLUME_ICON_FILE = ':/icons/prism-outline.svg'
SURFACE_ICON_FILE = ':/icons/prism.svg'

CFDTypes = {
    CFDType.NONE.value: QCoreApplication.translate('GeometryPage', 'None'),
    CFDType.CELL_ZONE.value: QCoreApplication.translate('GeometryPage', 'CellZone'),
    CFDType.BOUNDARY.value: QCoreApplication.translate('GeometryPage', 'Boundary'),
    CFDType.CONFORMAL_MESH.value: QCoreApplication.translate('GeometryPage', 'Interface'),
    CFDType.NON_CONFORMAL_MESH.value: QCoreApplication.translate('GeometryPage', 'Intefarce')
}


class Column(IntEnum):
    NAME_COLUMN = 0
    TYPE_COLUMN = auto()


class GeometryItem(QTreeWidgetItem):
    def __init__(self, gId):
        super().__init__(int(gId))
        self._nameWidget = None

    def gId(self):
        return str(self.type())

    def updateGeometry(self, geometry):
        self.setText(Column.NAME_COLUMN, geometry['name'])
        self.setText(Column.TYPE_COLUMN, CFDTypes[geometry['cfdType']])


class GeometryList(QObject):
    eyeToggled = Signal(str, bool)

    showAllClicked = Signal()
    hideAllClicked = Signal()
    itemDoubleClicked = Signal(str)

    volumeIcon = QIcon(VOLUME_ICON_FILE)
    surfaceIcon = QIcon(SURFACE_ICON_FILE)

    def __init__(self, tree, geometries):
        super().__init__()

        self._tree = tree
        self._items = {}

        self._tree.header().setSectionResizeMode(Column.NAME_COLUMN, QHeaderView.ResizeMode.Stretch)

        self._connectSignalsSlots()

        for gId, geometry in geometries.geometries().items():
            self.add(gId, geometry)

    def add(self, gId, geometry):
        item = GeometryItem(gId)

        if geometry['volume']:
            self._items[geometry['volume']].addChild(item)
        else:
            self._tree.addTopLevelItem(item)
            item.setExpanded(True)

        item.setIcon(Column.NAME_COLUMN,
                     self.volumeIcon if geometry['gType'] == GeometryType.VOLUME.value else self.surfaceIcon)
        item.setText(Column.NAME_COLUMN, geometry['name'])
        item.setText(Column.TYPE_COLUMN, CFDTypes[geometry['cfdType']])

        self._items[gId] = item

    def update(self, gId, geometry):
        self._items[gId].updateGeometry(geometry)

    def remove(self, gId):
        index = -1
        for i in range(self._tree.topLevelItemCount()):
            if self._tree.topLevelItem(i).gId() == gId:
                index = i
                break

        if index > -1:
            item = self._tree.takeTopLevelItem(index)
            while item.childCount():
                citem = item.takeChild(0)
                del self._items[str(citem.gId())]
                del citem

            del self._items[str(gId)]
            del item

    def currentGeometryID(self):
        return str(self._tree.currentItem().gId()) if self._tree.currentItem() else None

    def childSurfaces(self, gId):
        item = self._items[gId]
        for i in range(item.childCount()):
            yield str(item.child(i).type())

    def _connectSignalsSlots(self):
        self._tree.itemDoubleClicked.connect(self._doubleClicked)

    def _doubleClicked(self, item, column):
        self.itemDoubleClicked.emit(item.gId())
