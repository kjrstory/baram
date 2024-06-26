#!/usr/bin/env python
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import QFrame, QGridLayout, QWidget, QLabel
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon, QPalette

from widgets.flat_push_button import FlatPushButton


class ListItem(QObject):
    def __init__(self, id_, texts):
        super().__init__()

        self._id = id_
        self._widgets = []

        for l in texts:
            self._widgets.append(QLabel(l))

    def columnCount(self):
        return len(self._widgets)

    def id(self):
        return self._id

    def widgets(self):
        return self._widgets

    def widget(self, column):
        return self._widgets[column]

    def enableEdit(self):
        return

    def disableEdit(self):
        return


class ListItemWithButtons(ListItem):
    editClicked = Signal()
    removeClicked = Signal()

    def __init__(self, id_: int, texts):
        super().__init__(id_, texts)

        self._removeButton = FlatPushButton(QIcon(':/icons/trash-outline.svg'), '')

        editButton = FlatPushButton(QIcon(':/icons/create-outline.svg'), '')

        self._widgets.append(editButton)
        self._widgets.append(self._removeButton)

        editButton.clicked.connect(self.editClicked)
        self._removeButton.clicked.connect(self.removeClicked)

    def update(self, texts):
        for i in range(len(texts)):
            self._widgets[i].setText(texts[i])

    def enableEdit(self):
        self._removeButton.setEnabled(True)

    def disableEdit(self):
        self._removeButton.setEnabled(False)


class ListTable(QFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._items = {}

    def setBackgroundColor(self, color=Qt.GlobalColor.white):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, color)
        self.setAutoFillBackground(True)
        self.setPalette(palette)

    def setHeaderWithWidth(self, widths):
        if self.layout():
            layout = self.layout()
        else:
            layout = QGridLayout(self)
            self.setLayout(layout)

        columnCount = len(widths)

        for i in range(columnCount):
            widget = layout.itemAtPosition(0, i)
            if widget is None:
                widget = QWidget()
                widget.setMaximumWidth(widths[i])
                layout.addWidget(widget, 0, i)

        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line, 1, 0, 1, columnCount)

    def addItem(self, item: ListItem):
        layout = self.layout()
        row = layout.rowCount()
        for i in range(item.columnCount()):
            layout.addWidget(item.widget(i), row, i)

        self._items[item.id()] = item

    def removeItem(self, id_):
        item = self._items.pop(id_)
        for widget in item.widgets():
            self.layout().removeWidget(widget)
            widget.deleteLater()

    def item(self, id_):
        return self._items[id_]

    def count(self):
        return len(self._items)

    def clear(self):
        for i in [key for key in self._items]:
            self.removeItem(i)

        self._items = {}

    def enableEdit(self):
        for item in self._items.values():
            item.enableEdit()

    def disableEdit(self):
        for item in self._items.values():
            item.disableEdit()
