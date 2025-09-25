"""Fronius Modbus Hub."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional
from importlib.metadata import version

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.core import HomeAssistant

from .froniusmodbusclient import FroniusModbusClient

from .const import (
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

class Hub:
    """Hub for Fronius Battery Storage Modbus Interface"""

    PYMODBUS_VERSION = '3.11.1'

    def __init__(self, hass: HomeAssistant, name: str, host: str, port: int, inverter_unit_id: int, meter_unit_ids, scan_interval: int) -> None:
        """Init hub."""
        self._hass = hass
        self._name = name

        self._id = f'{name.lower()}_{host.lower().replace('.','')}'
        self.online = True        

        self._client = FroniusModbusClient(host=host, port=port, inverter_unit_id=inverter_unit_id, meter_unit_ids=meter_unit_ids, timeout=max(3, (scan_interval - 1)))
        self._scan_interval = timedelta(seconds=scan_interval)
        self._unsub_interval_method = None
        self._entities = []
        self._entities_dict = {}
        self._busy = False

    def toggle_busy(func):
        async def wrapper(self, *args, **kwargs):
            if self._busy:
                #_LOGGER.debug(f"skip {func.__name__} hub busy") 
                return
            self._busy = True
            error = None
            try:
                result = await func(self, *args, **kwargs)
            except Exception as e:
                _LOGGER.warning(f'Exception in wrapper {e}')
                error = e
            self._busy = False
            if not error is None:
                raise error
            return result
        return wrapper

    @toggle_busy
    async def init_data(self, close = False, read_status_data = False):
        await self._hass.async_add_executor_job(self.check_pymodbus_version)  
        result = await self._client.init_data()

        if self.storage_configured:
            result : bool = await self._hass.async_add_executor_job(self._client.get_json_storage_info)                

        return

    def check_pymodbus_version(self):
        if version('pymodbus') is None:
            _LOGGER.warning(f"pymodbus not found")
        elif version('pymodbus') < self.PYMODBUS_VERSION:
            raise Exception(f"pymodbus {version('pymodbus')} found, please update to {self.PYMODBUS_VERSION} or higher")
        elif version('pymodbus') > self.PYMODBUS_VERSION:
            _LOGGER.warning(f"newer pymodbus {version('pymodbus')} found")
        _LOGGER.debug(f"pymodbus {version('pymodbus')}")      

    @property 
    def device_info_storage(self) -> dict:
        return {
            "identifiers": {(DOMAIN, f'{self._name}_battery_storage')},
            "name": f'{self._client.data.get('s_model')}',
            "manufacturer": self._client.data.get('s_manufacturer'),
            "model": self._client.data.get('s_model'),
            "serial_number": self._client.data.get('s_serial'),
        }

    @property 
    def device_info_inverter(self) -> dict:
        return {
            "identifiers": {(DOMAIN, f'{self._name}_inverter')},
            "name": f'Fronius {self._client.data.get('i_model')}',
            "manufacturer": self._client.data.get('i_manufacturer'),
            "model": self._client.data.get('i_model'),
            "serial_number": self._client.data.get('i_serial'),
            "sw_version": self._client.data.get('i_sw_version'),
            #"hw_version": f'modbus id-{self._client.data.get('i_unit_id')}',
        }
    
    def get_device_info_meter(self, id) -> dict:
         return {
            "identifiers": {(DOMAIN, f'{self._name}_meter{id}')},
            "name": f'Fronius {self._client.data.get(f'm{id}_model')} {self._client.data.get(f'm{id}_options')}',
            "manufacturer": self._client.data.get(f'm{id}_manufacturer'),
            "model": self._client.data.get(f'm{id}_model'),
            "serial_number": self._client.data.get(f'm{id}_serial'),
            "sw_version": self._client.data.get(f'm{id}_sw_version'),
            #"hw_version": f'modbus id-{self._client.data.get(f'm{id}_unit_id')}',
        }

    @property
    def hub_id(self) -> str:
        """ID for hub."""
        return self._id

    @callback
    def async_add_hub_entity(self, update_callback):
        """Listen for data updates."""
        # This is the first entity, set up interval.
        if not self._entities:
            self._unsub_interval_method = async_track_time_interval(
                self._hass, self.async_refresh_modbus_data, self._scan_interval
            )
        self._entities.append(update_callback)

    @callback
    def async_remove_hub_entity(self, update_callback):
        """Remove data update."""
        self._entities.remove(update_callback)

        if not self._entities:
            """stop the interval timer upon removal of last entity"""
            self._unsub_interval_method()
            self._unsub_interval_method = None
            self.close()

    @toggle_busy
    async def async_refresh_modbus_data(self, _now: Optional[int] = None) -> dict:
        """Time to update."""

        if not self._entities:
            return False

        try:
            update_result = await self._client.read_inverter_data()
        except Exception as e:
            _LOGGER.exception("Error reading inverter data", exc_info=True)
            update_result = False

        try:
            update_result = await self._client.read_inverter_status_data()
        except Exception as e:
            _LOGGER.exception("Error reading inverter status data", exc_info=True)
            update_result = False

        try:
            update_result = await self._client.read_inverter_model_settings_data()
        except Exception as e:
            _LOGGER.exception("Error reading inverter model settings data", exc_info=True)
            update_result = False

        try:
            update_result = await self._client.read_inverter_controls_data()
        except Exception as e:
            _LOGGER.exception("Error reading inverter model settings data", exc_info=True)
            update_result = False

        if self._client.meter_configured:
            for meter_address in self._client._meter_unit_ids:
                try:
                    update_result = await self._client.read_meter_data(meter_prefix="m1_", unit_id=meter_address)
                except Exception as e:
                    _LOGGER.error(f"Error reading meter data {meter_address}.", exc_info=True)
                    #update_result = False

        if self._client.mppt_configured:
            try:
                update_result = await self._client.read_mppt_data()
            except Exception as e:
                _LOGGER.exception("Error reading mptt data", exc_info=True)
                update_result = False
        
        if self._client.storage_configured:
            try:
                update_result = await self._client.read_inverter_storage_data()
            except Exception as e:
                _LOGGER.exception("Error reading inverter storage data", exc_info=True)
                update_result = False


        if update_result:
            for update_callback in self._entities:
                update_callback()

    @toggle_busy
    async def test_connection(self) -> bool:
        """Test connectivity"""
        try:
            return await self._client.connect()
        except Exception as e:
            _LOGGER.exception("Error connecting to inverter", exc_info=True)
            return False

    def close(self):
        """Disconnect client."""
        #with self._lock:
        self._client.close()

    @property
    def data(self):
        return self._client.data

    @property
    def meter_configured(self):
        return self._client.meter_configured

    @property
    def storage_configured(self):
        return self._client.storage_configured

    @property
    def max_discharge_rate_w(self):
        return self._client.max_discharge_rate_w

    @property
    def max_charge_rate_w(self):
        return self._client.max_charge_rate_w

    @property
    def storage_extended_control_mode(self):
        return self._client.storage_extended_control_mode

    @toggle_busy
    async def set_mode(self, mode):
        if mode == 0:
            await self._client.set_auto_mode()
        elif mode == 1:
            await self._client.set_charge_mode()
        elif mode == 2:
            await self._client.set_discharge_mode()
        elif mode == 3:
            await self._client.set_charge_discharge_mode()
        elif mode == 4:
            await self._client.set_grid_charge_mode()
        elif mode == 5:
            await self._client.set_grid_discharge_mode()
        elif mode == 6:
            await self._client.set_block_discharge_mode()
        elif mode == 7:
            await self._client.set_block_charge_mode()
        elif mode == 8:
            await self._client.set_calibrate_mode()

    @toggle_busy
    async def set_minimum_reserve(self, value):
        await self._client.set_minimum_reserve(value)

    @toggle_busy
    async def set_charge_limit(self, value):
        await self._client.set_charge_limit(value)

    @toggle_busy
    async def set_discharge_limit(self, value):
        await self._client.set_discharge_limit(value)

    @toggle_busy
    async def set_grid_charge_power(self, value):
        await self._client.set_grid_charge_power(value)
           
    @toggle_busy
    async def set_grid_discharge_power(self, value):
        await self._client.set_grid_discharge_power(value)


