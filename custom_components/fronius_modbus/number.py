import logging
from typing import Optional, Dict, Any

from .const import (
    STORAGE_NUMBER_TYPES,
)

from homeassistant.core import callback
from homeassistant.const import CONF_NAME
from homeassistant.components.number import (
    NumberEntity,
)

from .hub import Hub
from .base import FroniusModbusBaseEntity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities) -> None:
    hub:Hub = config_entry.runtime_data

    entities = []

    if hub.storage_configured:

        for number_info in STORAGE_NUMBER_TYPES:

            max = None
            max_key = number_info[2].get('max_key')
            if not max_key is None:
                max = hub.data.get(max_key)
            if max is None:
                max = number_info[2]['max']

            number = FroniusModbusNumber(
                hub.entity_prefix,
                hub,
                hub.device_info_storage,
                number_info[0],
                number_info[1],
                min = number_info[2]['min'],
                max = max,
                unit = number_info[2]['unit'],
                mode = number_info[2]['mode'],
                native_step = number_info[2]['step'],
            )
            entities.append(number)

    async_add_entities(entities)
    return True

class FroniusModbusNumber(FroniusModbusBaseEntity, NumberEntity):
    """Representation of an Battery Storage Modbus number."""

    @property
    def state(self):
        """Return the state of the sensor."""

        if self._key in self._hub.data:
            if self._key in ['grid_discharge_power','discharge_limit']:
                value = round(self._hub.data[self._key] / 100.0 * self._hub.max_discharge_rate_w,0)
            elif self._key in ['grid_charge_power','charge_limit']:
                value = round(self._hub.data[self._key] / 100.0 * self._hub.max_charge_rate_w,0)
            else:
                value = self._hub.data[self._key]    
            return value

    # @property
    # def native_value(self) -> float:
    #     if self._key in self._hub.data:
    #         _LOGGER.debug(f'native_value {self._key}')
    #         if self._key in ['grid_discharge_power','discharge_limit']:
    #             return self._hub.data[self._key]/100.0 * self._hub.max_discharge_rate_w
    #         elif self._key in ['grid_charge_power','charge_limit']:
    #             return self._hub.data[self._key]/100.0 * self._hub.max_charge_rate_w
    #         return self._hub.data[self._key]

    async def async_set_native_value(self, value: float) -> None:
        """Change the selected value."""

        if self._key == 'minimum_reserve':
            await self._hub.set_minimum_reserve(value)
        elif self._key == 'charge_limit':
            await self._hub.set_charge_limit(value)
        elif self._key == 'discharge_limit':
            await self._hub.set_discharge_limit(value)
        elif self._key == 'grid_charge_power':
            await self._hub.set_grid_charge_power(value)
        elif self._key == 'grid_discharge_power':
            await self._hub.set_grid_discharge_power(value)

        #_LOGGER.debug(f"Number {self._key} set to {value}")
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return depending on mode."""
        if self._key == 'minimum_reserve':
            return True
        if self._key == 'charge_limit' and self._hub.storage_extended_control_mode in [1,3,6]:
            return True
        if self._key == 'discharge_limit' and self._hub.storage_extended_control_mode in [2,3,7]:
            return True
        if self._key == 'grid_charge_power' and self._hub.storage_extended_control_mode in [4]:
            return True
        if self._key == 'grid_discharge_power' and self._hub.storage_extended_control_mode in [5]:
            return True
        return False
