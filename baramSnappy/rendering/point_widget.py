#!/usr/bin/env python
# -*- coding: utf-8 -*-

from PySide6.QtCore import QObject, Signal
from vtkmodules.vtkCommonCore import vtkCommand
from vtkmodules.vtkInteractionWidgets import vtkPointWidget

from baramSnappy.app import app


class PointWidget(QObject):
    pointMoved = Signal(tuple)

    def __init__(self, view):
        super().__init__()

        self._view = view
        self._widget = vtkPointWidget()
        self._widget.SetInteractor(view.interactor())
        self._bounds = None

        self._widget.AddObserver(vtkCommand.InteractionEvent, self._pointMoved)

    def setBounds(self, bounds):
        position = bounds.center()

        self._bounds = bounds
        self._widget.SetPosition(*position)
        self._widget.PlaceWidget(bounds.xMin, bounds.xMax, bounds.yMin, bounds.yMax, bounds.zMin, bounds.zMax)

        return position

    def setPosition(self, x, y, z):
        x = max(x, self._bounds.xMin)
        x = min(x, self._bounds.xMax)
        y = max(y, self._bounds.yMin)
        y = min(y, self._bounds.yMax)
        z = max(z, self._bounds.zMin)
        z = min(z, self._bounds.zMax)
        self._widget.SetPosition(x, y, z)
        app.window.renderingView.refresh()

        return x, y, z

    def bounds(self):
        return self._bounds

    def on(self):
        self._widget.On()

    def off(self):
        self._widget.Off()

    def close(self):
        self._widget.RemoveAllObservers()
        self._widget.Off()
        self._widget = None

    def _pointMoved(self, obj, evnent):
        self.pointMoved.emit(obj.GetPosition())