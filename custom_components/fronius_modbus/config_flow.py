from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant

from .hub import Hub
from homeassistant.const import CONF_NAME, CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from .const import (
    DOMAIN,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_INVERTER_UNIT_ID,
    DEFAULT_METER_UNIT_ID,
    CONF_INVERTER_UNIT_ID,
    CONF_METER_UNIT_ID,
    SUPPORTED_MANUFACTURERS,
    SUPPORTED_MODELS,
)

_LOGGER = logging.getLogger(__name__)

# This is the schema that used to display the UI to the user. This simple
# schema has a single required host field, but it could include a number of fields
# such as username, password etc. See other components in the HA core code for
# further examples.
# Note the input displayed to the user will be translated. See the
# translations/<lang>.json file and strings.json. See here for further information:
# https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#translations
# At the time of writing I found the translations created by the scaffold didn't
# quite work as documented and always gave me the "Lokalise key references" string
# (in square brackets), rather than the actual translated value. I did not attempt to
# figure this out or look further into it.
#DATA_SCHEMA = vol.Schema({("host"): str, ("port"): int})

DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_INVERTER_UNIT_ID, default=DEFAULT_INVERTER_UNIT_ID): int,
        vol.Optional(CONF_METER_UNIT_ID, default=DEFAULT_METER_UNIT_ID): int,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
    }
)

async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    # Validate the data can be used to set up a connection.

    if len(data[CONF_HOST]) < 3:
        raise InvalidHost
    if data[CONF_PORT] > 65535:
        raise InvalidPort
    if data[CONF_SCAN_INTERVAL] < 5:
        raise ScanIntervalTooShort
        
    meter_addresses = [data[CONF_METER_UNIT_ID]]

    all_addresses = meter_addresses + [data[CONF_INVERTER_UNIT_ID]] 

    if len(all_addresses) > len(set(all_addresses)):
        _LOGGER.error(f"Modbus addresses are not unique {all_addresses}")
        raise AddressesNotUnique

    try:
        hub = Hub(hass, data[CONF_NAME], data[CONF_HOST], data[CONF_PORT], data[CONF_INVERTER_UNIT_ID], meter_addresses, data[CONF_SCAN_INTERVAL])

        await hub.init_data()
    except Exception as e:
        # If there is an error, raise an exception to notify HA that there was a
        # problem. The UI will also show there was a problem
        _LOGGER.error(f"Cannot start hub {e}")
        raise CannotConnect

    manufacturer = hub.data.get('i_manufacturer')
    if manufacturer is None:
        _LOGGER.error(f"No manufacturer is returned")
        raise UnsupportedHardware   
    if manufacturer not in SUPPORTED_MANUFACTURERS:
        _LOGGER.error(f"Unsupported manufacturer: '{manufacturer}'")
        raise UnsupportedHardware

    model = hub.data.get('i_model')
    if model is None:
        _LOGGER.error(f"No model type is returned")
        raise UnsupportedHardware

    supported = False
    for supported_model in SUPPORTED_MODELS:
        if model.startswith(supported_model):
            supported = True
    
    if not supported:
        _LOGGER.warning(f"Untested model {model}")
        #raise UnsupportedHardware

    #result = await hub.test_connection()
    #if not result:
    #    raise CannotConnect

    # Return info that you want to store in the config entry.
    # "Title" is what is displayed to the user for this hub device
    # It is stored internally in HA as part of the device config.
    # See `async_step_user` below for how this is used
    return {"title": data[CONF_NAME]}

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow """

    VERSION = 1
    # CONNECTION_CLASS wurde in HA 2022.x entfernt; iot_class wird in manifest.json definiert.

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. This example provides a single form (built from `DATA_SCHEMA`),
        # and when that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidPort:
                errors["base"] = "invalid_port"
            except InvalidHost:
                errors["host"] = "invalid_host"
            except ScanIntervalTooShort:
                errors["base"] = "scan_interval_too_short"
            except UnsupportedHardware:
                errors["base"] = "unsupported_hardware"
            except AddressesNotUnique:
                errors["base"] = "modbus_address_conflict"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""

class InvalidPort(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""

class UnsupportedHardware(exceptions.HomeAssistantError):
    """Error to indicate there is an unsupported hardware."""

class AddressesNotUnique(exceptions.HomeAssistantError):
    """Error to indicate that the modbus addresses are not unique."""

class ScanIntervalTooShort(exceptions.HomeAssistantError):
    """Error to indicate the scan interval is too short."""    