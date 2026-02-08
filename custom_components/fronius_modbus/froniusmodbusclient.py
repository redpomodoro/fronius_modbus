#import os, sys; sys.path.append(os.path.dirname(os.path.realpath(__file__)))

"""BYD Battery Box Class"""

import asyncio
import logging
from typing import Optional, Literal
from .extmodbusclient import ExtModbusClient
import requests

from .froniusmodbusclient_const import (
    INVERTER_ADDRESS,
    MPPT_ADDRESS,
    COMMON_ADDRESS,
    NAMEPLATE_ADDRESS,
    STORAGE_ADDRESS,
    METER_ADDRESS,
    STORAGE_CONTROL_MODE,
    CHARGE_STATUS,
    CHARGE_GRID_STATUS,
    STORAGE_EXT_CONTROL_MODE,
    FRONIUS_INVERTER_STATUS,
    CONNECTION_STATUS_CONDENSED,
    ECP_CONNECTION_STATUS,
    INVERTER_CONTROLS,
    INVERTER_EVENTS,
    CONTROL_STATUS,
    GRID_STATUS,
#    INVERTER_STATUS,
#    CONNECTION_STATUS,
)

_LOGGER = logging.getLogger(__name__)

class FroniusModbusClient(ExtModbusClient):
    """Hub for BYD Battery Box Interface"""

    def __init__(self, host: str, port: int, inverter_unit_id: int, meter_unit_ids, timeout: int) -> None:
        """Init hub."""
        super(FroniusModbusClient, self).__init__(host = host, port = port, unit_id=inverter_unit_id, timeout=timeout)

        self.initialized = False

        self._inverter_unit_id = inverter_unit_id
        self._meter_unit_ids = meter_unit_ids

        self.meter_configured = False
        self.mppt_configured = False
        self.storage_configured = False
        self.storage_extended_control_mode = 0
        self.max_charge_rate_w = 11000
        self.max_discharge_rate_w = 11000
        self._storage_address = STORAGE_ADDRESS
        self.mppt_module_count = 2
        self.mppt_model_length = 88
        self._grid_frequency = 50
        self._grid_frequency_lower_bound = self._grid_frequency - 0.2
        self._grid_frequency_upper_bound = self._grid_frequency + 0.2

        self._inverter_frequency_lower_bound = self._grid_frequency - 5
        self._inverter_frequency_upper_bound = self._grid_frequency + 5

        self.data = {}

    def _map_value(self, values: dict, key: int, field_name: str):
        value = values.get(key)
        if value is None:
            _LOGGER.debug("Unknown %s code %s", field_name, key)
            return f"Unknown ({key})"
        return value

    def _storage_register_address(self, offset: int) -> int:
        return self._storage_address + offset

    def _update_storage_base_address(self, mppt_model_length: int):
        if not self.is_numeric(mppt_model_length):
            return

        model_length = int(mppt_model_length)
        if model_length < 20 or model_length > 200:
            return

        # In this integration's addressing mode, storage model starts directly behind MPPT at L + length + 2.
        candidate = MPPT_ADDRESS + model_length + 2
        if candidate < 40300 or candidate > 40500:
            return

        self.mppt_model_length = model_length
        self._storage_address = candidate
        self.data["storage_model_address"] = candidate

    async def init_data(self):
        await self.connect()
        try: 
            result = await self.read_device_info_data(prefix='i_', unit_id=self._inverter_unit_id)
        except Exception as e:
            _LOGGER.error(f"Error reading inverter info {self._host}:{self._port} unit id: {self._inverter_unit_id}", exc_info=True)
            raise Exception(f"Error reading inverter info unit id: {self._inverter_unit_id}")
        if result == False:
            _LOGGER.error(f"Empty inverter info {self._host}:{self._port} unit id: {self._inverter_unit_id}")
            raise Exception(f"Empty inverter info unit id: {self._inverter_unit_id}")

        try:
            if await self.read_mppt_data():
                self.mppt_configured = True
        except Exception as e:
            _LOGGER.warning(f"Error while checking mppt data {e}")

        if len(self._meter_unit_ids)>5:
            _LOGGER.error(f"Too many meters configured, max 5")
            return
        #elif len(self._meter_unit_ids)>0:
        #    self.meter_configured = True

        for i in range(len(self._meter_unit_ids)):
            unit_id = self._meter_unit_ids[i]
            try:
                result = await self.read_device_info_data(prefix=f'm{i+1}_', unit_id=unit_id)
                if result:
                    if not self.meter_configured:
                        self.meter_configured = True
                else:
                    _LOGGER.error(f"Failed reading meter info unit id: {unit_id}")
            except Exception as e:
                _LOGGER.error(f"Error reading meter info unit id: {unit_id}", exc_info=True)

        if await self.read_inverter_nameplate_data() == False:
            _LOGGER.error(f"Error reading nameplate data", exc_info=True)
        elif self.mppt_configured:
            # Re-evaluate MPPT channels after storage detection from nameplate data.
            await self.read_mppt_data()

        _LOGGER.debug(f"Init done. data: {self.data}")

        return True
    
    def get_json_storage_info(self):
        self.data['s_manufacturer'] = None
        self.data['s_model'] = 'Battery Storage'
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

    async def read_device_info_data(self, prefix, unit_id):
        regs = await self.get_registers(unit_id=unit_id, address=COMMON_ADDRESS, count=65)
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

    async def read_inverter_data(self):
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=INVERTER_ADDRESS, count=50)
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
        self.data["acpower"] = self.calculate_value(W, W_SF, 2, -50000, 50000)
        self.data["line_frequency"] = self.calculate_value(Hz, Hz_SF, 2, 0, 100)
        self.data["acenergy"] = self.calculate_value(WH, WH_SF) 
        #self.data["status"] = INVERTER_STATUS[St]
        self.data["statusvendor"] = self._map_value(FRONIUS_INVERTER_STATUS, StVnd, "inverter status")
        self.data["statusvendor_id"] = StVnd
        #self.data["events1"] = self.bitmask_to_string(EvtVnd1,INVERTER_EVENTS,default='None',bits=32)  
        self.data["events2"] = self.bitmask_to_string(EvtVnd2,INVERTER_EVENTS,default='None',bits=32)  

        return True

    async def read_inverter_nameplate_data(self):
        """start reading storage data"""
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=NAMEPLATE_ADDRESS, count=120)
        if regs is None:
            return False

        # DERTyp: Type of DER device. Default value is 4 to indicate PV device.
        DERTyp = self._client.convert_from_registers(regs[0:1], data_type = self._client.DATATYPE.UINT16)
        # WHRtg: Nominal energy rating of storage device.
        WHRtg = self._client.convert_from_registers(regs[17:18], data_type = self._client.DATATYPE.UINT16)
        WHRtg_SF = self._client.convert_from_registers(regs[18:19], data_type = self._client.DATATYPE.INT16)
        # MaxChaRte: Maximum rate of energy transfer into the storage device.
        MaxChaRte = self._client.convert_from_registers(regs[21:22], data_type = self._client.DATATYPE.UINT16)
        MaxChaRte_SF = self._client.convert_from_registers(regs[22:23], data_type = self._client.DATATYPE.INT16)
        # MaxDisChaRte: Maximum rate of energy transfer out of the storage device.
        MaxDisChaRte = self._client.convert_from_registers(regs[23:24], data_type = self._client.DATATYPE.UINT16)
        MaxDisChaRte_SF = self._client.convert_from_registers(regs[24:25], data_type = self._client.DATATYPE.INT16)

        self.data['DERTyp'] = DERTyp
        self.data['WHRtg'] = self.calculate_value(WHRtg, WHRtg_SF, 0)
        self.data['MaxChaRte'] = self.calculate_value(MaxChaRte, MaxChaRte_SF, 0)
        self.data['MaxDisChaRte'] = self.calculate_value(MaxDisChaRte, MaxDisChaRte_SF, 0)
    
        if self.is_numeric(self.data['MaxChaRte']):
            self.max_charge_rate_w = self.data['MaxChaRte']
        if self.is_numeric(self.data['MaxDisChaRte']):
            self.max_discharge_rate_w = self.data['MaxDisChaRte']

        return True

    async def read_inverter_status_data(self):
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=40183, count=44)
        if regs is None:
            return False

        PVConn = self._client.convert_from_registers(regs[0:1], data_type = self._client.DATATYPE.UINT16)
        StorConn = self._client.convert_from_registers(regs[1:2], data_type = self._client.DATATYPE.UINT16)
        ECPConn = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.UINT16)

        StActCtl = self._client.convert_from_registers(regs[33:35], data_type = self._client.DATATYPE.UINT32)
        
        self.data['pv_connection'] = self._map_value(CONNECTION_STATUS_CONDENSED, PVConn, 'pv connection')
        self.data['storage_connection'] = self._map_value(CONNECTION_STATUS_CONDENSED, StorConn, 'storage connection')
        self.data['ecp_connection'] = self._map_value(ECP_CONNECTION_STATUS, ECPConn, 'electrical connection')
        self.data['inverter_controls'] = self.bitmask_to_string(StActCtl, INVERTER_CONTROLS, 'Normal')  

        return True

    async def read_inverter_model_settings_data(self):
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=40151, count=30)
        if regs is None:
            return False

        WMax = self._client.convert_from_registers(regs[0:1], data_type = self._client.DATATYPE.UINT16)
        #VRef = self._client.convert_from_registers(regs[1:2], data_type = self._client.DATATYPE.UINT16)
        #VRefOfs = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.UINT16)

        WMax_SF = self._client.convert_from_registers(regs[20:21], data_type = self._client.DATATYPE.INT16)
        #VRef_SF = self._client.convert_from_registers(regs[21:22], data_type = self._client.DATATYPE.INT16)
        #VRefOfs_SF = self._client.convert_from_registers(regs[21:22], data_type = self._client.DATATYPE.INT16)

        self.data['max_power'] = self.calculate_value(WMax, WMax_SF,2,0,50000) 
        #self.data['vref'] = self.calculate_value(VRef, VRef_SF) # At PCC 
        #self.data['vrefofs'] = self.calculate_value(VRefOfs, VRefOfs_SF) # At PCC 

        return True

    async def read_inverter_controls_data(self):
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=40229, count=24)
        if regs is None:
            return False

        Conn = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.UINT16)
        WMaxLim_Ena = self._client.convert_from_registers(regs[7:8], data_type = self._client.DATATYPE.UINT16)
        OutPFSet_Ena = self._client.convert_from_registers(regs[12:13], data_type = self._client.DATATYPE.UINT16)
        VArPct_Ena = self._client.convert_from_registers(regs[20:21], data_type = self._client.DATATYPE.INT16)

        self.data['Conn'] = self._map_value(CONTROL_STATUS, Conn, 'connection control')
        self.data['WMaxLim_Ena'] = self._map_value(CONTROL_STATUS, WMaxLim_Ena, 'throttle control')
        self.data['OutPFSet_Ena'] = self._map_value(CONTROL_STATUS, OutPFSet_Ena, 'fixed power factor')
        self.data['VArPct_Ena'] = self._map_value(CONTROL_STATUS, VArPct_Ena, 'VAr control')

        return True

    async def read_mppt_data(self):
        mppt_read_address = MPPT_ADDRESS
        header_regs = await self.get_registers(unit_id=self._inverter_unit_id, address=MPPT_ADDRESS, count=2)
        if header_regs is None:
            return False

        mppt_model_length = self._client.convert_from_registers(header_regs[0:1], data_type=self._client.DATATYPE.UINT16)
        if not self.is_numeric(mppt_model_length) or int(mppt_model_length) < 20 or int(mppt_model_length) > 200:
            alt_header_regs = await self.get_registers(unit_id=self._inverter_unit_id, address=MPPT_ADDRESS - 1, count=2)
            if alt_header_regs is None:
                return False
            alt_mppt_model_length = self._client.convert_from_registers(alt_header_regs[0:1], data_type=self._client.DATATYPE.UINT16)
            if not self.is_numeric(alt_mppt_model_length) or int(alt_mppt_model_length) < 20 or int(alt_mppt_model_length) > 200:
                return False
            mppt_model_length = alt_mppt_model_length
            mppt_read_address = MPPT_ADDRESS - 1

        self._update_storage_base_address(int(mppt_model_length))
        self.data['mppt_model_length'] = int(mppt_model_length)

        storage_model_header = await self.get_registers(
            unit_id=self._inverter_unit_id,
            address=self._storage_address - 2,
            count=2,
        )
        if storage_model_header and len(storage_model_header) == 2:
            storage_model_id = self._client.convert_from_registers(storage_model_header[0:1], data_type=self._client.DATATYPE.UINT16)
            storage_model_length = self._client.convert_from_registers(storage_model_header[1:2], data_type=self._client.DATATYPE.UINT16)
            self.data['storage_model_id'] = storage_model_id
            self.data['storage_model_length'] = storage_model_length
            if storage_model_id == 124 and storage_model_length == 24:
                self.storage_configured = True

        model_register_count = int(mppt_model_length) + 1
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=mppt_read_address, count=model_register_count)
        if regs is None:
            return False

        model_limit = len(regs)
        if model_limit < 8:
            return False

        DCW_SF = self._client.convert_from_registers(regs[3:4], data_type=self._client.DATATYPE.INT16)
        DCWH_SF = self._client.convert_from_registers(regs[4:5], data_type=self._client.DATATYPE.INT16)
        reported_module_count = self._client.convert_from_registers(regs[7:8], data_type=self._client.DATATYPE.UINT16)
        if not self.is_numeric(reported_module_count) or int(reported_module_count) <= 0:
            return False

        # Module i has DCW at index 20*i and DCWH at index 20*i+1 (2 registers) relative to L.
        max_modules_by_length = (model_limit - 2) // 20
        module_count = min(int(reported_module_count), int(max_modules_by_length))
        if module_count <= 0:
            return False

        self.mppt_module_count = module_count
        self.data['mppt_module_count'] = module_count

        module_power = {}
        module_lfte = {}
        module_labels = {}
        for module_id in range(1, module_count + 1):
            label_idx = 20 * (module_id - 1) + 10
            power_idx = 20 * module_id
            lfte_idx = power_idx + 1

            label = None
            if label_idx + 8 <= model_limit:
                try:
                    label = self.get_string_from_registers(regs[label_idx:label_idx + 8])
                except Exception:
                    label = None
            module_labels[module_id] = label

            raw_power = self._client.convert_from_registers(regs[power_idx:power_idx + 1], data_type=self._client.DATATYPE.UINT16)
            raw_lfte = self._client.convert_from_registers(regs[lfte_idx:lfte_idx + 2], data_type=self._client.DATATYPE.UINT32)

            power = self.calculate_value(raw_power, DCW_SF, 2)
            lfte = self.calculate_value(raw_lfte, DCWH_SF)

            module_power[module_id] = power
            module_lfte[module_id] = lfte
            self.data[f'module{module_id}_label'] = label
            self.data[f'module{module_id}_power'] = power
            self.data[f'module{module_id}_lfte'] = lfte

        for module_id in range(1, min(module_count, 4) + 1):
            self.data[f'mppt{module_id}_power'] = module_power.get(module_id)
            self.data[f'mppt{module_id}_lfte'] = module_lfte.get(module_id)

        storage_charge_module = None
        storage_discharge_module = None
        for module_id, label in module_labels.items():
            if not isinstance(label, str):
                continue
            normalized = label.replace(" ", "").upper()
            if "STDISCHA" in normalized:
                storage_discharge_module = module_id
            elif normalized.startswith("STCHA"):
                storage_charge_module = module_id

        # Model 160 reports N as MPPT tracker count + 2 battery channels.
        # If labels are unavailable, keep compatibility by using the last two modules as storage channels.
        if self.storage_configured and not (storage_charge_module and storage_discharge_module) and module_count >= 4:
            storage_charge_module = module_count - 1
            storage_discharge_module = module_count

        if self.storage_configured and storage_charge_module and storage_discharge_module:
            self.data['storage_charge_module'] = storage_charge_module
            self.data['storage_discharge_module'] = storage_discharge_module

            self.data['mppt3_power'] = module_power.get(storage_charge_module)
            self.data['mppt4_power'] = module_power.get(storage_discharge_module)
            self.data['mppt3_lfte'] = module_lfte.get(storage_charge_module)
            self.data['mppt4_lfte'] = module_lfte.get(storage_discharge_module)

            storage_charge_power = module_power.get(storage_charge_module)
            storage_discharge_power = module_power.get(storage_discharge_module)
            if self.is_numeric(storage_charge_power) and self.is_numeric(storage_discharge_power):
                self.data['storage_power'] = round(storage_discharge_power - storage_charge_power, 2)
            else:
                self.data['storage_power'] = None
        elif self.storage_configured:
            self.data['mppt3_power'] = None
            self.data['mppt4_power'] = None
            self.data['mppt3_lfte'] = None
            self.data['mppt4_lfte'] = None
            self.data['storage_power'] = None

        pv_modules = []
        for module_id, label in module_labels.items():
            if isinstance(label, str) and "MPPT" in label.upper():
                pv_modules.append(module_id)
        if not pv_modules:
            if storage_charge_module and storage_discharge_module:
                pv_modules = [module_id for module_id in range(1, module_count + 1) if module_id not in [storage_charge_module, storage_discharge_module]]
            else:
                pv_modules = list(range(1, module_count + 1))

        pv_values = [module_power.get(module_id) for module_id in pv_modules if self.is_numeric(module_power.get(module_id))]
        self.data['pv_power'] = round(sum(pv_values), 2) if pv_values else None

        return True

    async def read_inverter_storage_data(self):
        """start reading storage data"""
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=self._storage_address, count=24)
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

        if self.is_numeric(max_charge) and max_charge > 0:
            self.storage_configured = True

        self.data['grid_charging'] = self._map_value(CHARGE_GRID_STATUS, charge_grid_set, 'grid charging')
        #self.data['power'] = power
        self.data['charge_status'] = self._map_value(CHARGE_STATUS, charge_status, 'charge status')
        self.data['minimum_reserve'] =  self.calculate_value(minimum_reserve, -2, 2, 0, 100)
        self.data['discharging_power'] = self.calculate_value(discharge_power, -2, 2, -100, 100)
        self.data['charging_power'] = self.calculate_value(charge_power, -2, 2, -100, 100)
        self.data['soc'] = self.calculate_value(charge_state, -2, 2, 0, 100)
        self.data['max_charge'] = self.calculate_value(max_charge, 0, 0)
        self.data['WChaGra'] = self.calculate_value(WChaGra, 0, 0)
        self.data['WDisChaGra'] = self.calculate_value(WDisChaGra, 0, 0)

        mapped_control_mode = self._map_value(STORAGE_CONTROL_MODE, storage_control_mode, 'storage control mode')
        control_mode = self.data.get('control_mode')
        if control_mode is None or control_mode != mapped_control_mode:
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

            self.data['control_mode'] = mapped_control_mode

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
            if not ext_control_mode is None:
                self.data['ext_control_mode'] = self._map_value(STORAGE_EXT_CONTROL_MODE, ext_control_mode, 'extended storage mode')
                self.storage_extended_control_mode = ext_control_mode

        if ext_control_mode == 7:
            soc = self.data.get('soc')
            if storage_control_mode == 2 and soc == 100:
                _LOGGER.error(f'Calibration hit 100%, start discharge')
                await self.change_settings(1, 0, 100, 0)
            elif storage_control_mode == 3 and soc <= 5: 
                _LOGGER.error(f'Calibration hit 5%, return to auto mode')
                await self.set_auto_mode()
                await self.set_minimum_reserve(30)
                self.data['ext_control_mode'] = self._map_value(STORAGE_EXT_CONTROL_MODE, 0, 'extended storage mode')
                self.storage_extended_control_mode = 0

        return True

    async def read_meter_data(self, meter_prefix, unit_id):
        """start reading meter data"""
        regs = await self.get_registers(unit_id=unit_id, address=METER_ADDRESS, count=103)
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

        acpower = self.calculate_value(W, W_SF, 2, -50000, 50000)
        m_frequency = self.calculate_value(Hz, Hz_SF, 2, 0, 100)
 
        self.data[meter_prefix + "PhVphA"] = self.calculate_value(PhVphA, V_SF,1,0,1000)
        self.data[meter_prefix + "PhVphB"] = self.calculate_value(PhVphB, V_SF,1,0,1000)
        self.data[meter_prefix + "PhVphC"] = self.calculate_value(PhVphC, V_SF,1,0,1000)
        self.data[meter_prefix + "PPV"] = self.calculate_value(PPV, V_SF,1,0,1000)
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
                    _LOGGER.error(f'meter {meter_prefix} acpower not numeric {acpower}')
                elif not self.is_numeric(inverter_acpower):
                    _LOGGER.error(f'inverter acpower not numeric {inverter_acpower}')

            status_str = ""
            i_frequency = self.data["line_frequency"]
            #_LOGGER.debug(f'grid status m: {m_frequency} i: {i_frequency}')
            if not i_frequency is None and self.is_numeric(i_frequency) and not m_frequency is None and self.is_numeric(m_frequency):
                m_online = False
                if m_frequency and m_frequency > self._grid_frequency_lower_bound and m_frequency < self._grid_frequency_upper_bound:
                    m_online = True
                
                if m_online and i_frequency > self._grid_frequency_lower_bound and i_frequency < self._grid_frequency_upper_bound:
                    status_str = GRID_STATUS.get(3)
                elif not m_online and i_frequency > self._inverter_frequency_lower_bound and i_frequency < self._inverter_frequency_upper_bound:
                    status_str = GRID_STATUS.get(1)
                elif i_frequency < 1:
                    if m_online:
                        status_str = GRID_STATUS.get(2)
                    elif m_frequency < 1:
                        status_str = GRID_STATUS.get(0)
            if status_str is None:
                _LOGGER.error(f'Could not establish grid connection status m: {m_frequency} i: {i_frequency}')
                self.data["grid_status"] = None
            else:
                self.data["grid_status"] = status_str

        return True

    async def set_storage_control_mode(self, mode: int):
        if not mode in [0,1,2,3]:
            _LOGGER.error(f'Attempted to set to unsupported storage control mode. Value: {mode}')
            return
        await self.write_registers(unit_id=self._inverter_unit_id, address=self._storage_register_address(3), payload=[mode])

    async def set_minimum_reserve(self, minimum_reserve: float):
        if minimum_reserve < 5:
            _LOGGER.error(f'Attempted to set minimum reserve below 5%. Value: {minimum_reserve}')
            return
        minimum_reserve = round(minimum_reserve * 100)
        await self.write_registers(unit_id=self._inverter_unit_id, address=self._storage_register_address(5), payload=[minimum_reserve])

    def _get_storage_reference_power_w(self):
        # Model 124 InWRte/OutWRte are scaled by WChaMax.
        max_charge = self.data.get('max_charge')
        if self.is_numeric(max_charge) and max_charge > 0:
            return max_charge

        if self.is_numeric(self.max_charge_rate_w) and self.is_numeric(self.max_discharge_rate_w):
            fallback = max(self.max_charge_rate_w, self.max_discharge_rate_w)
            if fallback > 0:
                return fallback

        if self.is_numeric(self.max_discharge_rate_w) and self.max_discharge_rate_w > 0:
            return self.max_discharge_rate_w
        return None

    async def set_discharge_rate_w(self, discharge_rate_w):
        reference_power = self._get_storage_reference_power_w()
        if not self.is_numeric(reference_power) or reference_power <= 0:
            _LOGGER.error("Cannot set discharge limit: invalid WChaMax/reference power %s", reference_power)
            return None

        if discharge_rate_w > reference_power:
            discharge_rate = 100
        elif discharge_rate_w < reference_power * -1:
            discharge_rate = -100
        else:
            discharge_rate = discharge_rate_w / reference_power * 100
        await self.set_discharge_rate(discharge_rate)
        return discharge_rate

    async def set_discharge_rate(self, discharge_rate):
        if discharge_rate < 0:
            discharge_rate = int(65536 + (discharge_rate * 100))
        else:
            discharge_rate = int(round(discharge_rate * 100))
        await self.write_registers(unit_id=self._inverter_unit_id, address=self._storage_register_address(10), payload=[discharge_rate])

    async def set_charge_rate_w(self, charge_rate_w):
        if charge_rate_w > self.max_charge_rate_w:
            charge_rate = 100
        elif charge_rate_w < self.max_charge_rate_w * -1:
            charge_rate = -100
        else:
            charge_rate = charge_rate_w / self.max_charge_rate_w * 100
        await self.set_charge_rate(charge_rate)

    async def set_grid_charge_power(self, value):
        if self.storage_extended_control_mode == 4:
            await self.set_discharge_rate_w(value * -1)
            self.data['grid_charge_power'] = value
        else:
            return

    async def set_grid_discharge_power(self, value):
        if self.storage_extended_control_mode == 5:
            await self.set_charge_rate_w(value * -1)
            self.data['grid_discharge_power'] = value
        else:
            return
        
    async def set_charge_limit(self, value):
        if self.storage_extended_control_mode in [1,3,6]:
            # only change when charge limit is used
            await self.set_charge_rate_w(value)
            self.data['charge_limit'] = value
        elif self.storage_extended_control_mode in [4,5,7]:
            return
        elif self.storage_extended_control_mode in [0,2]:
            return

    async def set_discharge_limit(self, value):
        if self.storage_extended_control_mode in [2,3,7]:
            # only change when discharge limit is used
            discharge_rate = await self.set_discharge_rate_w(value)
            if self.is_numeric(discharge_rate):
                self.data['discharge_limit'] = round(discharge_rate, 2)
        elif self.storage_extended_control_mode in [4,5,6]:
            return
        elif self.storage_extended_control_mode in [0,1]:
            return

    async def set_charge_rate(self, charge_rate):
        if charge_rate < 0:
            charge_rate =  int(65536 + (charge_rate * 100))
        else:
            charge_rate = int(round(charge_rate * 100))
        await self.write_registers(unit_id=self._inverter_unit_id, address=self._storage_register_address(11), payload=[charge_rate])

    async def change_settings(self, mode, charge_limit, discharge_limit, grid_charge_power=0, grid_discharge_power=0, minimum_reserve=None):
        await self.set_storage_control_mode(mode)
        await self.set_charge_rate(charge_limit)
        await self.set_discharge_rate(discharge_limit)
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
            await self.set_minimum_reserve(minimum_reserve)
        
    async def restore_defaults(self):
        await self.change_settings(mode=0, charge_limit=100, discharge_limit=100, minimum_reserve=7)
        _LOGGER.info(f"restored defaults")

    async def set_auto_mode(self):
        await self.change_settings(mode=0, charge_limit=100, discharge_limit=100)
        self.storage_extended_control_mode = 0
        _LOGGER.info(f"Auto mode")

    async def set_charge_mode(self):
        await self.change_settings(mode=1, charge_limit=100, discharge_limit=100)
        self.storage_extended_control_mode = 1
        _LOGGER.info(f"Set charge mode")
  
    async def set_discharge_mode(self):
        await self.change_settings(mode=2, charge_limit=100, discharge_limit=100)
        self.storage_extended_control_mode = 2
        _LOGGER.info(f"Set discharge mode")

    async def set_charge_discharge_mode(self):
        await self.change_settings(mode=3, charge_limit=100, discharge_limit=100)
        self.storage_extended_control_mode = 3
        _LOGGER.info(f"Set charge/discharge mode.")

    async def set_grid_charge_mode(self):
        grid_charge_power = 0
        discharge_rate = grid_charge_power * -1
        await self.change_settings(mode=2, charge_limit=100, discharge_limit=discharge_rate, grid_charge_power=grid_charge_power)
        self.storage_extended_control_mode = 4
        _LOGGER.info(f"Forced charging at {grid_charge_power}")

    async def set_grid_discharge_mode(self):
        grid_discharge_power = 0
        charge_rate = grid_discharge_power * -1
        await self.change_settings(mode=1, charge_limit=charge_rate, discharge_limit=100, grid_discharge_power=grid_discharge_power)
        self.storage_extended_control_mode = 5
        _LOGGER.info(f"Forced discharging to grid {grid_discharge_power}")

    async def set_block_discharge_mode(self):
        charge_rate = 100
        await self.change_settings(mode=3, charge_limit=charge_rate, discharge_limit=0)
        self.storage_extended_control_mode = 6
        _LOGGER.info(f"blocked discharging")

    async def set_block_charge_mode(self):
        discharge_rate = 100
        await self.change_settings(mode=3, charge_limit=0, discharge_limit=discharge_rate)
        self.storage_extended_control_mode = 7
        _LOGGER.info(f"Block charging at {discharge_rate}")

    async def set_calibrate_mode(self):
        await self.change_settings(mode=2, charge_limit=100, discharge_limit=-100, grid_charge_power=100)
        self.storage_extended_control_mode = 8
        _LOGGER.info(f"Auto mode")
