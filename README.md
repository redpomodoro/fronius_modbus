[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)

# fronius_modbus
Home assistant Custom Component for reading data from Fronius GEN24, Verto or Tauro Inverter and connected smart meters and battery storage. This integration uses a local modbus connection. 

> [!CAUTION]
> This is a work in progress project - it is still in early development stage, so there are still breaking changes possible.
>
> This is an unofficial implementation and not supported by Fronius. It might stop working at any point in time.
> You are using this module (and it's prerequisites/dependencies) at your own risk. Not me neither any of contributors to this or any prerequired/dependency project are responsible for damage in any kind caused by this project or any of its prerequsites/dependencies.

# Installation

HACS installation
* Go to HACS
* Click on the 3 dots in the top right corner.
* Select "Custom repositories"
* Add the [URL](https://github.com/redpomodoro/fronius_modbus) to the repository.
* Select the 'integration' type.
* Click the "ADD" button.

Manual installation
Copy contents of custom_components folder to your home-assistant config/custom_components folder.
After reboot of Home-Assistant, this integration can be configured through the integration setup UI.

Make sure modbus is enabled on the inverter. You can check by going into the web interface of the inverter and go to:
"Communication" -> "Modbus"

And turn on:
- "Con­trol sec­ond­ary in­ver­t­er via Mod­bus TCP"
- "Allow control"
- Make sure that under 'SunSpec Model Type' has 'int + SF' selected. 

![modbus settings](images/modbus_settings.png?raw=true "modbus")


> [!IMPORTANT]
> Turn off scheduled (dis)charging in the web UI to avoid unexpected behavior.

> [!IMPORTANT]
> When using multiple integrations that use pymodbus package it can lead to version conflicts as they will share 1 package in HA. This can be fixed by removing ALL integrations using pymodbus and modbus configuratio.yaml (for the build in integration into HA), rebooting HA and then reinstalling the integrations and the modbus configuration yaml.

> [!IMPORTANT]
> Update your GEN24 inverter firmware to 1.34.6-1 or higher otherwise battery charging might be limited.

# Usage

### Battery Storage

### Controls
| Entity  | Description |
| --- | --- |
| Load Discharge Limit | Maximum load discharging power in watts of which the battery can be discharged by. |
| Grid Charge Power | The charging power in watts when the storage is being charged from the grid. Note that grid charging seems to be limited to an effective 50% by the hardware. |
| Grid Discharge Power | The discharging power in watts when the storage is being discharged to the grid. |
| Minimum Reserve | The minimum reserve for storage when discharging. Note that the storage will charge from the grid with 0.5kW if SOC falls below this level. Called 'Reserve Capacity' in Fronius Web UI. |
| PV Charge Limit | Maximum PV charging power in watts of which the battery can be charged by. |
| Charge Rate Setpoint | Direct hardware setpoint for the maximum charge rate of the battery. Advanced control that bypasses mode logic. |
| Discharge Rate Setpoint | Direct hardware setpoint for the maximum discharge rate of the battery. Advanced control that bypasses mode logic. |

### Storage Control Modes
| Mode  | Description |
| --- | --- |
| Auto  | The storage will allow charging and discharging up to the minimum reserve. |
| PV Charge Limit | The storage can be charged with PV power at a limited rate. Limit will be set to maximum power after change.  |
| Load Discharge Limit | The storage can be discharged into the load at a limited rate. Limit will be set to maximum power after change. |
| PV Charge and Load Discharge Limit | Allows setting both PV charge and load discharge limits. Limits will be set to maximum power after change. |
| Charge from Grid | The storage will be charged from the grid using the charge rate from 'Storage Grid Charge Power'. Power will be set 0 after change. |
| Discharge to Grid | The storage will discharge to the grid using the discharge rate from 'Storage Grid Discharge Power'. Power will be set 0 after change. |
| Block discharging | The storage can only be charged with PV power. Charge limit will be set to maximum power. |
| Block charging | The storage can only be discharged and won't be charged with PV power. Discharge limit will be set to maximum power. |

Note to change the mode first then set controls active in that mode.

### Controls used by Modes
| Mode | PV Charge Limit | Load Discharge Limit | Grid Charge Power | Grid Discharge Power | Minimum Reserve | 
| --- | --- | --- | --- | --- | --- |
| Auto | Ignored (100%) | Ignored (100%) | Ignored (0%) | Ignored (0%) | Used | 
| PV Charge Limit | Used | Ignored (100%) | Ignored (0%) | Ignored (0%) | Used |
| Load Discharge Limit  | Ignored (100%) | Used | Ignored (0%) | Ignored (0%) | Used |
| PV Charge and Load Discharge Limit  | Used | Used | Ignored (0%) | Ignored (0%) | Used |
| Charge from Grid | Ignored | Ignored | Used | Ignored (0%) | Used |
| Discharge to Grid | Ignored | Ignored | Ignored (0%) | Used | Used |
| Block discharging | Used | Ignored (0%) | Ignored (0%) | Ignored (0%) | Used |
| Block charging | Ignored (0%) | Used | Ignored (0%) | Ignored (0%) | Used |

### Fronius Web UI mapping
| Web UI name | Integration Control | Integration Mode |
| --- | --- | --- |
| Max. charging power | PV Charge Limit | PV Charge Limit |
| Min. charging power | Grid Charge Power | Charge from Grid |
| Max. discharging power | Load Discharge Limit | Load Discharge Limit |
| Min. discharging power | Grid Discharge Power | Discharge to Grid | 

### Battery Storage Sensors
| Entity  | Description |
| --- | --- |
| Charge Status | Holding / Charging / Discharging |
| Minimum Reserve | This is minium level to which the battery can be discharged and will be charged from the grid if falls below. Called 'Reserve Capacity' in Web UI. |
| State of Charge | The current battery level |

### Diagnostic
| Entity  | Description |
| --- | --- |
To come!


### Inverter Sensors
| Entity  | Description |
| --- | --- |
| Load | The current total power consumption which is derived by adding up the meter AC power and inverter AC power. |
| MPPT{x} power | The current power generated by MPPT module {x} in watts. Generated dynamically based on the hardware configuration. |
| MPPT{x} lifetime energy | The total lifetime energy generated by MPPT module {x} in Wh. Generated dynamically based on the hardware configuration. |


### Inverter Diagnostics
| Entity  | Description |
| --- | --- |
| Grid status | Grid status based on meter and inverter frequency. If inverter frequency is 53hz it is running in off grid mode and normally in 50hz. When the inverter is sleeping the meter frequency is checked for connection. |

### Smart Meters
The integration dynamically detects and exposes all configured smart meters up to the limit configured in your inverter. Each meter will have its own individual entity prefixed with `m{id}_` (e.g. `m1_`, `m2_`) and supports models 201, 202, 203, and 204.


# Example Devices (Outdated screenshots!)

Battery Storage
![battery storage](images/example_batterystorage0.png?raw=true "storage")

Battery Storage Actions
![battery storage actions](images/example_batterystorage.png?raw=true "storage actions")

Smart Meter
![smart meter](images/example_meter.png?raw=true "meter")

Inverter 
![smart meter](images/example_inverter.png?raw=true "inverter")


# References
- https://www.fronius.com/~/downloads/Solar%20Energy/Operating%20Instructions/42,0410,2649.pdf
- https://github.com/binsentsu/home-assistant-solaredge-modbus/
- https://github.com/bigramonk/byd_charging
