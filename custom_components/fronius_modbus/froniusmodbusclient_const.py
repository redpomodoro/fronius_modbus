SUPPORTED_MANUFACTURERS = ['Fronius']
SUPPORTED_MODELS = ['Primo GEN24', 'Symo GEN24']

COMMON_ADDRESS = 40004
INVERTER_ADDRESS = 40071
NAMEPLATE_ADDRESS = 40123
MPPT_ADDRESS = 40255
METER_ADDRESS = 40071
STORAGE_ADDRESS = 40345
STORAGE_CONTROL_MODE_ADDRESS = 40348
MINIMUM_RESERVE_ADDRESS = 40350
DISCHARGE_RATE_ADDRESS = 40355
CHARGE_RATE_ADDRESS = 40356
EXPORT_LIMIT_RATE_ADDRESS = 40232
EXPORT_LIMIT_ENABLE_ADDRESS = 40236
CONN_ADDRESS = 40231

    # Manufacturer
    # Type
    # Firmware
    # Serial

STORAGE_CONTROL_MODE = {
    0: 'Auto',
    1: 'Charge',
    2: 'Discharge',
    3: 'Change and Discharge',
}

CHARGE_STATUS = {
    1: 'Off',
    2: 'Empty',
    3: 'Discharging',
    4: 'Charging',
    5: 'Full',
    6: 'Holding',
    7: 'Testing',
}

INVERTER_STATUS = {
    1: 'Off',
    2: 'Sleeping',
    3: 'Starting',
    4: 'Normal',
    5: 'Throttled',
    6: 'Shutdown',
    7: 'Fault',
    8: 'Standby',
}

INVERTER_CONTROLS = [
    'Power reduction',
    'Constant reactive power',
    'Constant power factor',
]

INVERTER_EVENTS = [
    'Error',
    'Warning',
    'Info',
]

FRONIUS_INVERTER_STATUS = {
    1: 'Off',
    2: 'Sleeping',
    3: 'Starting',
    4: 'Normal',
    5: 'Throttled',
    6: 'Shutdown',
    7: 'Fault',
    8: 'Standby',
    9: 'No solarnet',
    10: 'No inverter communication',
    11: 'Overcurrent solarnet',
    12: 'Firmware updating',
    13: 'ACFI event',
}

CHARGE_GRID_STATUS = {
    1: 'Disabled',
    2: 'Enabled',
}

GRID_STATUS = {
    0: 'Off grid',
    1: 'Off grid operating',
    2: 'On grid',
    3: 'On grid operating',
}

CONNECTION_STATUS = [ 
    'Connected',
    'Available',
    'Operating',
]

CONNECTION_STATUS_CONDENSED = {
    0: 'Disconnected',
    1: 'Connected', 
    3: 'Available', 
    7: 'Operating', 
}

ECP_CONNECTION_STATUS = {
    0: 'Disconnected',
    1: 'Connected',
}

CONTROL_STATUS = {
    0: 'Disabled',
    1: 'Enabled',
}

EXPORT_LIMIT_STATUS = {
    0: 'Disabled',
    1: 'Enabled',
}

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
