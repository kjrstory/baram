#!/usr/bin/env python
# -*- coding: utf-8 -*-

from .configurations_schema import CFDType


def migrate(data):
    cfdTypes = [e.value for e in CFDType]
    for geometry in data['geometry'].values():
        if geometry['cfdType'] not in cfdTypes:
            geometry['cfdType'] = CFDType.INTERFACE.value

    for i in data['castellation']['refinementSurfaces']:
        if 'groupName' not in data['castellation']['refinementSurfaces'][i]:
            data['castellation']['refinementSurfaces'] = {}
        break

    for i in data['addLayers']['layers']:
        if 'groupName' not in data['addLayers']['layers'][i]:
            data['addLayers']['layers'] = {}
        break

    return data