#!/usr/bin/env python
# -*- coding: utf-8 -*-

from threading import Lock
from enum import Enum, auto
import copy
import logging

from lxml import etree
import xmlschema
import h5py
import pandas as pd

# To use ".qrc" QT Resource files
# noinspection PyUnresolvedReferences
import resource_rc

from resources import resource

ns = 'http://www.example.org/baram'
nsmap = {'': ns}

_mutex = Lock()

logger = logging.getLogger(__name__)


class Cancel(Exception):
    pass


class Error(Enum):
    OUT_OF_RANGE = auto()
    INTEGER_ONLY = auto()
    FLOAT_ONLY   = auto()
    REFERENCED   = auto()
    EMPTY        = auto()


class CoreDB(object):
    CONFIGURATION_ROOT = 'configurations'
    XSD_PATH = f'{CONFIGURATION_ROOT}/baram.cfg.xsd'
    XML_PATH = f'{CONFIGURATION_ROOT}/baram.cfg.xml'

    CELL_ZONE_PATH = f'{CONFIGURATION_ROOT}/cell_zone.xml'
    BOUNDARY_CONDITION_PATH = f'{CONFIGURATION_ROOT}/boundary_condition.xml'

    FORCE_MONITOR_PATH   = f'{CONFIGURATION_ROOT}/force_monitor.xml'
    POINT_MONITOR_PATH   = f'{CONFIGURATION_ROOT}/point_monitor.xml'
    SURFACE_MONITOR_PATH = f'{CONFIGURATION_ROOT}/surface_monitor.xml'
    VOLUME_MONITOR_PATH  = f'{CONFIGURATION_ROOT}/volume_monitor.xml'

    MATERIALS_PATH = 'materials.csv'

    FORCE_MONITOR_DEFAULT_NAME = 'force-mon-'
    POINT_MONITOR_DEFAULT_NAME = 'point-mon-'
    SURFACE_MONITOR_DEFAULT_NAME = 'surface-mon-'
    VOLUME_MONITOR_DEFAULT_NAME = 'volume-mon-'

    MONITOR_MAX_INDEX = 100
    MATERIAL_MAX_INDEX = 1000
    CELL_ZONE_MAX_INDEX = 1000
    BOUNDARY_CONDITION_MAX_INDEX = 10000

    def __new__(cls, *args, **kwargs):
        with _mutex:
            if not hasattr(cls, '_instance'):
                cls._instance = super(CoreDB, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._initialized = True

        self._modified = False
        self._filePath = None
        self._inContext = False
        self._backupTree = None
        self._lastError = None

        self._schema = xmlschema.XMLSchema(resource.file(self.XSD_PATH))

        xsdTree = etree.parse(resource.file(self.XSD_PATH))
        self._xmlSchema = etree.XMLSchema(etree=xsdTree)
        self._xmlParser = etree.XMLParser(schema=self._xmlSchema)
        self._xmlTree = etree.parse(resource.file(self.XML_PATH), self._xmlParser)

        df = pd.read_csv(resource.file(self.MATERIALS_PATH), header=0, index_col=0).transpose()
        self._materialDB = df.where(pd.notnull(df), None).to_dict()

        # Add 'air' as default material
        self.addMaterial('air')

    def __enter__(self):
        logger.debug('enter')
        self._backupTree = copy.deepcopy(self._xmlTree)
        self._lastError = None
        self._inContext = True
        return self

    def __exit__(self, eType, eValue, eTraceback):
        if self._lastError is not None or eType is not None:
            self._xmlTree = self._backupTree

        self._lastError = None
        self._backupTree = None
        self._inContext = False

        if eType == Cancel:
            logger.debug('exit with Cancel')
            return True
        else: # To make it clear
            logger.debug('exit without error')
            return None

    def getAttribute(self, xpath: str, name: str) -> str:
        """Returns attribute value on specified configuration path.

        Returns attribute value specified by 'xpath', and 'name'

        Args:
            xpath: XML xpath for the configuration item
            name: attribute name

        Returns:
            attribute value

        Raises:
            LookupError: Less or more than one item are matched, or attribute not found
        """
        elements = self._xmlTree.findall(xpath, namespaces=nsmap)
        if len(elements) != 1:
            raise LookupError

        value = elements[0].get(name)
        if value is None:
            raise LookupError

        logger.debug(f'getAttribute( {xpath}:{name} -> {value} )')

        return value

    def setAttribute(self, xpath: str, name: str, value: str):
        """Returns attribute value on specified configuration path.

        Returns attribute value specified by 'xpath', and 'name'

        Args:
            xpath: XML xpath for the configuration item
            name: attribute name
            value: attribute value

        Returns:

        Raises:
            LookupError: Less or more than one item are matched, or attribute not found
        """
        elements = self._xmlTree.findall(xpath, namespaces=nsmap)
        if len(elements) != 1:
            raise LookupError

        if name not in elements[0].keys():
            raise LookupError

        elements[0].set(name, value)

        logger.debug(f'setAttribute( {xpath}:{name} -> {value} )')

    def getValue(self, xpath: str) -> str:
        """Returns specified configuration value.

        Returns configuration value specified by 'xpath'

        Args:
            xpath: XML xpath for the configuration item

        Returns:
            configuration value

        Raises:
            LookupError: Less or more than one item are matched
        """
        elements = self._xmlTree.findall(xpath, namespaces=nsmap)
        if len(elements) != 1:
            raise LookupError

        element = elements[0]

        path = self._xmlTree.getelementpath(element)
        schema = self._schema.find(".//" + path, namespaces=nsmap)

        if schema is None:
            raise LookupError

        if not schema.type.has_simple_content():
            raise LookupError

        logger.debug(f'getValue( {xpath} -> {element.text} )')

        return element.text

    def setValue(self, xpath: str, value: str) -> Error:
        """Sets configuration value in specified path

        Sets configuration value in specified path

        Args:
            xpath: XML xpath for the configuration item
            value: configuration value

        Raises:
            LookupError: Less or more than one item are matched
            ValueError: Invalid configuration value
        """
        elements = self._xmlTree.findall(xpath, namespaces=nsmap)
        if len(elements) != 1:
            raise LookupError

        element = elements[0]

        path = self._xmlTree.getelementpath(element)
        schema = self._schema.find(".//" + path, namespaces=nsmap)

        if schema is None:
            raise LookupError

        if not schema.type.has_simple_content():
            raise LookupError

        if schema.type.local_name == 'inputNumberType' or (
                schema.type.base_type is not None and schema.type.base_type.local_name == 'inputNumberType'):  # The case when the type has restrictions
            try:
                decimal = float(value)
            except ValueError:
                self._lastError = Error.FLOAT_ONLY
                return Error.FLOAT_ONLY

            minValue = schema.type.min_value
            maxValue = schema.type.max_value

            if minValue is not None and decimal < minValue:
                self._lastError = Error.OUT_OF_RANGE
                return Error.OUT_OF_RANGE

            if maxValue is not None and decimal > maxValue:
                self._lastError = Error.OUT_OF_RANGE
                return Error.OUT_OF_RANGE

            element.text = value.lower().strip()

            logger.debug(f'setValue( {xpath} -> {element.text} )')
            self._modified = True

        elif schema.type.local_name == 'inputNumberListType':
            numbers = value.split()
            # To check if the strings in value are valid numbers
            # 'ValueError" exception is raised if invalid number found
            try:
                [float(n) for n in numbers]
            except ValueError:
                self._lastError = Error.FLOAT_ONLY
                return Error.FLOAT_ONLY

            element.text = ' '.join(numbers)

            logger.debug(f'setValue( {xpath} -> {element.text} )')
            self._modified = True

        elif schema.type.is_decimal():
            if schema.type.is_simple():
                name = schema.type.local_name.lower()
                minValue = schema.type.min_value
                maxValue = schema.type.max_value
            else:
                name = schema.type.content.primitive_type.local_name.lower()
                minValue = schema.type.content.min_value
                maxValue = schema.type.content.max_value

            if 'integer' in name:
                try:
                    decimal = int(value)
                except ValueError:
                    self._lastError = Error.INTEGER_ONLY
                    return Error.INTEGER_ONLY
            else:
                try:
                    decimal = float(value)
                except ValueError:
                    self._lastError = Error.FLOAT_ONLY
                    return Error.FLOAT_ONLY

            if minValue is not None and decimal < minValue:
                self._lastError = Error.OUT_OF_RANGE
                return Error.OUT_OF_RANGE

            if maxValue is not None and decimal > maxValue:
                self._lastError = Error.OUT_OF_RANGE
                return Error.OUT_OF_RANGE

            element.text = value.lower().strip()

            logger.debug(f'setValue( {xpath} -> {element.text} )')
            self._modified = True

        # String
        # For now, string value is set only by VIEW code not by user.
        # Therefore, raising exception(not returning value) is reasonable.
        else:
            if schema.type.is_restriction() and value not in schema.type.enumeration:
                raise ValueError

            element.text = value.strip()
            logger.debug(f'setValue( {xpath} -> {element.text} )')
            self._modified = True

        self._xmlSchema.assertValid(self._xmlTree)
        return None

    def setBulk(self, xpath: str, value: dict):
        """Set the value at the specified path

        Current configuration under the xpath will be cleared.
        Usually process is like following.
            1. A value of type dictionary is read by getBulk()
            2. Some values in the dictionary are modified
            3. the dictionary value is written back by setBulk
        It handles only dictionary, list and simple types

        Args:
            xpath: XML xpath for the configuration item
            value: configuration value of dictionary type

        Raises:
            LookupError: Less or more than one item are matched
            ValueError: Invalid configuration value
            RuntimeError: Called not in "with" context
        """
        def _setBulkInternal(element: etree.Element, data: dict):
            for k, v in data.items():
                # process attributes
                if k.startswith('@'):
                    element.set(k[1:], v)
                # process text
                elif k.startswith('$'):
                    element.text = str(v)
                # process dictionary
                elif isinstance(v, dict):
                    _setBulkInternal(etree.SubElement(element, f'{{{ns}}}{k}'), v)
                elif isinstance(v, list):
                    # Only primitive types or dictionary can be a member of the value
                    if len(v) == 0:
                        etree.SubElement(element, f'{{{ns}}}{k}')
                    elif isinstance(v[0], dict):
                        for item in v:
                            if not isinstance(item, dict):
                                raise ValueError
                            _setBulkInternal(etree.SubElement(element, f'{{{ns}}}{k}'), item)
                    else:
                        for item in v:
                            etree.SubElement(element, f'{{{ns}}}{k}').text = str(item)
                else:
                    etree.SubElement(element, f'{{{ns}}}{k}').text = str(v)

        if not self._inContext:
            raise RuntimeError

        if not isinstance(value, dict):
            raise ValueError

        elements = self._xmlTree.findall(xpath, namespaces=nsmap)
        if len(elements) != 1:
            raise LookupError

        elements[0].clear()
        _setBulkInternal(elements[0], value)

        self._xmlSchema.assertValid(self._xmlTree)

    def getBulk(self, xpath: str) -> dict:
        """Get the value at the specified path

        Current configuration under the xpath will be returned in dictionary type

        Args:
            xpath: XML xpath for the configuration item

        Raises:
            LookupError: Less or more than one item are matched
        """
        def _getBulkInternal(element: etree.Element) -> dict:
            data = {}

            # process attributes
            for k, v in element.items():
                data['@' + k] = v

            # process dictionary
            for child in element:
                tag = etree.QName(child.tag).localname
                result = _getBulkInternal(child)
                if tag in data:
                    if isinstance(data[tag], list):
                        data[tag].append(result)
                    else:
                        data[tag] = [
                            data[tag],
                            result
                        ]
                else:
                    data[tag] = result

            # process text
            if element.text is not None:
                if data:  # dictionary is not empty
                    data['$'] = element.text
                else:
                    data = element.text

            return data

        elements = self._xmlTree.findall(xpath, namespaces=nsmap)
        if len(elements) != 1:
            raise LookupError

        return _getBulkInternal(elements[0])

    def getMaterialsFromDB(self) -> list[(str, str, str)]:
        """Returns available materials from material database

        Returns available materials with name, chemicalFormula and phase from material database

        Returns:
            List of materials in tuple, '(name, chemicalFormula, phase)'
        """
        return [(k, v['chemicalFormula'], v['phase']) for k, v in self._materialDB.items()]

    def getMaterials(self) -> list[(int, str, str, str)]:
        """Returns configured materials

        Returns configured materials with name, chemicalFormula and phase from material database

        Returns:
            List of materials in tuple, '(id, name, chemicalFormula, phase)'
        """
        elements = self._xmlTree.findall(f'.//materials/material', namespaces=nsmap)

        return [(int(e.attrib['mid']), e.findtext('name', namespaces=nsmap), e.findtext('chemicalFormula', namespaces=nsmap), e.findtext('phase', namespaces=nsmap)) for e in elements]

    def addMaterial(self, name: str) -> int:
        """Add material to configuration from material database

        Add material to configuration from material database

        Raises:
            FileExistsError: Specified material is already in the configuration
            LookupError: material not found in material database
        """
        try:
            mdb = self._materialDB[name]
        except KeyError:
            raise LookupError

        material = self._xmlTree.find(f'.//materials/material[name="{name}"]', namespaces=nsmap)
        if material is not None:
            raise FileExistsError

        idList = self._xmlTree.xpath(f'.//x:materials/x:material/@mid', namespaces={'x': ns})

        for index in range(1, self.MATERIAL_MAX_INDEX):
            if str(index) not in idList:
                break
        else:
            raise OverflowError

        materialsElement = self._xmlTree.find('.//materials', namespaces=nsmap)

        def _materialPropertySubElement(parent: etree.Element, tag: str, pname: str):
            if mdb[pname] is None:
                return
            etree.SubElement(parent, f'{{{ns}}}{tag}').text = str(mdb[pname])

        material = etree.SubElement(materialsElement, f'{{{ns}}}material')
        material.attrib['mid'] = str(index)

        etree.SubElement(material, f'{{{ns}}}name').text = name

        _materialPropertySubElement(material, 'chemicalFormula', 'chemicalFormula')
        _materialPropertySubElement(material, 'phase', 'phase')
        _materialPropertySubElement(material, 'molecularWeight', 'molecularWeight')
        _materialPropertySubElement(material, 'absorptionCoefficient', 'absorptionCoefficient')
        _materialPropertySubElement(material, 'surfaceTension', 'surfaceTension')
        _materialPropertySubElement(material, 'saturationPressure', 'saturationPressure')
        _materialPropertySubElement(material, 'emissivity', 'emissivity')

        density = etree.SubElement(material, f'{{{ns}}}density')
        etree.SubElement(density, f'{{{ns}}}specification').text = 'constant'
        _materialPropertySubElement(density, 'constant', 'density')

        specificHeat = etree.SubElement(material, f'{{{ns}}}specificHeat')
        etree.SubElement(specificHeat, f'{{{ns}}}specification').text = 'constant'
        _materialPropertySubElement(specificHeat, 'constant', 'specificHeat')
        etree.SubElement(specificHeat, f'{{{ns}}}polynomial').text = ''

        if mdb['viscosity'] is not None:
            viscosity = etree.SubElement(material, f'{{{ns}}}viscosity')
            etree.SubElement(viscosity, f'{{{ns}}}specification').text = 'constant'
            _materialPropertySubElement(viscosity, 'constant', 'viscosity')
            etree.SubElement(viscosity, f'{{{ns}}}polynomial').text = ''
            if mdb['phase'] == 'gas':
                sutherland = etree.SubElement(viscosity, f'{{{ns}}}sutherland')
                _materialPropertySubElement(sutherland, 'coefficient', 'sutherlandCoefficient')
                _materialPropertySubElement(sutherland, 'temperature', 'sutherlandTemperature')

        thermalConductivity = etree.SubElement(material, f'{{{ns}}}thermalConductivity')
        etree.SubElement(thermalConductivity, f'{{{ns}}}specification').text = 'constant'
        _materialPropertySubElement(thermalConductivity, 'constant', 'thermalConductivity')
        etree.SubElement(thermalConductivity, f'{{{ns}}}polynomial').text = ''

        self._xmlSchema.assertValid(self._xmlTree)

        return index

    def removeMaterial(self, name: str) -> Error:
        parent = self._xmlTree.find(f'.//materials', namespaces=nsmap)
        material = parent.find(f'material[name="{name}"]', namespaces=nsmap)
        if material is None:
            raise LookupError

        # check if the material is referenced by other elements

        mid = material.attrib['mid']
        idList = self._xmlTree.xpath(f'.//x:cellZones/x:region/x:material/text()', namespaces={'x': ns})
        if str(mid) in idList:
            return Error.REFERENCED

        elements = self._xmlTree.findall(f'.//materials/material', namespaces=nsmap)
        if len(elements) == 1:  # this is the last material in the list
            return Error.EMPTY

        parent.remove(material)
        return None

    def addRegion(self, rname: str):
        region = self._xmlTree.find(f'.//regions/region[name="{rname}"]', namespaces=nsmap)

        if region is not None:
            raise FileExistsError

        parent = self._xmlTree.find('.//regions', namespaces=nsmap)

        region = etree.SubElement(parent, f'{{{ns}}}region')

        etree.SubElement(region, f'{{{ns}}}name').text = rname

        # set default material for the region
        materials = self.getMaterials()
        if len(materials) == 0:
            raise AssertionError  # One material should exist

        # use the first material for default material for the region
        etree.SubElement(region, f'{{{ns}}}material').text = str(materials[0][0])

        cellZones = etree.SubElement(region, f'{{{ns}}}cellZones')
        etree.SubElement(region, f'{{{ns}}}boundaryConditions')

        # add default cell zone named "All"
        czoneTree = etree.parse(resource.file(self.CELL_ZONE_PATH), self._xmlParser)
        cellZones.append(czoneTree.getroot())

        self._xmlSchema.assertValid(self._xmlTree)

    def getRegions(self) -> list[str]:
        names = self._xmlTree.xpath(f'.//x:region/x:name/text()', namespaces={'x': ns})
        return [str(r) for r in names]

    def addCellZone(self, rname: str, zname: str) -> int:
        zone = self._xmlTree.find(f'.//region[name="{rname}"]/cellZones/cellZone[name="{zname}"]', namespaces=nsmap)

        if zone is not None:
            raise FileExistsError

        idList = self._xmlTree.xpath(f'.//x:region[x:name="{rname}"]/x:cellZones/x:cellZone/@czid', namespaces={'x': ns})

        for index in range(1, self.CELL_ZONE_MAX_INDEX):
            if str(index) not in idList:
                break
        else:
            raise OverflowError

        # 'region' cannot be None because zoneTree lookup above succeeded
        cellZones = self._xmlTree.find(f'.//region[name="{rname}"]/cellZones', namespaces=nsmap)

        zoneTree = etree.parse(resource.file(self.CELL_ZONE_PATH), self._xmlParser)
        zone = zoneTree.getroot()
        zone.find('name', namespaces=nsmap).text = zname
        zone.attrib['czid'] = str(index)

        cellZones.append(zone)

        self._xmlSchema.assertValid(self._xmlTree)

        return index

    def getCellZones(self, rname: str) -> list[(int, str)]:
        elements = self._xmlTree.findall(f'.//region[name="{rname}"]/cellZones/cellZone', namespaces=nsmap)
        return [(int(e.attrib['czid']), e.find('name', namespaces=nsmap).text) for e in elements]

    def addBoundaryCondition(self, rname: str, bname: str, geometricalType: str) -> int:
        bc = self._xmlTree.find(f'.//region[name="{rname}"]/boundaryConditions/boundaryCondition[name="{bname}"]', namespaces=nsmap)

        if bc is not None:
            raise FileExistsError

        idList = self._xmlTree.xpath(f'.//x:region[x:name="{rname}"]/x:boundaryConditions/x:boundaryCondition/@bcid', namespaces={'x': ns})

        for index in range(1, self.BOUNDARY_CONDITION_MAX_INDEX):
            if str(index) not in idList:
                break
        else:
            raise OverflowError

        parent = self._xmlTree.find(f'.//region[name="{rname}"]/boundaryConditions', namespaces=nsmap)

        bcTree = etree.parse(resource.file(self.BOUNDARY_CONDITION_PATH), self._xmlParser)
        bc = bcTree.getroot()
        bc.find('name', namespaces=nsmap).text = bname
        bc.attrib['bcid'] = str(index)

        if geometricalType is not None:
            bc.find('geometricalType', namespaces=nsmap).text = geometricalType
            # ToDo: set default physicalType according to the geometricalType

        parent.append(bc)

        self._xmlSchema.assertValid(self._xmlTree)

        return index

    def getBoundaryConditions(self, rname: str) -> list[(int, str, str)]:
        elements = self._xmlTree.findall(f'.//region[name="{rname}"]/boundaryConditions/boundaryCondition', namespaces=nsmap)
        return [(int(e.attrib['bcid']),
                 e.find('name', namespaces=nsmap).text,
                 e.find('physicalType', namespaces=nsmap).text) for e in elements]

    def addForceMonitor(self) -> str:
        names = self.getForceMonitors()

        for index in range(1, self.MONITOR_MAX_INDEX):
            monitorName = self.FORCE_MONITOR_DEFAULT_NAME+str(index)
            if monitorName not in names:
                break
        else:
            raise OverflowError

        parent = self._xmlTree.find(f'.//monitors/forces', namespaces=nsmap)

        forceTree = etree.parse(resource.file(self.FORCE_MONITOR_PATH), self._xmlParser)
        forceTree.find('name', namespaces=nsmap).text = monitorName

        parent.append(forceTree.getroot())

        self._xmlSchema.assertValid(self._xmlTree)

        return monitorName

    def removeForceMonitor(self, name: str):
        monitor = self._xmlTree.find(f'.//monitors/forces/forceMonitor[name="{name}"]', namespaces=nsmap)
        if monitor is None:
            raise LookupError

        parent = self._xmlTree.find(f'.//monitors/forces', namespaces=nsmap)
        parent.remove(monitor)

    def getForceMonitors(self) -> list[str]:
        names = self._xmlTree.xpath(f'.//x:monitors/x:forces/x:forceMonitor/x:name/text()', namespaces={'x': ns})
        return [str(r) for r in names]

    def addPointMonitor(self) -> str:
        names = self.getPointMonitors()

        for index in range(1, self.MONITOR_MAX_INDEX):
            monitorName = self.POINT_MONITOR_DEFAULT_NAME+str(index)
            if monitorName not in names:
                break
        else:
            raise OverflowError

        parent = self._xmlTree.find(f'.//monitors/points', namespaces=nsmap)

        pointTree = etree.parse(resource.file(self.POINT_MONITOR_PATH), self._xmlParser)
        pointTree.find('name', namespaces=nsmap).text = monitorName

        parent.append(pointTree.getroot())

        self._xmlSchema.assertValid(self._xmlTree)

        return monitorName

    def removePointMonitor(self, name: str):
        monitor = self._xmlTree.find(f'.//monitors/points/pointMonitor[name="{name}"]', namespaces=nsmap)
        if monitor is None:
            raise LookupError

        parent = self._xmlTree.find(f'.//monitors/points', namespaces=nsmap)
        parent.remove(monitor)

    def getPointMonitors(self) -> list[str]:
        names = self._xmlTree.xpath(f'.//x:monitors/x:points/x:pointMonitor/x:name/text()', namespaces={'x': ns})
        return [str(r) for r in names]

    def addSurfaceMonitor(self) -> str:
        names = self.getSurfaceMonitors()

        for index in range(1, self.MONITOR_MAX_INDEX):
            monitorName = self.SURFACE_MONITOR_DEFAULT_NAME+str(index)
            if monitorName not in names:
                break
        else:
            raise OverflowError

        parent = self._xmlTree.find(f'.//monitors/surfaces', namespaces=nsmap)

        surfaceTree = etree.parse(resource.file(self.SURFACE_MONITOR_PATH), self._xmlParser)
        surfaceTree.find('name', namespaces=nsmap).text = monitorName

        parent.append(surfaceTree.getroot())

        self._xmlSchema.assertValid(self._xmlTree)

        return monitorName

    def removeSurfaceMonitor(self, name: str):
        monitor = self._xmlTree.find(f'.//monitors/surfaces/surfaceMonitor[name="{name}"]', namespaces=nsmap)
        if monitor is None:
            raise LookupError

        parent = self._xmlTree.find(f'.//monitors/surfaces', namespaces=nsmap)
        parent.remove(monitor)

    def getSurfaceMonitors(self) -> list[str]:
        names = self._xmlTree.xpath(f'.//x:monitors/x:surfaces/x:surfaceMonitor/x:name/text()', namespaces={'x': ns})
        return [str(r) for r in names]

    def addVolumeMonitor(self) -> str:
        names = self.getVolumeMonitors()

        for index in range(1, self.MONITOR_MAX_INDEX):
            monitorName = self.VOLUME_MONITOR_DEFAULT_NAME+str(index)
            if monitorName not in names:
                break
        else:
            raise OverflowError

        parent = self._xmlTree.find(f'.//monitors/volumes', namespaces=nsmap)

        volumeTree = etree.parse(resource.file(self.VOLUME_MONITOR_PATH), self._xmlParser)
        volumeTree.find('name', namespaces=nsmap).text = monitorName

        parent.append(volumeTree.getroot())

        self._xmlSchema.assertValid(self._xmlTree)

        return monitorName

    def removeVolumeMonitor(self, name: str):
        monitor = self._xmlTree.find(f'.//monitors/volumes/volumeMonitor[name="{name}"]', namespaces=nsmap)
        if monitor is None:
            raise LookupError

        parent = self._xmlTree.find(f'.//monitors/volumes', namespaces=nsmap)
        parent.remove(monitor)

    def getVolumeMonitors(self) -> list[str]:
        names = self._xmlTree.xpath(f'.//x:monitors/x:volumes/x:volumeMonitor/x:name/text()', namespaces={'x': ns})
        return [str(r) for r in names]

    @property
    def isModified(self) -> bool:
        return self._modified

    def saveAs(self, path: str):
        f = h5py.File(path, 'w')
        try:
            dt = h5py.string_dtype(encoding='utf-8')
            ds = f.create_dataset('configuration', (1,), dtype=dt)
            ds[0] = etree.tostring(self._xmlTree, xml_declaration=True, encoding='UTF-8')

            # ToDo: write the rest of data like uploaded polynomials

        finally:
            f.close()

        self._filePath = path
        self._modified = False

    def save(self):
        with h5py.File(self._filePath, 'r+') as f:
            ds = f['configuration']
            if h5py.check_string_dtype(ds.dtype) is None:
                raise ValueError
            ds[0] = etree.tostring(self._xmlTree.getroot(), xml_declaration=True, encoding='UTF-8')
            # ToDo: write the rest of data like uploaded polynomials

        self._modified = False

    def load(self, path: str):
        with h5py.File(path, 'r') as f:
            ds = f['configuration']
            if h5py.check_string_dtype(ds.dtype) is None:
                raise ValueError
            root = etree.fromstring(ds[0], self._xmlParser)

        self._xmlTree = root
        self._filePath = path
        self._modified = False
