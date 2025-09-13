from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory

DOMAIN = 'fronius_modbus'
CONNECTION_MODBUS = 'modbus'
DEFAULT_NAME = 'Fronius'
ENTITY_PREFIX = 'fm'
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_PORT = 502
DEFAULT_INVERTER_UNIT_ID = 1
DEFAULT_METER_UNIT_ID = 200
CONF_INVERTER_UNIT_ID = 'inverter_modbus_unit_id'
CONF_METER_UNIT_ID = 'meter_modbus_unit_id'
ATTR_MANUFACTURER = 'Fronius'
SUPPORTED_MANUFACTURERS = ['Fronius']
SUPPORTED_MODELS = ['Primo GEN24', 'Symo GEN24']

STORAGE_EXT_CONTROL_MODE = {
    0: 'Auto',
    1: 'PV Charge Limit',
    2: 'Discharge Limit',
    3: 'PV Charge and Discharge Limit',
    4: 'Charge from Grid',
    5: 'Discharge to Grid',
    6: 'Block Discharging',
    7: 'Block Charging',
#    8: 'Calibrate',
}

STORAGE_SELECT_TYPES = [
    ['Storage Control Mode', 'ext_control_mode', STORAGE_EXT_CONTROL_MODE],
]

STORAGE_NUMBER_TYPES = [
    ['Grid discharge power', 'grid_discharge_power', {'min': 0, 'max': 10100, 'step': 10, 'mode':'box', 'unit': 'W', 'max_key': 'MaxDisChaRte'}],
    ['Grid charge power', 'grid_charge_power', {'min': 0, 'max': 10100, 'step': 10, 'mode':'box', 'unit': 'W', 'max_key': 'MaxChaRte'}],
    ['Discharge limit', 'discharge_limit',  {'min': 0, 'max': 10100, 'step': 10, 'mode':'box', 'unit': 'W', 'max_key': 'MaxDisChaRte'}],
    ['PV charge limit', 'charge_limit', {'min': 0, 'max': 10100, 'step': 10, 'mode':'box', 'unit': 'W', 'max_key': 'MaxChaRte'}],
    ['Minimum reserve', 'minimum_reserve', {'min': 5, 'max': 100, 'step': 1, 'mode':'box', 'unit': '%'}],
#    ['Reserve Target', 'reserve_target', {'min': 0, 'max': 100, 'unit': '%'}],
]

