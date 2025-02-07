"""Fronius Modbus Hub."""
from __future__ import annotations

import requests
import threading
import logging
import operator
import threading
from datetime import timedelta
from typing import Optional

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.core import HomeAssistant

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusIOException

from .const import (
    DOMAIN,
    INVERTER_ADDRESS,
    MPPT_ADDRESS,
    COMMON_ADDRESS,
    NAMEPLATE_ADDRESS,
    STORAGE_ADDRESS,
    METER_ADDRESS,
    STORAGE_CONTROL_MODE_ADDRESS,
    MINIMUM_RESERVE_ADDRESS,
    DISCHARGE_RATE_ADDRESS,
    CHARGE_RATE_ADDRESS,    
    STORAGE_CONTROL_MODE,
    CHARGE_STATUS,
    CHARGE_GRID_STATUS,
    STORAGE_EXT_CONTROL_MODE,
    INVERTER_STATUS,
    FRONIUS_INVERTER_STATUS,
    CONNECTION_STATUS,
    CONNECTION_STATUS_CONDENSED,
    ECP_CONNECTION_STATUS,
    INVERTER_CONTROLS,
    INVERTER_EVENTS,
    CONTROL_STATUS,
    GRID_STATUS,
)

_LOGGER = logging.getLogger(__name__)

