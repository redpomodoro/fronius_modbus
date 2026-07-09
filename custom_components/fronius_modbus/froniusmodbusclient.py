#import os, sys; sys.path.append(os.path.dirname(os.path.realpath(__file__)))

"""BYD Battery Box Class"""

import asyncio
import logging
from typing import Optional, Literal
from .extmodbusclient import ExtModbusClient
import requests

from .froniusmodbusclient_const import (
    # Sunspec models
    SUNSPEC_START_ADDRESS,
    SUNSPEC_COMMON_MODEL,
    SUNSPEC_INVERTER_MODEL_101,
    SUNSPEC_INVERTER_MODEL_103,
    SUNSPEC_NAMEPLATE_MODEL,
    SUNSPEC_SETTINGS_MODEL,
    SUNSPEC_STATUS_MODEL,
    SUNSPEC_CONTROLS_MODEL,
    SUNSPEC_STORAGE_MODEL,
    SUNSPEC_MPPT_MODEL,
    SUNSPEC_METER_MODEL_201,
    SUNSPEC_METER_MODEL_202,
    SUNSPEC_METER_MODEL_203,
    SUNSPEC_METER_MODEL_204,
    SUNSPEC_END_MODEL,
    # MPPT offsets
    MPPT_HEADER_LENGTH,
    MPPT_MODULE_LENGTH,
    # Storage offsets
    STORAGE_CONTROL_MODE_OFFSET,
    MINIMUM_RESERVE_OFFSET,
    DISCHARGE_RATE_OFFSET,
    CHARGE_RATE_OFFSET,
    # Dictionaries
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
        self.mppt_block_length = 0
        self.num_mppt_modules = 0
        self.max_charge_rate_w = 11000
        self.max_discharge_rate_w = 11000
        self._grid_frequency = 50
        self._grid_frequency_lower_bound = self._grid_frequency - 0.2
        self._grid_frequency_upper_bound = self._grid_frequency + 0.2

        self._inverter_frequency_lower_bound = self._grid_frequency - 5
        self._inverter_frequency_upper_bound = self._grid_frequency + 5

        self.data = {}
        self.sunspec_models = {}
        self.sunspec_meter_models = {}

    async def _discover_sunspec_models(self):
        """Discovers all sunspec models"""
        # find SunS marker
        suns_marker = await self.get_registers(unit_id=self._inverter_unit_id, address=SUNSPEC_START_ADDRESS, count=2)
        if suns_marker is None:
            _LOGGER.error(f"Could not find suns_marker at address {SUNSPEC_START_ADDRESS}")
            return
        
        if self.get_string_from_registers(suns_marker) != "SunS":
            _LOGGER.error(f"No SunS marker found at address {SUNSPEC_START_ADDRESS}")
            return
        else:
            _LOGGER.debug(f"Found SunS marker at address {SUNSPEC_START_ADDRESS}")

        # read common model
        offset = SUNSPEC_START_ADDRESS + 2
        model_id_regs = await self.get_registers(unit_id=self._inverter_unit_id, address=offset, count=1)
        model_len_regs = await self.get_registers(unit_id=self._inverter_unit_id, address=offset+1, count=1)
        if not model_id_regs or not model_len_regs:
            _LOGGER.error(f"Could not read common model details at address {offset}")
            return
        model_id = model_id_regs[0]
        model_len = model_len_regs[0]

        if model_id != SUNSPEC_COMMON_MODEL:
            _LOGGER.error(f"Expected common model not found at address {offset}")
            return
        else:
            _LOGGER.debug(f"Found common model at address {offset} with length {model_len}")
        
        self.sunspec_models[model_id] = {'address': offset, 'len': model_len}
        
        offset += model_len + 2

        # discover all other models
        while model_id != SUNSPEC_END_MODEL:
            model_id_regs = await self.get_registers(unit_id=self._inverter_unit_id, address=offset, count=1)
            model_len_regs = await self.get_registers(unit_id=self._inverter_unit_id, address=offset+1, count=1)
            if not model_id_regs or not model_len_regs:
                _LOGGER.error(f"Could not read model details at address {offset}")
                break
            model_id = model_id_regs[0]
            model_len = model_len_regs[0]
            
            if model_id != SUNSPEC_END_MODEL:
                _LOGGER.debug(f"Found model {model_id} at address {offset} with length {model_len}")
                self.sunspec_models[model_id] = {'address': offset, 'len': model_len}

            offset += model_len + 2
        
        _LOGGER.debug(f"Finished sunspec discovery, found models: {self.sunspec_models}")

    async def _discover_meter_models(self):
        """Discovers all sunspec models for all configured meters"""
        for meter_unit_id in self._meter_unit_ids:
            # find SunS marker
            suns_marker = await self.get_registers(unit_id=meter_unit_id, address=SUNSPEC_START_ADDRESS, count=2)
            if suns_marker is None:
                _LOGGER.error(f"Could not find suns_marker for meter {meter_unit_id} at address {SUNSPEC_START_ADDRESS}")
                continue
            
            if self.get_string_from_registers(suns_marker) != "SunS":
                _LOGGER.error(f"No SunS marker found for meter {meter_unit_id} at address {SUNSPEC_START_ADDRESS}")
                continue
            else:
                _LOGGER.debug(f"Found SunS marker for meter {meter_unit_id} at address {SUNSPEC_START_ADDRESS}")

            # read common model
            offset = SUNSPEC_START_ADDRESS + 2
            model_id_regs = await self.get_registers(unit_id=meter_unit_id, address=offset, count=1)
            model_len_regs = await self.get_registers(unit_id=meter_unit_id, address=offset+1, count=1)
            if not model_id_regs or not model_len_regs:
                _LOGGER.error(f"Could not read common model details for meter {meter_unit_id} at address {offset}")
                continue
            model_id = model_id_regs[0]
            model_len = model_len_regs[0]

            if model_id != SUNSPEC_COMMON_MODEL:
                _LOGGER.error(f"Expected common model not found for meter {meter_unit_id} at address {offset}")
                continue
            else:
                _LOGGER.debug(f"Found common model for meter {meter_unit_id} at address {offset} with length {model_len}")
            
            self.sunspec_meter_models[meter_unit_id] = {}
            self.sunspec_meter_models[meter_unit_id][model_id] = {'address': offset, 'len': model_len}
            
            offset += model_len + 2

            # discover all other models
            while model_id != SUNSPEC_END_MODEL:
                model_id_regs = await self.get_registers(unit_id=meter_unit_id, address=offset, count=1)
                model_len_regs = await self.get_registers(unit_id=meter_unit_id, address=offset+1, count=1)
                if not model_id_regs or not model_len_regs:
                    _LOGGER.error(f"Could not read model details for meter {meter_unit_id} at address {offset}")
                    break
                model_id = model_id_regs[0]
                model_len = model_len_regs[0]
                
                if model_id != SUNSPEC_END_MODEL:
                    _LOGGER.debug(f"Found model {model_id} for meter {meter_unit_id} at address {offset} with length {model_len}")
                    self.sunspec_meter_models[meter_unit_id][model_id] = {'address': offset, 'len': model_len}

                offset += model_len + 2
            
            _LOGGER.debug(f"Finished sunspec discovery for meter {meter_unit_id}, found models: {self.sunspec_meter_models[meter_unit_id]}")

    async def init_data(self):
        await self.connect()
        
        await self._discover_sunspec_models()

        try: 
            result = await self.read_device_info_data(prefix='i_', unit_id=self._inverter_unit_id)
        except Exception as e:
            _LOGGER.error(f"Error reading inverter info {self._host}:{self._port} unit id: {self._inverter_unit_id}", exc_info=True)
            raise Exception(f"Error reading inverter info unit id: {self._inverter_unit_id}")
        if result == False:
            _LOGGER.error(f"Empty inverter info {self._host}:{self._port} unit id: {self._inverter_unit_id}")
            raise Exception(f"Empty inverter info unit id: {self._inverter_unit_id}")

        if SUNSPEC_MPPT_MODEL in self.sunspec_models:
            self.mppt_configured = True
            mppt_model = self.sunspec_models[SUNSPEC_MPPT_MODEL]
            try:
                # get number of mppt modules, offset 8 in mppt model
                num_mppt_modules_reg = await self.get_registers(unit_id=self._inverter_unit_id, address=mppt_model['address'] + 2 + 6, count=1)
                if num_mppt_modules_reg:
                    self.num_mppt_modules = num_mppt_modules_reg[0]
                    self.mppt_block_length = mppt_model['len']
                    _LOGGER.debug(f"Detected {self.num_mppt_modules} MPPT modules, block length is {self.mppt_block_length}")
                    if self.mppt_block_length != (MPPT_HEADER_LENGTH + self.num_mppt_modules * MPPT_MODULE_LENGTH):
                        _LOGGER.warning(
                            f"MPPT block length ({self.mppt_block_length}) does not match the expected length for {self.num_mppt_modules} modules. "
                            f"Expected {MPPT_HEADER_LENGTH + self.num_mppt_modules * MPPT_MODULE_LENGTH}. "
                        )
                        max_safe = max(0, (self.mppt_block_length - MPPT_HEADER_LENGTH) // MPPT_MODULE_LENGTH)
                        self.num_mppt_modules = min(self.num_mppt_modules, max_safe)
                else:
                    _LOGGER.warning("Could not read number of MPPT modules. Using defaults.")
                    self.num_mppt_modules = 0
                    self.mppt_block_length = 0
            except Exception as e:
                _LOGGER.warning(f"Error while determining MPPT modules: {e}. Using defaults.")
                self.num_mppt_modules = 0
                self.mppt_block_length = 0

        if SUNSPEC_STORAGE_MODEL in self.sunspec_models:
            self.storage_configured = True
            _LOGGER.debug(f"Storage is configured")

        await self._discover_meter_models()

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
        if unit_id in self.sunspec_meter_models:
            common_model = self.sunspec_meter_models[unit_id][SUNSPEC_COMMON_MODEL]
        else:
            common_model = self.sunspec_models[SUNSPEC_COMMON_MODEL]

        regs = await self.get_registers(unit_id=unit_id, address=common_model['address'] + 2, count=65)
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
        if SUNSPEC_INVERTER_MODEL_101 in self.sunspec_models:
            inverter_model = self.sunspec_models[SUNSPEC_INVERTER_MODEL_101]
        elif SUNSPEC_INVERTER_MODEL_103 in self.sunspec_models:
            inverter_model = self.sunspec_models[SUNSPEC_INVERTER_MODEL_103]
        else:
            _LOGGER.warning("No inverter model found")
            return False

        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=inverter_model['address'] + 2, count=inverter_model['len'])
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
        status_vendor = FRONIUS_INVERTER_STATUS.get(StVnd)
        if status_vendor is None:
            _LOGGER.warning(f"Unknown inverter status {StVnd}")
            status_vendor = "Unknown"
        self.data["statusvendor"] = status_vendor
        self.data["statusvendor_id"] = StVnd
        #self.data["events1"] = self.bitmask_to_string(EvtVnd1,INVERTER_EVENTS,default='None',bits=32)  
        self.data["events2"] = self.bitmask_to_string(EvtVnd2,INVERTER_EVENTS,default='None',bits=32)  

        return True

    async def read_inverter_nameplate_data(self):
        """start reading storage data"""
        if SUNSPEC_NAMEPLATE_MODEL in self.sunspec_models:
            nameplate_model = self.sunspec_models[SUNSPEC_NAMEPLATE_MODEL]
        else:
            _LOGGER.warning("No nameplate model found")
            return False

        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=nameplate_model['address'] + 2, count=nameplate_model['len'])
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

        if DERTyp == 82 and SUNSPEC_STORAGE_MODEL in self.sunspec_models:
            self.storage_configured = True
        self.data['WHRtg'] = WHRtg
        self.data['MaxChaRte'] = MaxChaRte
        self.data['MaxDisChaRte'] = MaxDisChaRte
    
        self.max_charge_rate_w = MaxChaRte
        self.max_discharge_rate_w = MaxDisChaRte

        return True

    async def read_inverter_status_data(self):
        if SUNSPEC_STATUS_MODEL not in self.sunspec_models:
            return False
        status_model = self.sunspec_models[SUNSPEC_STATUS_MODEL]
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=status_model['address'] + 2, count=status_model['len'])
        if regs is None:
            return False

        PVConn = self._client.convert_from_registers(regs[0:1], data_type = self._client.DATATYPE.UINT16)
        StorConn = self._client.convert_from_registers(regs[1:2], data_type = self._client.DATATYPE.UINT16)
        ECPConn = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.UINT16)

        StActCtl = self._client.convert_from_registers(regs[33:35], data_type = self._client.DATATYPE.UINT32)
        
        pv_connection = CONNECTION_STATUS_CONDENSED.get(PVConn)
        if pv_connection is None:
            _LOGGER.warning(f"Unknown pv connection status {PVConn}")
            pv_connection = "Unknown"
        self.data['pv_connection'] = pv_connection

        storage_connection = CONNECTION_STATUS_CONDENSED.get(StorConn)
        if storage_connection is None:
            _LOGGER.warning(f"Unknown storage connection status {StorConn}")
            storage_connection = "Unknown"
        self.data['storage_connection'] = storage_connection

        ecp_connection = ECP_CONNECTION_STATUS.get(ECPConn)
        if ecp_connection is None:
            _LOGGER.warning(f"Unknown ecp connection status {ECPConn}")
            ecp_connection = "Unknown"
        self.data['ecp_connection'] = ecp_connection
        self.data['inverter_controls'] = self.bitmask_to_string(StActCtl, INVERTER_CONTROLS, 'Normal')  

        return True

    async def read_inverter_model_settings_data(self):
        if SUNSPEC_SETTINGS_MODEL not in self.sunspec_models:
            return False
        settings_model = self.sunspec_models[SUNSPEC_SETTINGS_MODEL]
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=settings_model['address'] + 2, count=settings_model['len'])
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
        if SUNSPEC_CONTROLS_MODEL not in self.sunspec_models:
            return False
        controls_model = self.sunspec_models[SUNSPEC_CONTROLS_MODEL]
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=controls_model['address'] + 2, count=controls_model['len'])
        if regs is None:
            return False

        Conn = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.UINT16)
        WMaxLim_Ena = self._client.convert_from_registers(regs[7:8], data_type = self._client.DATATYPE.UINT16)
        OutPFSet_Ena = self._client.convert_from_registers(regs[12:13], data_type = self._client.DATATYPE.UINT16)
        VArPct_Ena = self._client.convert_from_registers(regs[20:21], data_type = self._client.DATATYPE.INT16)

        conn_status = CONTROL_STATUS.get(Conn)
        if conn_status is None:
            _LOGGER.warning(f"Unknown control status {Conn}")
            conn_status = "Unknown"
        self.data['Conn'] = conn_status

        wmaxlim_ena_status = CONTROL_STATUS.get(WMaxLim_Ena)
        if wmaxlim_ena_status is None:
            _LOGGER.warning(f"Unknown control status {WMaxLim_Ena}")
            wmaxlim_ena_status = "Unknown"
        self.data['WMaxLim_Ena'] = wmaxlim_ena_status

        outpfset_ena_status = CONTROL_STATUS.get(OutPFSet_Ena)
        if outpfset_ena_status is None:
            _LOGGER.warning(f"Unknown control status {OutPFSet_Ena}")
            outpfset_ena_status = "Unknown"
        self.data['OutPFSet_Ena'] = outpfset_ena_status

        varpct_ena_status = CONTROL_STATUS.get(VArPct_Ena)
        if varpct_ena_status is None:
            _LOGGER.warning(f"Unknown control status {VArPct_Ena}")
            varpct_ena_status = "Unknown"
        self.data['VArPct_Ena'] = varpct_ena_status

        return True

    async def read_mppt_data(self):
        if not self.mppt_configured:
            return False
            
        mppt_model = self.sunspec_models[SUNSPEC_MPPT_MODEL]
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=mppt_model['address'] + 2, count=mppt_model['len'])
        if regs is None:
            return False

        DCW_SF = self._client.convert_from_registers(regs[2:3], data_type = self._client.DATATYPE.INT16)
        DCWH_SF = self._client.convert_from_registers(regs[3:4], data_type = self._client.DATATYPE.INT16)
        
        num_modules = self.num_mppt_modules

        pv_power = 0
        
        mppt_powers = []
        mppt_lftes = []

        for i in range(num_modules):
            # 8 is the header length for the mppt model, each module has a length of 20
            dcw_offset = MPPT_HEADER_LENGTH + 11 + i * MPPT_MODULE_LENGTH
            dcwh_offset = MPPT_HEADER_LENGTH + 12 + i * MPPT_MODULE_LENGTH
            
            power = self.calculate_value(self._client.convert_from_registers(regs[dcw_offset:dcw_offset+1], data_type = self._client.DATATYPE.UINT16), DCW_SF, 2, 0, 15000)
            lfte = self.calculate_value(self._client.convert_from_registers(regs[dcwh_offset:dcwh_offset+2], data_type = self._client.DATATYPE.UINT32), DCWH_SF)

            self.data[f'mppt{i+1}_power'] = power
            self.data[f'mppt{i+1}_lfte'] = lfte
            
            mppt_powers.append(power)
            mppt_lftes.append(lfte)

        if self.storage_configured:
            # Last two mppts are for storage
            num_pv_mppts = max(0, num_modules - 2)
            
            if len(mppt_powers) >= 2:
                charge_power = mppt_powers[num_modules-2]
                discharge_power = mppt_powers[num_modules-1]
                net_power = discharge_power - charge_power
                
                self.data['storage_power'] = net_power if discharge_power is not None and charge_power is not None else None
                self.data['storage_charge_power'] = charge_power
                self.data['storage_discharge_power'] = discharge_power
                self.data['storage_charge_lfte'] = mppt_lftes[num_modules-2]
                self.data['storage_discharge_lfte'] = mppt_lftes[num_modules-1]
            else:
                self.data['storage_power'] = None
                self.data['storage_charge_power'] = None
                self.data['storage_discharge_power'] = None
                self.data['storage_charge_lfte'] = None
                self.data['storage_discharge_lfte'] = None

        else:
            num_pv_mppts = num_modules

        for i in range(num_pv_mppts):
            if mppt_powers[i] is not None:
                pv_power += mppt_powers[i]

        self.data['pv_power'] = pv_power if pv_power > 0 else None

        return True


    async def read_inverter_storage_data(self):
        """start reading storage data"""
        if not self.storage_configured:
            return False

        storage_model = self.sunspec_models[SUNSPEC_STORAGE_MODEL]
        regs = await self.get_registers(unit_id=self._inverter_unit_id, address=storage_model['address'] + 2, count=storage_model['len'])
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
        self.data['minimum_reserve'] = self.calculate_value(minimum_reserve, -2, 2, 0, 100)
        self.data['discharging_power'] = self.calculate_value(discharge_power, -2, 2, -100, 100)
        self.data['charging_power'] = self.calculate_value(charge_power, -2, 2, -100, 100)
        self.data['soc'] = self.calculate_value(charge_state, -2, 2, 0, 100)
        self.data['max_charge'] = self.calculate_value(max_charge, 0, 0)
        self.data['storage_minimum_reserve'] = self.data['minimum_reserve']

        w_cha_max = self.data.get('max_charge', 10000)

        control_mode = self.data.get('control_mode')
        if control_mode is None or control_mode != STORAGE_CONTROL_MODE.get(storage_control_mode):
            if discharge_power >= 0:
                self.data['storage_discharge_limit'] = (discharge_power / 10000.0) * w_cha_max 
                self.data['storage_grid_charge_power'] = 0
            else: 
                self.data['storage_grid_charge_power'] = ((discharge_power * -1) / 10000.0) * w_cha_max 
                self.data['storage_discharge_limit'] = 0
            if charge_power >= 0:
                self.data['storage_charge_limit'] = (charge_power / 10000.0) * w_cha_max 
                self.data['storage_grid_discharge_power'] = 0
            else: 
                self.data['storage_grid_discharge_power'] = ((charge_power * -1) / 10000.0) * w_cha_max 
                self.data['storage_charge_limit'] = 0

            self.data['control_mode'] = STORAGE_CONTROL_MODE.get(storage_control_mode)

        # set extended storage control mode at startup
        ext_control_mode = self.data.get('ext_control_mode')
        if ext_control_mode is None:
            if storage_control_mode == 0:
                ext_control_mode = 0
            elif storage_control_mode in [1,3] and charge_power == 0:
                ext_control_mode = 7
            elif storage_control_mode in [1,3] and charge_power < 0:
                ext_control_mode = 5
            elif storage_control_mode == 1:
                ext_control_mode = 1
            elif storage_control_mode in [2,3] and discharge_power == 0:
                ext_control_mode = 6
            elif storage_control_mode in [2,3] and discharge_power < 0:
                ext_control_mode = 4
            elif storage_control_mode == 2:
                ext_control_mode = 2
            elif storage_control_mode == 3:
                ext_control_mode = 3
            self.data['ext_control_mode'] = STORAGE_EXT_CONTROL_MODE[ext_control_mode]
            self.storage_extended_control_mode = ext_control_mode

        return True

    async def read_meter_data(self, meter_prefix, unit_id):
        """start reading meter data"""
        meter_model = next((m for m in self.sunspec_meter_models.get(unit_id, {}) if m in [SUNSPEC_METER_MODEL_201, SUNSPEC_METER_MODEL_202, SUNSPEC_METER_MODEL_203, SUNSPEC_METER_MODEL_204]), None)

        if not meter_model:
            _LOGGER.warning(f"No compatible meter model found for unit id {unit_id}")
            return False

        meter_info = self.sunspec_meter_models[unit_id][meter_model]
        regs = await self.get_registers(unit_id=unit_id, address=meter_info['address'] + 2, count=meter_info['len'])
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
        if not self.storage_configured:
            return False
        storage_model = self.sunspec_models[SUNSPEC_STORAGE_MODEL]
        if not mode in [0,1,2,3]:
            _LOGGER.error(f'Attempted to set to unsupported storage control mode. Value: {mode}')
            return
        await self.write_registers(unit_id=self._inverter_unit_id, address=storage_model['address'] + 2 + STORAGE_CONTROL_MODE_OFFSET, payload=[mode])

    async def set_storage_minimum_reserve(self, minimum_reserve: float):
        if not self.storage_configured:
            return False
        storage_model = self.sunspec_models[SUNSPEC_STORAGE_MODEL]
        if minimum_reserve < 5:
            _LOGGER.error(f'Attempted to set minimum reserve below 5%. Value: {minimum_reserve}')
            return
        minimum_reserve = round(minimum_reserve * 100)
        await self.write_registers(unit_id=self._inverter_unit_id, address=storage_model['address'] + 2 + MINIMUM_RESERVE_OFFSET, payload=[minimum_reserve])



    async def set_discharge_rate_w(self, discharge_rate_w):
        if discharge_rate_w > self.max_discharge_rate_w:
            discharge_rate = 100
        elif discharge_rate_w < self.max_discharge_rate_w * -1:
            discharge_rate = -100
        else:
            discharge_rate = discharge_rate_w / self.max_discharge_rate_w * 100
        await self.set_discharge_rate(discharge_rate)

    async def set_discharge_rate(self, discharge_rate):
        if not self.storage_configured:
            return False
        storage_model = self.sunspec_models[SUNSPEC_STORAGE_MODEL]
        if discharge_rate < 0:
            discharge_rate = int(round(65536 + (discharge_rate * 100)))
        else:
            discharge_rate = int(round(discharge_rate * 100))
        await self.write_registers(unit_id=self._inverter_unit_id, address=storage_model['address'] + 2 + DISCHARGE_RATE_OFFSET, payload=[discharge_rate])

    async def set_charge_rate_w(self, charge_rate_w):
        if charge_rate_w > self.max_charge_rate_w:
            charge_rate = 100
        elif charge_rate_w < self.max_charge_rate_w * -1:
            charge_rate = -100
        else:
            charge_rate = charge_rate_w / self.max_charge_rate_w * 100
        await self.set_charge_rate(charge_rate)

    async def set_storage_grid_charge_power(self, value):
        if self.storage_extended_control_mode == 4:
            await self.set_discharge_rate_w(value * -1)
            self.data['storage_grid_charge_power'] = value
        else:
            return

    async def set_storage_grid_discharge_power(self, value):
        if self.storage_extended_control_mode == 5:
            await self.set_charge_rate_w(value * -1)
            self.data['storage_grid_discharge_power'] = value
        else:
            return
        
    async def set_storage_charge_limit(self, value):
        if self.storage_extended_control_mode in [1,3,6]:
            # only change when charge limit is used
            await self.set_charge_rate_w(value)
            self.data['storage_charge_limit'] = value
        elif self.storage_extended_control_mode in [4,5,7]:
            return
        elif self.storage_extended_control_mode in [0,2]:
            return

    async def set_storage_discharge_limit(self, value):
        if self.storage_extended_control_mode in [2,3,7]:
            # only change when discharge limit is used
            await self.set_discharge_rate_w(value)
            self.data['storage_discharge_limit'] = value
        elif self.storage_extended_control_mode in [4,5,6]:
            return
        elif self.storage_extended_control_mode in [0,1]:
            return

    async def set_charge_rate(self, charge_rate):
        if not self.storage_configured:
            return False
        storage_model = self.sunspec_models[SUNSPEC_STORAGE_MODEL]
        if charge_rate < 0:
            charge_rate = int(round(65536 + (charge_rate * 100)))
        else:
            charge_rate = int(round(charge_rate * 100))
        await self.write_registers(unit_id=self._inverter_unit_id, address=storage_model['address'] + 2 + CHARGE_RATE_OFFSET, payload=[charge_rate])

    async def change_settings(self, mode, charge_limit, discharge_limit, grid_charge_power=0, grid_discharge_power=0, minimum_reserve=None):
        await self.set_storage_control_mode(0)
        await self.set_charge_rate_w(charge_limit)
        await self.set_discharge_rate_w(discharge_limit)
        await self.set_storage_control_mode(mode)
        if self.storage_extended_control_mode == 4:
            self.data['storage_discharge_limit'] = 0
        else:
            self.data['storage_discharge_limit'] = discharge_limit
        if self.storage_extended_control_mode == 5:
            self.data['storage_charge_limit'] = 0
        else:
            self.data['storage_charge_limit'] = charge_limit
        self.data['storage_grid_charge_power'] = grid_charge_power
        self.data['storage_grid_discharge_power'] = grid_discharge_power
        if not minimum_reserve is None:
            await self.set_storage_minimum_reserve(minimum_reserve)
        
    async def restore_defaults(self):
        await self.change_settings(mode=0, charge_limit=self.max_charge_rate_w, discharge_limit=self.max_discharge_rate_w, minimum_reserve=7)
        _LOGGER.info(f"restored defaults")

    async def set_auto_mode(self):
        await self.change_settings(mode=0, charge_limit=self.max_charge_rate_w, discharge_limit=self.max_discharge_rate_w)
        self.storage_extended_control_mode = 0
        _LOGGER.info(f"Auto mode")

    async def set_charge_mode(self):
        await self.change_settings(mode=1, charge_limit=self.max_charge_rate_w, discharge_limit=self.max_discharge_rate_w)
        self.storage_extended_control_mode = 1
        _LOGGER.info(f"Set charge mode")
  
    async def set_discharge_mode(self):
        await self.change_settings(mode=2, charge_limit=self.max_charge_rate_w, discharge_limit=self.max_discharge_rate_w)
        self.storage_extended_control_mode = 2
        _LOGGER.info(f"Set discharge mode")

    async def set_charge_discharge_mode(self):
        await self.change_settings(mode=3, charge_limit=self.max_charge_rate_w, discharge_limit=self.max_discharge_rate_w)
        self.storage_extended_control_mode = 3
        _LOGGER.info(f"Set charge/discharge mode.")

    async def set_grid_charge_mode(self):
        grid_charge_power = 0
        discharge_rate = grid_charge_power * -1
        await self.change_settings(mode=2, charge_limit=self.max_charge_rate_w, discharge_limit=discharge_rate, grid_charge_power=grid_charge_power)
        self.storage_extended_control_mode = 4
        _LOGGER.info(f"Forced charging at {grid_charge_power}")

    async def set_grid_discharge_mode(self):
        grid_discharge_power = 0
        charge_rate = grid_discharge_power * -1
        await self.change_settings(mode=1, charge_limit=charge_rate, discharge_limit=self.max_discharge_rate_w, grid_discharge_power=grid_discharge_power)
        self.storage_extended_control_mode = 5
        _LOGGER.info(f"Forced discharging to grid {grid_discharge_power}")

    async def set_block_discharge_mode(self):
        charge_rate = self.max_charge_rate_w
        await self.change_settings(mode=3, charge_limit=charge_rate, discharge_limit=0)
        self.storage_extended_control_mode = 6
        _LOGGER.info(f"blocked discharging")

    async def set_block_charge_mode(self):
        discharge_rate = self.max_discharge_rate_w
        await self.change_settings(mode=3, charge_limit=0, discharge_limit=discharge_rate)
        self.storage_extended_control_mode = 7
        _LOGGER.info(f"Block charging at {discharge_rate}")