INVERTER_SENSOR_TYPES = {
    'acpower': ['AC power', 'acpower', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:lightning-bolt', None],
    'acenergy': ['AC energy', 'acenergy', SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, 'Wh', 'mdi:lightning-bolt', None],
    'tempcab': ['Temperature', 'tempcab', SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, '°C', 'mdi:thermometer', None],
    'mppt1_power': ['MPPT1 power', 'mppt1_power', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:solar-power', None],
    'mppt2_power': ['MPPT2 power', 'mppt2_power', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:solar-power', None],
    'pv_power': ['PV power', 'pv_power', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:solar-power', None],
    'mppt1_lfte': ['MPPT1 lifetime energy', 'mppt1_lfte', SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, 'Wh', 'mdi:solar-panel', None],
    'mppt2_lfte': ['MPPT2 lifetime energy', 'mppt2_lfte', SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, 'Wh', 'mdi:solar-panel', None],
    'load': ['Load', 'load', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:lightning-bolt', None],
    'pv_connection': ['PV connection', 'pv_connection', None, None, None, None, EntityCategory.DIAGNOSTIC],
    'ecp_connection': ['Electrical connection', 'ecp_connection', None, None, None, None, EntityCategory.DIAGNOSTIC],
    #'status': ['Status Base', 'status', None, None, None, None, None],
    'statusvendor': ['Status', 'statusvendor', None, None, None, None, EntityCategory.DIAGNOSTIC],
    'line_frequency': ['Line frequency', 'line_frequency', SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, 'Hz', None, None],
    'inverter_controls': ['Control mode', 'inverter_controls', None, None, None, None, EntityCategory.DIAGNOSTIC],
    #'vref': ['Reference Voltage', 'vref', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    #'vrefofs': ['Reference Voltage offset', 'vrefofs', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'max_power': ['Maximum power', 'max_power', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:lightning-bolt', None],
    #'events1': ['Events Customer', 'events1', None, None, None, None, EntityCategory.DIAGNOSTIC],    
    'events2': ['Events', 'events2', None, None, None, None, EntityCategory.DIAGNOSTIC],    

    'grid_status': ['Grid status', 'grid_status', None, None, None, None, EntityCategory.DIAGNOSTIC],

    'Conn': ['Connection control', 'Conn', None, None, None, None, EntityCategory.DIAGNOSTIC],
    'WMaxLim_Ena': ['Throttle control', 'WMaxLim_Ena', None, None, None, None, EntityCategory.DIAGNOSTIC],
    'OutPFSet_Ena': ['Fixed power factor', 'OutPFSet_Ena', None, None, None, None, EntityCategory.DIAGNOSTIC],
    'VArPct_Ena': ['Limit VAr control', 'VArPct_Ena', None, None, None, None, EntityCategory.DIAGNOSTIC],
    'PhVphA': ['AC voltage L1-N', 'PhVphA', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'unit_id': ['Modbus ID', 'i_unit_id', None, None, None, None, EntityCategory.DIAGNOSTIC],    
}

INVERTER_SYMO_SENSOR_TYPES = {
    'PhVphB': ['AC voltage L2-N', 'PhVphB', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'PhVphC': ['AC voltage L3-N', 'PhVphC', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'PPVphAB': ['AC voltage L1-L2', 'PPVphAB', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'PPVphBC': ['AC voltage L2-L3', 'PPVphBC', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'PPVphCA': ['AC voltage L3-L1', 'PPVphCA', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
}

INVERTER_STORAGE_SENSOR_TYPES = {
    'mppt3_power': ['Storage charging power', 'mppt3_power', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:home-battery', None],
    'mppt4_power': ['Storage discharging power', 'mppt4_power', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:home-battery', None],
    'storage_connection': ['Storage connection', 'storage_connection', None, None, None, None, EntityCategory.DIAGNOSTIC],
    'storage_power': ['Storage power', 'storage_power', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:home-battery', None],
    'mppt3_lfte': ['Storage charging lifetime energy', 'mppt3_lfte', SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, 'Wh', 'mdi:home-battery', None],
    'mppt4_lfte': ['Storage discharging lifetime energy', 'mppt4_lfte', SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, 'Wh', 'mdi:home-battery', None],
}


METER_SENSOR_TYPES = {
    'power': ['Power', 'power', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:lightning-bolt', None],
    'exported': ['Exported', 'exported', SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, 'Wh', 'mdi:lightning-bolt', None],
    'imported': ['Imported', 'imported', SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, 'Wh', 'mdi:lightning-bolt', None],
    'line_frequency': ['Line frequency', 'line_frequency', SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, 'Hz', None, None],
    'PhVphA': ['AC voltage L1-N', 'PhVphA', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'PhVphB': ['AC voltage L2-N', 'PhVphB', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'PhVphC': ['AC voltage L3-N', 'PhVphC', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'PPV': ['AC voltage Line to Line', 'PPV', SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 'V', 'mdi:lightning-bolt', None],
    'unit_id': ['Modbus ID', 'unit_id', None, None, None, None, EntityCategory.DIAGNOSTIC],
}

STORAGE_SENSOR_TYPES = {
    'control_mode': ['Core storage control mode', 'control_mode', None, None, None, None, EntityCategory.DIAGNOSTIC],
    'charge_status': ['Charge status', 'charge_status', None, None, None, None, None, EntityCategory.DIAGNOSTIC],
    'max_charge': ['Max charging power', 'max_charge', SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', 'mdi:gauge', EntityCategory.DIAGNOSTIC],
    'soc': ['State of charge', 'soc', SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT, '%', None, None],
    'charging_power': ['Charging power', 'charging_power',  None, None, '%', 'mdi:gauge', EntityCategory.DIAGNOSTIC],
    'discharging_power': ['Discharging power', 'discharging_power',  None, None, '%', 'mdi:gauge', EntityCategory.DIAGNOSTIC],
    'minimum_reserve': ['Minimum reserve', 'minimum_reserve',  None, None, '%', 'mdi:gauge', None],
    'grid_charging': ['Grid charging', 'grid_charging',  None, None, None, None, EntityCategory.DIAGNOSTIC],
    'WHRtg': ['Capacity', 'WHRtg',  SensorDeviceClass.ENERGY, SensorStateClass.MEASUREMENT, 'Wh', None, EntityCategory.DIAGNOSTIC],
    'MaxChaRte': ['Maximum charge rate', 'MaxChaRte',  SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', None, EntityCategory.DIAGNOSTIC],
    'MaxDisChaRte': ['Maximum discharge rate', 'MaxDisChaRte',  SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 'W', None, EntityCategory.DIAGNOSTIC],
    #'WChaGra': ['Setpoint for maximum charge', 'WChaGra', None, None, None, None, EntityCategory.DIAGNOSTIC],
    #'WDisChaGra': ['Setpoint for maximum discharge', 'WDisChaGra', None, None, None, None, EntityCategory.DIAGNOSTIC],
}