class Hub:
    """Hub for Fronius Battery Storage Modbus Interface"""

    manufacturer = "Fronius"

    def __init__(self, hass: HomeAssistant, name: str, host: str, port: int, inverter_unit_id: int, meter_unit_ids, scan_interval: int) -> None:
        """Init hub."""
        self._host = host
        self._port = port
        self._hass = hass
        self._name = name
        self._inverter_unit_id = inverter_unit_id
        self._meter_unit_ids = meter_unit_ids
        self._lock = threading.Lock()
        self._id = f'{name.lower()}_{host.lower().replace('.','')}'
        self.online = True        
        self._client = ModbusTcpClient(host=host, port=port, timeout=max(3, (scan_interval - 1)))
        self._scan_interval = timedelta(seconds=scan_interval)
        self._unsub_interval_method = None
        self._entities = []
        self._entities_dict = {}
        self.data = {}
        #self.data['reserve_target'] = 30
        self.meter_configured = False
        self.mppt_configured = False
        self.storage_configured = False
        self.storage_extended_control_mode = 0
        self.max_charge_rate_w = 11000
        self.max_discharge_rate_w = 11000

    async def init_data(self):
        try: 
            result = self.read_device_info_data(prefix='i_', unit_id=self._inverter_unit_id)
        except Exception as e:
            _LOGGER.error(f"Error reading inverter info {self._host}:{self._port} unit id: {self._inverter_unit_id}", exc_info=True)
            raise Exception(f"Error reading inverter info unit id: {self._inverter_unit_id}")
        if result == False:
            _LOGGER.error(f"Empty inverter info {self._host}:{self._port} unit id: {self._inverter_unit_id}")
            raise Exception(f"Empty inverter info unit id: {self._inverter_unit_id}")

        try:
            if self.read_mppt_data():
                self.mppt_configured = True
        except Exception as e:
            _LOGGER.warning(f"No mppt found")

        i = 1
        if len(self._meter_unit_ids)>5:
            _LOGGER.error(f"Too many meters configured, max 5")
            return
        elif len(self._meter_unit_ids)>0:
            self.meter_configured = True

        for unit_id in self._meter_unit_ids:
            try:
                self.read_device_info_data(prefix=f'm{i}_', unit_id=unit_id)
            except Exception as e:
                _LOGGER.info(f"Error reading meter info unit id: {unit_id}", exc_info=True)
            i += 1

        if self.read_inverter_nameplate_data() == False:
            _LOGGER.error(f"Error reading nameplate data", exc_info=True)

        if self.storage_configured:
            result : bool = await self._hass.async_add_executor_job(self.get_json_storage_info)                

        _LOGGER.debug(f"Init done. data: {self.data}")

        return True

    @property 
    def device_info_storage(self) -> dict:
        return {
            "identifiers": {(DOMAIN, f'{self._name}_battery_storage')},
            "name": f'Battery Storage {self.data.get('s_model')}',
            "manufacturer": self.data.get('s_manufacturer'),
            "model": self.data.get('s_model'),
            "serial_number": self.data.get('s_serial'),
        }

    @property 
    def device_info_inverter(self) -> dict:
        return {
            "identifiers": {(DOMAIN, f'{self._name}_inverter')},
            "name": f'Fronius Inverter {self.data.get('i_model')}',
            "manufacturer": self.data.get('i_manufacturer'),
            "model": self.data.get('i_model'),
            "serial_number": self.data.get('i_serial'),
            "sw_version": self.data.get('i_sw_version'),
            #"hw_version": f'modbus id-{self.data.get('i_unit_id')}',
        }
    
    def get_device_info_meter(self, id) -> dict:
         return {
            "identifiers": {(DOMAIN, f'{self._name}_meter{id}')},
            "name": f'Fronius Meter {id} {self.data.get(f'm{id}_options')}',
            "manufacturer": self.data.get(f'm{id}_manufacturer'),
            "model": self.data.get(f'm{id}_model'),
            "serial_number": self.data.get(f'm{id}_serial'),
            "sw_version": self.data.get(f'm{id}_sw_version'),
            #"hw_version": f'modbus id-{self.data.get(f'm{id}_unit_id')}',
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
            # self.connect()
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

    async def async_refresh_modbus_data(self, _now: Optional[int] = None) -> dict:
        """Time to update."""
        result : bool = await self._hass.async_add_executor_job(self._refresh_modbus_data)
        if result:
            for update_callback in self._entities:
                update_callback()

    def validate(self, value, comparison, against):
        ops = {
            ">": operator.gt,
            "<": operator.lt,
            ">=": operator.ge,
            "<=": operator.le,
            "==": operator.eq,
            "!=": operator.ne,
        }
        if not ops[comparison](value, against):
            raise ValueError(f"Value {value} failed validation ({comparison}{against})")
        return value

    def get_json_storage_info(self):
        self.data['s_manufacturer'] = None
        self.data['s_model'] = None
        self.data['s_serial'] = None

        url = f"http://{self._host}/solar_api/v1/GetStorageRealtimeData.cgi"

        try:
            response = requests.get(url)

            if response.status_code == 200:
                data = response.json()
            else:
                _LOGGER.error(f"Error storage json data {response.status_code}")
                return

            try:
                bodydata = data['Body']['Data']
            except Exception as e:
                _LOGGER.error(f"Error no body data in json data: {data}")
                return
            
            for c in bodydata.keys():
                try:
                    details = bodydata[c]['Controller']['Details']
                except Exception as e:
                    _LOGGER.error(f"Error no details in json bodydata: {bodydata}")
                    return

                self.data['s_manufacturer'] = details['Manufacturer']
                self.data['s_model'] = details['Model']
                self.data['s_serial'] = str(details['Serial']).strip()
                break
 
        except Exception as e:
            _LOGGER.error(f"Error storage json data {url} {e}", exc_info=True)

    def _refresh_modbus_data(self, _now: Optional[int] = None) -> bool:
        """Time to update."""
        if not self._entities:
            return False

        if not self._check_and_reconnect():
            #if not connected, skip
            return False

        try:
            update_result = self.read_inverter_data()
        except Exception as e:
            _LOGGER.exception("Error reading inverter data", exc_info=True)
            update_result = False

        try:
            update_result = self.read_inverter_status_data()
        except Exception as e:
            _LOGGER.exception("Error reading inverter status data", exc_info=True)
            update_result = False

        try:
            update_result = self.read_inverter_model_settings_data()
        except Exception as e:
            _LOGGER.exception("Error reading inverter model settings data", exc_info=True)
            update_result = False

        try:
            update_result = self.read_inverter_controls_data()
        except Exception as e:
            _LOGGER.exception("Error reading inverter model settings data", exc_info=True)
            update_result = False

        if self.meter_configured:
            for meter_address in self._meter_unit_ids:
                try:
                    update_result = self.read_meter_data(meter_prefix="m1_", unit_id=meter_address)
                except Exception as e:
                    _LOGGER.error(f"Error reading meter data {meter_address}.", exc_info=True)
                    #update_result = False

        if self.mppt_configured:
            try:
                update_result = self.read_mppt_data()
            except Exception as e:
                _LOGGER.exception("Error reading mptt data", exc_info=True)
                update_result = False
        
        if self.storage_configured:
            try:
                update_result = self.read_inverter_storage_data()
            except Exception as e:
                _LOGGER.exception("Error reading inverter storage data", exc_info=True)
                update_result = False

        return update_result

    async def test_connection(self) -> bool:
        """Test connectivity"""
        try:
            return self.connect()
        except Exception as e:
            _LOGGER.exception("Error connecting to inverter", exc_info=True)
            return False

    def close(self):
        """Disconnect client."""
        with self._lock:
            self._client.close()

    def _check_and_reconnect(self):
        if not self._client.connected:
            _LOGGER.info("modbus client is not connected, trying to reconnect")
            return self.connect()

        return self._client.connected

    def connect(self):
        """Connect client."""
        result = False
        with self._lock:
            result = self._client.connect()

        if result:
            _LOGGER.info("successfully connected to %s:%s",
                            self._client.comm_params.host, self._client.comm_params.port)
        else:
            _LOGGER.warning("not able to connect to %s:%s",
                            self._client.comm_params.host, self._client.comm_params.port)
        return result

    def read_holding_registers(self, unit_id, address, count):
        """Read holding registers."""
        _LOGGER.debug(f"read registers a: {address} s: {unit_id} c {count}")
        with self._lock:
            return self._client.read_holding_registers(
                address=address, count=count, slave=unit_id
            )

    def get_registers(self, unit_id, address, count, retries = 0):
        data = self.read_holding_registers( unit_id=unit_id, address=address, count=count)
        if data.isError():
            if isinstance(data,ModbusIOException):
                if retries < 1:
                    _LOGGER.debug(f"IO Error: {data}. Retrying...")
                    return self.get_registers(address=address, count=count, retries = retries + 1)
                else:
                    _LOGGER.error(f"error reading register: {address} count: {count} unit id: {self._unit_id} error: {data} ")
            else:
                _LOGGER.error(f"error reading register: {address} count: {count} unit id: {self._unit_id} error: {data} ")
            return None
        return data.registers
    
    def write_registers(self, unit_id, address, payload):
        """Write registers."""
        _LOGGER.debug(f"write registers a: {address} p: {payload}")
        with self._lock:
            return self._client.write_registers(
                address=address, values=payload, slave=unit_id
            )

    def bitmask_to_string(self, bitmask, bitmask_list, default='NA', max_length=255, bits=16):
        strings = []
        len_list = len(bitmask_list)
        for bit in range(bits):
            if bitmask & (1<<bit):
                if bit < len_list: 
                    value = bitmask_list[bit]
                else:
                    value = f'bit {bit} undefined'
                strings.append(value)

        if len(strings):
            return ','.join(strings)[:max_length]
        return default

    def calculate_value(self, value, sf, digits=2):
        if self.is_numeric(value) and self.is_numeric(sf):
            return round(value * 10**sf, digits)
        else:
            _LOGGER.debug(f'cannot calculate non numeric value: {value} sf: {sf} digits {digits}', exc_info=True)
        return None

    def strip_escapes(self, value:str):
        if value is None:
            return
        filter = ''.join([chr(i) for i in range(0, 32)])
        return value.translate(str.maketrans('', '', filter)).strip()
    
    def get_string_from_registers(self, regs):
        return self.strip_escapes(self._client.convert_from_registers(regs, data_type = self._client.DATATYPE.STRING))

    def read_device_info_data(self, prefix, unit_id):
        regs = self.get_registers(unit_id=unit_id, address=COMMON_ADDRESS, count=65)
        if regs is None:
            return False

        manufacturer = self.get_string_from_registers(regs[0:16])
        model = self.get_string_from_registers(regs[16:32])
        options = self.get_string_from_registers(regs[32:40])
        sw_version = self.get_string_from_registers(regs[40:48])
        serial =  self.get_string_from_registers(regs[48:64])
        modbus_id = self._client.convert_from_registers(regs[64:65], data_type = self._client.DATATYPE.UINT16)

        self.data[prefix + 'manufacturer'] = manufacturer
        self.data[prefix + 'model'] = model
        self.data[prefix + 'options'] = options
        self.data[prefix + 'sw_version'] = sw_version
        self.data[prefix + 'serial'] = serial
        self.data[prefix + 'unit_id'] = modbus_id

        return True

    def read_inverter_data(self):
        regs = self.get_registers(unit_id=self._inverter_unit_id, address=INVERTER_ADDRESS, count=50)
        if regs is None:
            return False

        PPVphAB = self._client.convert_from_registers(regs[5:6], data_type = self._client.DATATYPE.UINT16)
        PPVphBC = self._client.convert_from_registers(regs[6:7], data_type = self._client.DATATYPE.UINT16)
        PPVphCA = self._client.convert_from_registers(regs[7:8], data_type = self._client.DATATYPE.UINT16)
        PhVphA = self._client.convert_from_registers(regs[8:9], data_type = self._client.DATATYPE.UINT16)
        PhVphB = self._client.convert_from_registers(regs[9:10], data_type = self._client.DATATYPE.UINT16)
        PhVphC = self._client.convert_from_registers(regs[10:11], data_type = self._client.DATATYPE.UINT16)
        V_SF = self._client.convert_from_registers(regs[11:12], data_type = self._client.DATATYPE.INT16)

        W = self._client.convert_from_registers(regs[12:13], data_type = self._client.DATATYPE.INT16)
        W_SF = self._client.convert_from_registers(regs[13:14], data_type = self._client.DATATYPE.INT16)
        Hz = self._client.convert_from_registers(regs[14:15], data_type = self._client.DATATYPE.INT16)
        Hz_SF = self._client.convert_from_registers(regs[15:16], data_type = self._client.DATATYPE.INT16)

        WH = self._client.convert_from_registers(regs[22:24], data_type = self._client.DATATYPE.UINT32)
        WH_SF = self._client.convert_from_registers(regs[24:25], data_type = self._client.DATATYPE.INT16)

        TmpCab = self._client.convert_from_registers(regs[31:32], data_type = self._client.DATATYPE.INT16)
        Tmp_SF = self._client.convert_from_registers(regs[35:36], data_type = self._client.DATATYPE.INT16)
        #St = self._client.convert_from_registers(regs[36:37], data_type = self._client.DATATYPE.UINT16)
        StVnd = self._client.convert_from_registers(regs[37:38], data_type = self._client.DATATYPE.UINT16)
        #EvtVnd1 = self._client.convert_from_registers(regs[42:44], data_type = self._client.DATATYPE.UINT32)
        EvtVnd2 = self._client.convert_from_registers(regs[44:46], data_type = self._client.DATATYPE.UINT32)

        self.data['PPVphAB'] = self.calculate_value(PPVphAB, V_SF)
        self.data['PPVphBC'] = self.calculate_value(PPVphBC, V_SF)
        self.data['PPVphCA'] = self.calculate_value(PPVphCA, V_SF)
        self.data['PhVphA'] = self.calculate_value(PhVphA, V_SF)
        self.data['PhVphB'] = self.calculate_value(PhVphB, V_SF)
        self.data['PhVphC'] = self.calculate_value(PhVphC, V_SF)
        self.data['tempcab'] = self.calculate_value(TmpCab, Tmp_SF)
        self.data["acpower"] = self.calculate_value(W, W_SF)
        self.data["line_frequency"] = self.calculate_value(Hz, Hz_SF)
        self.data["acenergy"] = self.calculate_value(WH, WH_SF) 
        #self.data["status"] = INVERTER_STATUS[St]
        self.data["statusvendor"] = FRONIUS_INVERTER_STATUS[StVnd]
        self.data["statusvendor_id"] = StVnd
        #self.data["events1"] = self.bitmask_to_string(EvtVnd1,INVERTER_EVENTS,default='None',bits=32)  
        self.data["events2"] = self.bitmask_to_string(EvtVnd2,INVERTER_EVENTS,default='None',bits=32)  

        return True

    def read_inverter_nameplate_data(self):
        """start reading storage data"""
        regs = self.get_registers(unit_id=self._inverter_unit_id, address=NAMEPLATE_ADDRESS, count=120)
        if regs is None:
            return False

        # DERTyp: Type of DER device. Default value is 4 to indicate PV device.
        DERTyp = self._client.convert_from_registers(regs[0:1], data_type = self._client.DATATYPE.UINT16)
        # WHRtg: Nominal energy rating of storage device.
        WHRtg = self._client.convert_from_registers(regs[17:18], data_type = self._client.DATATYPE.UINT16)
        # MaxChaRte: Maximum rate of energy transfer into the storage device.
        MaxChaRte = self._client.convert_from_registers(regs[21:22], data_type = self._client.DATATYPE.UINT16)
        # MaxDisChaRte: Maximum rate of energy transfer out of the storage device.
        MaxDisChaRte = self._client.convert_from_registers(regs[23:24], data_type = self._client.DATATYPE.UINT16)

        if DERTyp == 82:
            self.storage_configured = True
        self.data['WHRtg'] = WHRtg
        self.data['MaxChaRte'] = MaxChaRte
        self.data['MaxDisChaRte'] = MaxDisChaRte
    
        self.max_charge_rate_w = MaxChaRte
        self.max_discharge_rate_w = MaxDisChaRte

        return True

    def read_inverter_status_data(self):
        regs = self.get_registers(unit_id=self._inverter_unit_id, address=40183, count=44)
        if regs is None:
            return False

        PVConn = self._client.convert_from_registers(regs[0:1], data_type = self._client.DATATYPE.UINT16)
        StorConn = self._client.convert_from_registers(regs[1:2], data_type = self._client.DATATYPE.UINT16)
        ECPConn = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.UINT16)

        StActCtl = self._client.convert_from_registers(regs[33:35], data_type = self._client.DATATYPE.UINT32)
        
        self.data['pv_connection'] = CONNECTION_STATUS_CONDENSED[PVConn]
        self.data['storage_connection'] = CONNECTION_STATUS_CONDENSED[StorConn] 
        self.data['ecp_connection'] = ECP_CONNECTION_STATUS[ECPConn]
        self.data['inverter_controls'] = self.bitmask_to_string(StActCtl, INVERTER_CONTROLS, 'Normal')  

        return True

    def read_inverter_model_settings_data(self):
        regs = self.get_registers(unit_id=self._inverter_unit_id, address=40151, count=30)
        if regs is None:
            return False

        WMax = self._client.convert_from_registers(regs[0:1], data_type = self._client.DATATYPE.UINT16)
        #VRef = self._client.convert_from_registers(regs[1:2], data_type = self._client.DATATYPE.UINT16)
        #VRefOfs = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.UINT16)

        WMax_SF = self._client.convert_from_registers(regs[20:21], data_type = self._client.DATATYPE.INT16)
        #VRef_SF = self._client.convert_from_registers(regs[21:22], data_type = self._client.DATATYPE.INT16)
        #VRefOfs_SF = self._client.convert_from_registers(regs[21:22], data_type = self._client.DATATYPE.INT16)

        self.data['max_power'] = self.calculate_value(WMax, WMax_SF) 
        #self.data['vref'] = self.calculate_value(VRef, VRef_SF) # At PCC 
        #self.data['vrefofs'] = self.calculate_value(VRefOfs, VRefOfs_SF) # At PCC 

        return True

    def read_inverter_controls_data(self):
        regs = self.get_registers(unit_id=self._inverter_unit_id, address=40229, count=24)
        if regs is None:
            return False

        Conn = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.UINT16)
        WMaxLim_Ena = self._client.convert_from_registers(regs[7:8], data_type = self._client.DATATYPE.UINT16)
        OutPFSet_Ena = self._client.convert_from_registers(regs[12:13], data_type = self._client.DATATYPE.UINT16)
        VArPct_Ena = self._client.convert_from_registers(regs[20:21], data_type = self._client.DATATYPE.INT16)

        self.data['Conn'] = CONTROL_STATUS[Conn]
        self.data['WMaxLim_Ena'] = CONTROL_STATUS[WMaxLim_Ena]
        self.data['OutPFSet_Ena'] = CONTROL_STATUS[OutPFSet_Ena]
        self.data['VArPct_Ena'] = CONTROL_STATUS[VArPct_Ena]

        return True

    def read_mppt_data(self):
        regs = self.get_registers(unit_id=self._inverter_unit_id, address=MPPT_ADDRESS, count=88)
        if regs is None:
            return False

        DCW_SF = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.INT16)
        DCWH_SF = self._client.convert_from_registers(regs[3:4], data_type = self._client.DATATYPE.INT16)
        N = self._client.convert_from_registers(regs[6:7], data_type = self._client.DATATYPE.UINT16)
        if N != 4:
            _LOGGER.error(f"Integration only supports 4 mppt modules. Found only: {N}")
            return

        module_1_DCW = self._client.convert_from_registers(regs[19:20], data_type = self._client.DATATYPE.UINT16)
        module_1_DCWH = self._client.convert_from_registers(regs[20:22], data_type = self._client.DATATYPE.UINT32)

        module_2_DCW = self._client.convert_from_registers(regs[39:40], data_type = self._client.DATATYPE.UINT16)
        module_2_DCWH = self._client.convert_from_registers(regs[40:42], data_type = self._client.DATATYPE.UINT32)

        module_3_DCW = self._client.convert_from_registers(regs[59:60], data_type = self._client.DATATYPE.UINT16)
        module_3_DCWH = self._client.convert_from_registers(regs[60:62], data_type = self._client.DATATYPE.UINT32)

        module_4_DCW = self._client.convert_from_registers(regs[79:80], data_type = self._client.DATATYPE.UINT16)
        module_4_DCWH = self._client.convert_from_registers(regs[80:82], data_type = self._client.DATATYPE.UINT32)

        mppt1_power = self.calculate_value(module_1_DCW, DCW_SF)
        mppt2_power = self.calculate_value(module_2_DCW, DCW_SF)
        mppt3_power = self.calculate_value(module_3_DCW, DCW_SF)
        mppt4_power = self.calculate_value(module_4_DCW, DCW_SF)

        mppt1_lfte = self.calculate_value(module_1_DCWH, DCWH_SF)
        mppt2_lfte = self.calculate_value(module_2_DCWH, DCWH_SF)
        mppt3_lfte = self.calculate_value(module_3_DCWH, DCWH_SF)
        mppt4_lfte = self.calculate_value(module_4_DCWH, DCWH_SF)

        self.data['mppt1_power'] = mppt1_power
        self.data['mppt2_power'] = mppt2_power
        self.data['mppt3_power'] = mppt3_power
        self.data['mppt4_power'] = mppt4_power
        self.data['pv_power'] = mppt1_power + mppt2_power
        self.data['storage_power'] = mppt4_power - mppt3_power

        self.data['mppt1_lfte'] = mppt1_lfte
        self.data['mppt2_lfte'] = mppt2_lfte
        self.data['mppt3_lfte'] = mppt3_lfte
        self.data['mppt4_lfte'] = mppt4_lfte

        return True

    def read_inverter_storage_data(self):
        """start reading storage data"""
        regs = self.get_registers(unit_id=self._inverter_unit_id, address=STORAGE_ADDRESS, count=24)
        if regs is None:
            return False
        
        # WChaMax: Reference Value for maximum Charge and Discharge.
        max_charge = self._client.convert_from_registers(regs[0:1], data_type = self._client.DATATYPE.UINT16)
        # WChaGra: Setpoint for maximum charging rate. Default is MaxChaRte.
        WChaGra = self._client.convert_from_registers(regs[1:2], data_type = self._client.DATATYPE.UINT16)
        # WDisChaGra: Setpoint for maximum discharge rate. Default is MaxDisChaRte.
        WDisChaGra = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.UINT16)
        # StorCtl_Mod: Active hold/discharge/charge storage control mode.
        storage_control_mode = self._client.convert_from_registers(regs[3:4], data_type = self._client.DATATYPE.UINT16)
        # VAChaMax: not supported
        # MinRsvPct: Setpoint for minimum reserve for storage as a percentage of the nominal maximum storage.
        minimum_reserve = self._client.convert_from_registers(regs[5:6], data_type = self._client.DATATYPE.UINT16)
        # ChaState: Currently available energy as a percent of the capacity rating.
        charge_state = self._client.convert_from_registers(regs[6:7], data_type = self._client.DATATYPE.UINT16)
        # StorAval: not supported 
        # InBatV: not supported
        # ChaSt:  Charge status of storage device.
        charge_status = self._client.convert_from_registers(regs[9:10], data_type = self._client.DATATYPE.UINT16)
        # OutWRte: Defines maximum Discharge rate. If not used than the default is 100 and WChaMax defines max. Discharge rate.
        discharge_power = self._client.convert_from_registers(regs[10:11], data_type = self._client.DATATYPE.INT16)
        # InWRte: Defines maximum Charge rate. If not used than the default is 100 and WChaMax defines max. Charge rate.
        charge_power = self._client.convert_from_registers(regs[11:12], data_type = self._client.DATATYPE.INT16)
        # InOutWRte_WinTms: not supported
        # InOutWRte_RvrtTms: Timeout period for charge/discharge rate.
        #InOutWRte_RvrtTms = self._client.convert_from_registers(regs[13:14], data_type = self._client.DATATYPE.INT16)
        # InOutWRte_RmpTms: not supported
        # ChaGriSet
        charge_grid_set = self._client.convert_from_registers(regs[15:16], data_type = self._client.DATATYPE.UINT16)
        # WChaMax_SF: Scale factor for maximum charge. 0
        #max_charge_sf = self._client.convert_from_registers(regs[16:17], data_type = self._client.DATATYPE.INT16)
        # WChaDisChaGra_SF: Scale factor for maximum charge and discharge rate. 0
        # VAChaMax_SF: not supported
        # MinRsvPct_SF: Scale factor for minimum reserve percentage. -2
        # ChaState_SF: Scale factor for available energy percent. -2
        #charge_state_sf = self._client.convert_from_registers(regs[20:21], data_type = self._client.DATATYPE.INT16)
        # StorAval_SF: not supported
        # InBatV_SF: not supported
        # InOutWRte_SF: Scale factor for percent charge/discharge rate. -2

        self.data['grid_charging'] = CHARGE_GRID_STATUS.get(charge_grid_set)
        #self.data['power'] = power
        self.data['charge_status'] = CHARGE_STATUS.get(charge_status)
        self.data['minimum_reserve'] =  self.calculate_value(minimum_reserve, -2)
        self.data['discharging_power'] = self.calculate_value(discharge_power, -2)
        self.data['charging_power'] = self.calculate_value(charge_power, -2)
        self.data['soc'] = self.calculate_value(charge_state, -2)
        self.data['max_charge'] = self.calculate_value(max_charge, 0, 0)
        self.data['WChaGra'] = self.calculate_value(WChaGra, 0, 0)
        self.data['WDisChaGra'] = self.calculate_value(WDisChaGra, 0, 0)

        control_mode = self.data.get('control_mode')
        if control_mode is None or control_mode != STORAGE_CONTROL_MODE.get(storage_control_mode):
            if discharge_power >= 0:
                self.data['discharge_limit'] = discharge_power / 100.0 
                self.data['grid_charge_power'] = 0
            else: 
                self.data['grid_charge_power'] = (discharge_power * -1) / 100.0 
                self.data['discharge_limit'] = 0
            if charge_power >= 0:
                self.data['charge_limit'] = charge_power / 100 
                self.data['grid_discharge_power'] = 0
            else: 
                self.data['grid_discharge_power'] = (charge_power * -1) / 100.0 
                self.data['charge_limit'] = 0

            self.data['control_mode'] = STORAGE_CONTROL_MODE.get(storage_control_mode)

        # set extended storage control mode at startup
        ext_control_mode = self.data.get('ext_control_mode')
        if ext_control_mode is None:
            if storage_control_mode == 0:
                ext_control_mode = 0
            elif storage_control_mode in [1,3] and charge_power == 0:
                ext_control_mode = 7
            elif storage_control_mode == 1:
                ext_control_mode = 1
            elif storage_control_mode in [2,3] and discharge_power < 0:
                ext_control_mode = 4
            elif storage_control_mode in [2,3] and charge_power < 0:
                ext_control_mode = 5
            elif storage_control_mode in [2,3] and discharge_power == 0:
                ext_control_mode = 6
            elif storage_control_mode == 2:
                ext_control_mode = 2
            elif storage_control_mode == 3:
                ext_control_mode = 3
            self.data['ext_control_mode'] = STORAGE_EXT_CONTROL_MODE[ext_control_mode]
            self.storage_extended_control_mode = ext_control_mode

        if ext_control_mode == 7:
            soc = self.data.get('soc')
            if storage_control_mode == 2 and soc == 100:
                _LOGGER.error(f'Calibration hit 100%, start discharge')
                self.change_settings(1, 0, 100, 0)
            elif storage_control_mode == 3 and soc <= 5: 
                _LOGGER.error(f'Calibration hit 5%, return to auto mode')
                self.set_auto_mode()
                self.set_minimum_reserve(30)
                self.data['ext_control_mode'] = STORAGE_EXT_CONTROL_MODE[0]
                self.storage_extended_control_mode = 0

        return True

    def read_meter_data(self, meter_prefix, unit_id):
        """start reading meter data"""
        regs = self.get_registers(unit_id=unit_id, address=METER_ADDRESS, count=103)
        if regs is None:
            return False

        PhVphA = self._client.convert_from_registers(regs[6:7], data_type = self._client.DATATYPE.INT16)
        PhVphB = self._client.convert_from_registers(regs[7:8], data_type = self._client.DATATYPE.INT16)
        PhVphC = self._client.convert_from_registers(regs[8:9], data_type = self._client.DATATYPE.INT16)
        PPV = self._client.convert_from_registers(regs[9:10], data_type = self._client.DATATYPE.INT16)
        V_SF = self._client.convert_from_registers(regs[13:14], data_type = self._client.DATATYPE.INT16)

        Hz = self._client.convert_from_registers(regs[14:15], data_type = self._client.DATATYPE.INT16)
        Hz_SF = self._client.convert_from_registers(regs[15:16], data_type = self._client.DATATYPE.INT16)
        W = self._client.convert_from_registers(regs[16:17], data_type = self._client.DATATYPE.INT16)
        W_SF = self._client.convert_from_registers(regs[20:21], data_type = self._client.DATATYPE.INT16)

        TotWhExp = self._client.convert_from_registers(regs[36:38], data_type = self._client.DATATYPE.UINT32)
        TotWhImp = self._client.convert_from_registers(regs[44:46], data_type = self._client.DATATYPE.UINT32)
        TotWh_SF = self._client.convert_from_registers(regs[52:53], data_type = self._client.DATATYPE.INT16)

        acpower = self.calculate_value(W, W_SF)
        m_frequency = self.calculate_value(Hz, Hz_SF)
 
        self.data[meter_prefix + "PhVphA"] = self.calculate_value(PhVphA, V_SF,1)
        self.data[meter_prefix + "PhVphB"] = self.calculate_value(PhVphB, V_SF,1)
        self.data[meter_prefix + "PhVphC"] = self.calculate_value(PhVphC, V_SF,1)
        self.data[meter_prefix + "PPV"] = self.calculate_value(PPV, V_SF,1)
        self.data[meter_prefix + "exported"] = self.calculate_value(TotWhExp, TotWh_SF)
        self.data[meter_prefix + "imported"] = self.calculate_value(TotWhImp, TotWh_SF)
        self.data[meter_prefix + "line_frequency"] = m_frequency
        self.data[meter_prefix + "power"] = acpower

        if meter_prefix == 'm1_':
            inverter_acpower = self.data.get('acpower')
            if not acpower is None and not inverter_acpower is None:
                if self.is_numeric(acpower) and self.is_numeric(inverter_acpower):
                    self.data['load'] = round(acpower + inverter_acpower,2)
                elif not self.is_numeric(acpower):
                    _LOGGER.warning(f'meter acpower not numeric {acpower}')
                elif not self.is_numeric(inverter_acpower):
                    _LOGGER.warning(f'inverter acpower not numeric {inverter_acpower}')

            #status = None
            status_str = ""
            i_frequency = self.data["line_frequency"]
            #_LOGGER.debug(f'grid status m: {m_frequency} i: {i_frequency}')
            if not i_frequency is None and self.is_numeric(i_frequency):
                if i_frequency > 48 and i_frequency < 52:
                    status_str = GRID_STATUS.get(3)
                elif i_frequency > 52 and i_frequency < 54:
                    status_str = GRID_STATUS.get(1)
                elif i_frequency < 1:
                    # statusvendor = self.data.get("statusvendor")
                    # statusvendor_id = self.data.get("statusvendor_id")
                    # if statusvendor is None:
                    #     statusvendor = 'na'
                    #     statusvendor_id = -1
                    if not m_frequency is None and self.is_numeric(m_frequency):                        
                        if m_frequency > 48:
                            status_str = GRID_STATUS.get(2)
                        elif m_frequency < 1:
                            status_str = GRID_STATUS.get(0)
            if status_str is None:
                _LOGGER.error(f'Could not establish grid connection status m: {m_frequency} i: {i_frequency}')
                self.data["grid_status"] = None
            else:
                self.data["grid_status"] = status_str

        return True

    def is_numeric(self, value):
        if isinstance(value, (int, float, complex)) and not isinstance(value, bool):
            return True
        return False

    def set_storage_control_mode(self, mode: int):
        if not mode in [0,1,2,3]:
            _LOGGER.error(f'Attempted to set to unsupported storage control mode. Value: {mode}')
            return
        self.write_registers(unit_id=self._inverter_unit_id, address=STORAGE_CONTROL_MODE_ADDRESS, payload=mode)

    def set_minimum_reserve(self, minimum_reserve: float):
        if minimum_reserve < 5:
            _LOGGER.error(f'Attempted to set minimum reserve below 5%. Value: {minimum_reserve}')
            return
        minimum_reserve = round(minimum_reserve * 100)
        self.write_registers(unit_id=self._inverter_unit_id, address=MINIMUM_RESERVE_ADDRESS, payload=minimum_reserve)

    def set_discharge_rate_w(self, discharge_rate_w):
        if discharge_rate_w > self.max_discharge_rate_w:
            discharge_rate = 100
        elif discharge_rate_w < self.max_discharge_rate_w * -1:
            discharge_rate = -100
        else:
            discharge_rate = discharge_rate_w / self.max_discharge_rate_w * 100
        self.set_discharge_rate(discharge_rate)

    def set_discharge_rate(self, discharge_rate):
        if discharge_rate < 0:
            discharge_rate = int(65536 + (discharge_rate * 100))
        else:
            discharge_rate = int(round(discharge_rate * 100))
        self.write_registers(unit_id=self._inverter_unit_id, address=DISCHARGE_RATE_ADDRESS, payload=discharge_rate)

    def set_charge_rate_w(self, charge_rate_w):
        if charge_rate_w > self.max_charge_rate_w:
            charge_rate = 100
        elif charge_rate_w < self.max_charge_rate_w * -1:
            charge_rate = -100
        else:
            charge_rate = charge_rate_w / self.max_charge_rate_w * 100
        self.set_charge_rate(charge_rate)

    def set_charge_rate(self, charge_rate):
        if charge_rate < 0:
            charge_rate =  int(65536 + (charge_rate * 100))
        else:
            charge_rate = int(round(charge_rate * 100))
        self.write_registers(unit_id=self._inverter_unit_id, address=CHARGE_RATE_ADDRESS, payload=charge_rate)

    def change_settings(self, mode, charge_limit, discharge_limit, grid_charge_power=0, grid_discharge_power=0, minimum_reserve=None):
        self.set_storage_control_mode(mode)
        self.set_charge_rate(charge_limit)
        self.set_discharge_rate(discharge_limit)
        self.data['charge_limit'] = charge_limit
        if self.storage_extended_control_mode == 4:
            self.data['discharge_limit'] = 0
        else:
            self.data['discharge_limit'] = discharge_limit
        if self.storage_extended_control_mode == 5:
            self.data['charge_limit'] = 0
        else:
            self.data['charge_limit'] = charge_limit
        self.data['grid_charge_power'] = grid_charge_power
        self.data['grid_discharge_power'] = grid_discharge_power
        if not minimum_reserve is None:
            self.set_minimum_reserve(minimum_reserve)
        
    def restore_defaults(self):
        self.change_settings(mode=0, charge_limit=100, discharge_limit=100, minimum_reserve=7)
        _LOGGER.info(f"restored defaults")

    def set_auto_mode(self):
        self.change_settings(mode=0, charge_limit=100, discharge_limit=100)
        _LOGGER.info(f"Auto mode")

    def set_charge_mode(self):
        self.change_settings(mode=1, charge_limit=100, discharge_limit=100)
        _LOGGER.info(f"Set charge mode")
  
    def set_discharge_mode(self):
        self.change_settings(mode=2, charge_limit=100, discharge_limit=100)
        _LOGGER.info(f"Set discharge mode")

    def set_charge_discharge_mode(self):
        self.change_settings(mode=3, charge_limit=100, discharge_limit=100)
        _LOGGER.info(f"Set charge/discharge mode.")

    def set_grid_charge_mode(self):
        grid_charge_power = 0
        discharge_rate = grid_charge_power * -1
        self.change_settings(mode=2, charge_limit=100, discharge_limit=discharge_rate, grid_charge_power=grid_charge_power)
        _LOGGER.info(f"Forced charging at {grid_charge_power}")

    def set_grid_discharge_mode(self):
        grid_discharge_power = 0
        charge_rate = grid_discharge_power * -1
        self.change_settings(mode=1, charge_limit=charge_rate, discharge_limit=100, grid_discharge_power=grid_discharge_power)
        _LOGGER.info(f"Forced discharging to grid {grid_discharge_power}")

    def set_block_discharge_mode(self):
        charge_rate = 100
        self.change_settings(mode=3, charge_limit=charge_rate, discharge_limit=0)
        _LOGGER.info(f"blocked discharging")

    def set_block_charge_mode(self):
        discharge_rate = 100
        self.change_settings(mode=3, charge_limit=0, discharge_limit=discharge_rate)
        _LOGGER.info(f"Block charging at {discharge_rate}")

    def set_calibrate_mode(self):
        self.change_settings(mode=2, charge_limit=100, discharge_limit=-100, grid_charge_power=100)
        _LOGGER.info(f"Auto mode")
