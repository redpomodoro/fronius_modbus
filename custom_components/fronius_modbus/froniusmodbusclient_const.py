# Sunspec starting address
SUNSPEC_START_ADDRESS = 40000

# Sunspec model IDs
SUNSPEC_COMMON_MODEL = 1
SUNSPEC_INVERTER_MODEL_101 = 101
SUNSPEC_INVERTER_MODEL_103 = 103
SUNSPEC_NAMEPLATE_MODEL = 120
SUNSPEC_SETTINGS_MODEL = 121
SUNSPEC_STATUS_MODEL = 122
SUNSPEC_CONTROLS_MODEL = 123
SUNSPEC_STORAGE_MODEL = 124
SUNSPEC_MPPT_MODEL = 160
SUNSPEC_METER_MODEL_201 = 201
SUNSPEC_METER_MODEL_202 = 202
SUNSPEC_METER_MODEL_203 = 203
SUNSPEC_METER_MODEL_204 = 204
SUNSPEC_END_MODEL = 65535

# MPPT model offsets
MPPT_HEADER_LENGTH = 8
MPPT_MODULE_LENGTH = 20

# Storage model write offsets
STORAGE_CONTROL_MODE_OFFSET = 3
MINIMUM_RESERVE_OFFSET = 5
DISCHARGE_RATE_OFFSET = 10
CHARGE_RATE_OFFSET = 11

# Dictionaries
STORAGE_CONTROL_MODE = {
    0: 'Auto',
    1: 'Charge',
    2: 'Discharge',
    3: 'Charge and Discharge',
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

STORAGE_EXT_CONTROL_MODE = {
    0: 'Auto',
    1: 'PV Charge Limit',
    2: 'Load Discharge Limit',
    3: 'PV Charge and Load Discharge Limit',
    4: 'Charge from Grid',
    5: 'Discharge to Grid',
    6: 'Block Discharging',
    7: 'Block Charging',
}
