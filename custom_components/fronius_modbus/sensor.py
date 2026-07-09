"""Platform for sensor integration."""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import CONF_NAME #, CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.icon import icon_for_battery_level
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import Entity, EntityCategory
from homeassistant.core import callback
from homeassistant.util import slugify

from . import HubConfigEntry
from .const import (
    INVERTER_SENSOR_TYPES,
    INVERTER_SYMO_SENSOR_TYPES,
    INVERTER_STORAGE_SENSOR_TYPES,
    METER_SENSOR_TYPES,
    METER_SENSOR_MAP,
    STORAGE_SENSOR_TYPES,
    ENTITY_PREFIX,
)
from .hub import Hub
from .base import FroniusModbusBaseEntity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    hub:Hub = config_entry.runtime_data

    entities = []

    for sensor_info in INVERTER_SENSOR_TYPES.values():
        sensor = FroniusModbusSensor(
            platform_name = ENTITY_PREFIX,
            hub = hub,
            device_info = hub.device_info_inverter,
            name = sensor_info[0],
            key = sensor_info[1],
            device_class = sensor_info[2],
            state_class = sensor_info[3],
            unit = sensor_info[4],
            icon = sensor_info[5],
            entity_category = sensor_info[6],
        )
        entities.append(sensor)

    for sensor_info in INVERTER_SYMO_SENSOR_TYPES.values():
        sensor = FroniusModbusSensor(
            platform_name = ENTITY_PREFIX,
            hub = hub,
            device_info = hub.device_info_inverter,
            name = sensor_info[0],
            key = sensor_info[1],
            device_class = sensor_info[2],
            state_class = sensor_info[3],
            unit = sensor_info[4],
            icon = sensor_info[5],
            entity_category = sensor_info[6],
        )
        entities.append(sensor)

    if hub.meter_configured:
        for i, unit_id in enumerate(hub.meter_unit_ids):
            meter_id = str(i + 1)
            
            meter_sensors = dict(METER_SENSOR_TYPES)
            meter_model = next((m for m in hub.sunspec_meter_models.get(unit_id, {}) if m in METER_SENSOR_MAP), None)
            if meter_model:
                meter_sensors.update(METER_SENSOR_MAP[meter_model])

            for sensor_info in meter_sensors.values():
                sensor = FroniusModbusSensor(
                    platform_name = ENTITY_PREFIX,
                    hub = hub,
                    device_info = hub.get_device_info_meter(meter_id),
                    name = f'Meter {meter_id} ' + sensor_info[0],
                    key = f'm{meter_id}_' + sensor_info[1],
                    device_class = sensor_info[2],
                    state_class = sensor_info[3],
                    unit = sensor_info[4],
                    icon = sensor_info[5],
                    entity_category = sensor_info[6],
                )
                entities.append(sensor)

    if hub.storage_configured:
        for sensor_info in INVERTER_STORAGE_SENSOR_TYPES.values():
            sensor = FroniusModbusSensor(
                platform_name = ENTITY_PREFIX,
                hub = hub,
                device_info = hub.device_info_inverter,
                name = sensor_info[0],
                key = sensor_info[1],
                device_class = sensor_info[2],
                state_class = sensor_info[3],
                unit = sensor_info[4],
                icon = sensor_info[5],
                entity_category = sensor_info[6],
            )
            entities.append(sensor)

        for sensor_info in STORAGE_SENSOR_TYPES.values():
            sensor = FroniusModbusSensor(
                platform_name = ENTITY_PREFIX,
                hub = hub,
                device_info = hub.device_info_storage,
                name = sensor_info[0],
                key = sensor_info[1],
                device_class = sensor_info[2],
                state_class = sensor_info[3],
                unit = sensor_info[4],
                icon = sensor_info[5],
                entity_category = sensor_info[6],
            )
            entities.append(sensor)

    num_modules = hub.num_mppt_modules
    num_pv_mppts = max(0, num_modules - 2) if hub.storage_configured else num_modules
    
    for i in range(num_pv_mppts):
        mppt_index = i + 1
        power_key = f'mppt{mppt_index}_power'
        lfte_key = f'mppt{mppt_index}_lfte'

        entities.append(FroniusModbusSensor(
            platform_name=ENTITY_PREFIX,
            hub=hub,
            device_info=hub.device_info_inverter,
            name=f'MPPT{mppt_index} power',
            key=power_key,
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            unit='W',
            icon='mdi:solar-power',
            entity_category=None,
        ))

        entities.append(FroniusModbusSensor(
            platform_name=ENTITY_PREFIX,
            hub=hub,
            device_info=hub.device_info_inverter,
            name=f'MPPT{mppt_index} lifetime energy',
            key=lfte_key,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            unit='Wh',
            icon='mdi:solar-panel',
            entity_category=None,
        ))

    async_add_entities(entities)
    return True

class FroniusModbusSensor(FroniusModbusBaseEntity, SensorEntity):
    """Representation of an Fronius Modbus Modbus sensor."""

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._key in self._hub.data:
            value = self._hub.data[self._key]
            if isinstance(value, str):
                if len(value)>255:
                    value = value[:255]
                    _LOGGER.error(f'state length > 255. k: {self._key} v: {value}')
            return value

            # self._icon = icon_for_battery_level(
            #     battery_level=self.native_value, charging=False
            # )                

    @property
    def extra_state_attributes(self):
        return None





