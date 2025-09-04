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
    STORAGE_CONTROL_MODE_ADDRESS,
    MINIMUM_RESERVE_ADDRESS,
    DISCHARGE_RATE_ADDRESS,
    CHARGE_RATE_ADDRESS,
    EXPORT_LIMIT_RATE_ADDRESS,
    EXPORT_LIMIT_ENABLE_ADDRESS,
    CONN_ADDRESS,
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
    EXPORT_LIMIT_STATUS,
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
        self._grid_frequency = 50
        self._grid_frequency_lower_bound = self._grid_frequency - 0.2
        self._grid_frequency_upper_bound = self._grid_frequency + 0.2

        self._inverter_frequency_lower_bound = self._grid_frequency - 5
        self._inverter_frequency_upper_bound = self._grid_frequency + 5

        self.data = {}

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
        self.data["statusvendor"] = FRONIUS_INVERTER_STATUS[StVnd]
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

    async def read_inverter_status_data(self):
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=40183, count=44)
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

        self.data['Conn'] = CONTROL_STATUS[Conn]
        self.data['WMaxLim_Ena'] = CONTROL_STATUS[WMaxLim_Ena]
        self.data['OutPFSet_Ena'] = CONTROL_STATUS[OutPFSet_Ena]
        self.data['VArPct_Ena'] = CONTROL_STATUS[VArPct_Ena]

        return True

    async def read_mppt_data(self):
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=MPPT_ADDRESS, count=88)
        if regs is None:
            return False

        DCW_SF = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.INT16)
        DCWH_SF = self._client.convert_from_registers(regs[3:4], data_type = self._client.DATATYPE.INT16)
        #N = self._client.convert_from_registers(regs[6:7], data_type = self._client.DATATYPE.UINT16)
        # if N != 4:
        #     _LOGGER.error(f"Integration only supports 4 mppt modules. Found only: {N}")
        #     return

        module_1_DCW = self._client.convert_from_registers(regs[19:20], data_type = self._client.DATATYPE.UINT16)
        module_1_DCWH = self._client.convert_from_registers(regs[20:22], data_type = self._client.DATATYPE.UINT32)

        module_2_DCW = self._client.convert_from_registers(regs[39:40], data_type = self._client.DATATYPE.UINT16)
        module_2_DCWH = self._client.convert_from_registers(regs[40:42], data_type = self._client.DATATYPE.UINT32)

        mppt1_power = self.calculate_value(module_1_DCW, DCW_SF, 2, 0, 15000)
        mppt2_power = self.calculate_value(module_2_DCW, DCW_SF, 2, 0, 15000)
        if not mppt1_power is None and not mppt2_power is None:
             pv_power = mppt1_power + mppt2_power
        else:
            pv_power = None

        mppt1_lfte = self.calculate_value(module_1_DCWH, DCWH_SF)
        mppt2_lfte = self.calculate_value(module_2_DCWH, DCWH_SF)

        self.data['mppt1_power'] = mppt1_power
        self.data['mppt2_power'] = mppt2_power
        self.data['pv_power'] = pv_power
        self.data['mppt1_lfte'] = mppt1_lfte
        self.data['mppt2_lfte'] = mppt2_lfte

        if self.storage_configured:
            module_3_DCW = self._client.convert_from_registers(regs[59:60], data_type = self._client.DATATYPE.UINT16)
            module_3_DCWH = self._client.convert_from_registers(regs[60:62], data_type = self._client.DATATYPE.UINT32)

            module_4_DCW = self._client.convert_from_registers(regs[79:80], data_type = self._client.DATATYPE.UINT16)
            module_4_DCWH = self._client.convert_from_registers(regs[80:82], data_type = self._client.DATATYPE.UINT32)

            mppt3_power = self.calculate_value(module_3_DCW, DCW_SF, 2, 0, 15000)
            mppt4_power = self.calculate_value(module_4_DCW, DCW_SF, 2, 0, 15000)
            if not mppt3_power is None and not mppt4_power is None:
                storage_power = mppt4_power - mppt3_power
            else:
                storage_power = None
        
            mppt3_lfte = self.calculate_value(module_3_DCWH, DCWH_SF)
            mppt4_lfte = self.calculate_value(module_4_DCWH, DCWH_SF)

            self.data['mppt3_power'] = mppt3_power
            self.data['mppt4_power'] = mppt4_power
            self.data['storage_power'] = storage_power

            self.data['mppt3_lfte'] = mppt3_lfte
            self.data['mppt4_lfte'] = mppt4_lfte

        return True

    async def read_inverter_storage_data(self):
        """start reading storage data"""
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=STORAGE_ADDRESS, count=24)
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
        self.data['minimum_reserve'] =  self.calculate_value(minimum_reserve, -2, 2, 0, 100)
        self.data['discharging_power'] = self.calculate_value(discharge_power, -2, 2, -100, 100)
        self.data['charging_power'] = self.calculate_value(charge_power, -2, 2, -100, 100)
        self.data['soc'] = self.calculate_value(charge_state, -2, 2, 0, 100)
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

    async def read_export_limit_data(self):
        """Read export limit control registers"""
        # Read export limit rate register (40232)
        rate_regs = await self.get_registers(unit_id=self._inverter_unit_id, address=EXPORT_LIMIT_RATE_ADDRESS, count=1)
        if rate_regs is not None:
            export_limit_rate = self._client.convert_from_registers(rate_regs[0:1], data_type=self._client.DATATYPE.UINT16)
            self.data['export_limit_rate'] = export_limit_rate
        else:
            self.data['export_limit_rate'] = None

        # Read export limit enable register (40236)
        enable_regs = await self.get_registers(unit_id=self._inverter_unit_id, address=EXPORT_LIMIT_ENABLE_ADDRESS, count=1)
        if enable_regs is not None:
            export_limit_enable_raw = self._client.convert_from_registers(enable_regs[0:1], data_type=self._client.DATATYPE.UINT16)
            self.data['export_limit_enable'] = EXPORT_LIMIT_STATUS.get(export_limit_enable_raw, 'Unknown')
        else:
            self.data['export_limit_enable'] = None

        return True

    async def set_storage_control_mode(self, mode: int):
        if not mode in [0,1,2,3]:
            _LOGGER.error(f'Attempted to set to unsupported storage control mode. Value: {mode}')
            return
        await self.write_registers(unit_id=self._inverter_unit_id, address=STORAGE_CONTROL_MODE_ADDRESS, payload=[mode])

    async def set_minimum_reserve(self, minimum_reserve: float):
        if minimum_reserve < 5:
            _LOGGER.error(f'Attempted to set minimum reserve below 5%. Value: {minimum_reserve}')
            return
        minimum_reserve = round(minimum_reserve * 100)
        await self.write_registers(unit_id=self._inverter_unit_id, address=MINIMUM_RESERVE_ADDRESS, payload=[minimum_reserve])

    async def set_discharge_rate_w(self, discharge_rate_w):
        if discharge_rate_w > self.max_discharge_rate_w:
            discharge_rate = 100
        elif discharge_rate_w < self.max_discharge_rate_w * -1:
            discharge_rate = -100
        else:
            discharge_rate = discharge_rate_w / self.max_discharge_rate_w * 100
        await self.set_discharge_rate(discharge_rate)

    async def set_discharge_rate(self, discharge_rate):
        if discharge_rate < 0:
            discharge_rate = int(65536 + (discharge_rate * 100))
        else:
            discharge_rate = int(round(discharge_rate * 100))
        await self.write_registers(unit_id=self._inverter_unit_id, address=DISCHARGE_RATE_ADDRESS, payload=[discharge_rate])

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
            await self.set_discharge_rate_w(value)
            self.data['discharge_limit'] = value
        elif self.storage_extended_control_mode in [4,5,6]:
            return
        elif self.storage_extended_control_mode in [0,1]:
            return

    async def set_charge_rate(self, charge_rate):
        if charge_rate < 0:
            charge_rate =  int(65536 + (charge_rate * 100))
        else:
            charge_rate = int(round(charge_rate * 100))
        await self.write_registers(unit_id=self._inverter_unit_id, address=CHARGE_RATE_ADDRESS, payload=[charge_rate])

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

    async def set_export_limit_rate(self, rate):
        """Set export limit rate (100-10000, where 10000=100%, minimum 1%)"""
        if rate < 100:
            rate = 100
        elif rate > 10000:
            rate = 10000
        await self.write_registers(unit_id=self._inverter_unit_id, address=EXPORT_LIMIT_RATE_ADDRESS, payload=[int(rate)])
        self.data['export_limit_rate'] = rate
        _LOGGER.info(f"Set export limit rate to {rate}")

    async def set_export_limit_enable(self, enable):
        """Enable/disable export limit (0=Disabled, 1=Enabled)"""
        enable_value = 1 if enable else 0
        await self.write_registers(unit_id=self._inverter_unit_id, address=EXPORT_LIMIT_ENABLE_ADDRESS, payload=[enable_value])
        self.data['export_limit_enable'] = enable_value
        _LOGGER.info(f"Set export limit enable to {enable_value}")

    async def apply_export_limit(self, rate):
        """Apply export limit by first disabling, then setting rate, then enabling"""
        await self.set_export_limit_enable(0)  # Disable first
        await asyncio.sleep(1.0)
        await self.set_export_limit_rate(rate)  # Set new rate
        await asyncio.sleep(1.0)
        await self.set_export_limit_enable(1)  # Enable with new rate
        _LOGGER.info(f"Applied export limit: rate={rate}, enabled=1")

    async def set_conn_status(self, enable):
        """Enable/disable inverter connection (0=Disconnected/Standby, 1=Connected/Normal)"""
        conn_value = 1 if enable else 0
        await self.write_registers(unit_id=self._inverter_unit_id, address=CONN_ADDRESS, payload=[conn_value])
        self.data['Conn'] = CONTROL_STATUS[conn_value]
        _LOGGER.info(f"Set inverter connection status to {conn_value} ({'Connected' if enable else 'Disconnected/Standby'})")
