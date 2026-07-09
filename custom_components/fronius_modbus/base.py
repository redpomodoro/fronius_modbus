import logging
from homeassistant.core import callback
from .hub import Hub

_LOGGER = logging.getLogger(__name__)

class FroniusModbusBaseEntity():
    """ """
    _key = None
    _options_dict = None

    def __init__(self, platform_name, hub, device_info, name, key, device_class=None, state_class=None, unit=None, icon=None, entity_category=None, options=None, min=None, max=None, native_step=None, mode=None):
        self._platform_name = platform_name
        self._hub:Hub = hub
        self._key = key
        self._name = name
        self._unit_of_measurement = unit
        self._icon = icon
        self._device_info = device_info
        if not device_class is None:
            self._attr_device_class = device_class
        if not state_class is None:
            self._attr_state_class = state_class
        if not entity_category is None:
            self._attr_entity_category = entity_category
        if not options is None:
            self._options_dict = options
            self._attr_options = list(options.values())
        if not min is None:
            self._attr_native_min_value = min
        if not max is None:
            self._attr_native_max_value = max
        if not native_step is None:
            self._attr_native_step = native_step
        if not mode is None:
            self._attr_mode = mode

        self._attr_has_entity_name = True
        self._attr_name = name
        self._attr_unique_id = f"{self._platform_name}_{self._hub._name}_{self._key}"
        self._attr_device_info = device_info

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._hub.async_add_hub_entity(self._modbus_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._hub.async_remove_hub_entity(self._modbus_data_updated)

    @callback
    def _modbus_data_updated(self):
        self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        """Data is delivered by the hub"""
        return False

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Return the sensor icon."""
        return self._icon

  