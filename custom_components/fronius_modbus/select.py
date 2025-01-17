import logging
from typing import Optional, Dict, Any

from .const import (
    STORAGE_SELECT_TYPES,
    ENTITY_PREFIX,
)

from homeassistant.core import callback
from homeassistant.const import CONF_NAME
from homeassistant.components.select import (
    SelectEntity,
)

from .hub import Hub
from .base import FroniusModbusBaseEntity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities) -> None:
    hub:Hub = config_entry.runtime_data

    entities = []

    if hub.storage_configured:

        for select_info in STORAGE_SELECT_TYPES:
            select = FroniusModbusSelect(
                platform_name=ENTITY_PREFIX,
                hub=hub,
                device_info=hub.device_info_storage,
                name = select_info[0],
                key = select_info[1],
                options = select_info[2],
            )
            entities.append(select)

    async_add_entities(entities)
    return True

def get_key(my_dict, search):
    for k, v in my_dict.items():
        if v == search:
            return k
    return None

class FroniusModbusSelect(FroniusModbusBaseEntity, SelectEntity):
    """Representation of an Battery Storage select."""

    @property
    def current_option(self) -> str:
        if self._key in self._hub.data:
            return self._hub.data[self._key]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        new_mode = get_key(self._options_dict, option)
        if new_mode == 0:
            self._hub.set_auto_mode()
        elif new_mode == 1:
            self._hub.set_charge_mode()
        elif new_mode == 2:
            self._hub.set_discharge_mode()
        elif new_mode == 3:
            self._hub.set_charge_discharge_mode()
        elif new_mode == 4:
            self._hub.set_grid_charge_mode()
        elif new_mode == 5:
            self._hub.set_grid_discharge_mode()
        elif new_mode == 6:
            self._hub.set_block_discharge_mode()
        elif new_mode == 7:
            self._hub.set_block_charge_mode()
        elif new_mode == 8:
            self._hub.set_calibrate_mode()

        self._hub.data[self._key] = option
        self._hub.storage_extended_control_mode = new_mode
        self.async_write_ha_state()