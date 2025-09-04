#import os, sys; sys.path.append(os.path.dirname(os.path.realpath(__file__)))

"""Extended Modbus Class"""

import logging
import operator
#from datetime import timedelta, datetime
from typing import Literal
import struct
import asyncio

from pymodbus.client import AsyncModbusTcpClient
try:
    # For newer pymodbus versions (3.9.x+)
    from pymodbus.pdu.pdu import unpack_bitstring
except ImportError:
    # For older pymodbus versions (3.8.x and below)
    from pymodbus.utilities import unpack_bitstring
from pymodbus.exceptions import ModbusIOException, ConnectionException
from pymodbus import ExceptionResponse

_LOGGER = logging.getLogger(__name__)

class ExtModbusClient:

    def __init__(self, host: str, port: int, unit_id: int, timeout: int, framer:str = None) -> None:
        """Init Class"""
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self.busy = False
        if not framer is None:
            self._client = AsyncModbusTcpClient(host=host, port=port, framer=framer, timeout=timeout) 
        else:
            self._client = AsyncModbusTcpClient(host=host, port=port, timeout=timeout) 

    def close(self):
        """Disconnect client."""
        self._client.close()

    async def connect(self, retries = 3):
        """Connect client."""
        for attempts in range(retries): 
            if attempts > 0:
                _LOGGER.debug(f"Connect retry attempt: {attempts}/{retries} connecting to: {self._host}:{self._port}")
                await asyncio.sleep(.2)
            connected = await self._client.connect()
            if connected:
                break

        if not self._client.connected:
            raise Exception(f"Failed to connect to {self._host}:{self._port} retries: {retries}")
        _LOGGER.debug("successfully connected to %s:%s", self._client.comm_params.host, self._client.comm_params.port)
        return True
    
    async def _check_and_reconnect(self):
        if not self._client.connected:
            _LOGGER.warning("Modbus client is not connected, reconnecting...", exc_info=True)
            return await self.connect()
        return self._client.connected

    @property
    def connected(self) -> bool:
        return self._client.connected

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

    async def read_holding_registers(self, unit_id, address, count, retries = 3):
        """Read holding registers."""
        await self._check_and_reconnect()

        for attempt in range(retries+1):
            try:
                data = await self._client.read_holding_registers(address=address, count=count, device_id=unit_id)
            except ModbusIOException as e:
                _LOGGER.error(f'error reading registers. IO error. connected: {self._client.connected} address: {address} count: {count} unit id: {unit_id}')
                return None
            except ConnectionException as e:
                _LOGGER.error(f'error reading registers. connection exception connected: {self._client.connected} address: {address} count: {count} unit id: {unit_id} {e} ')
                return None
            except Exception as e:
                _LOGGER.error(f'error reading registers. unknown error. connected {self._client.connected} address: {address} count: {count} unit id: {unit_id} type {type(e)} error {e} ')
                return None

            if not data.isError():
                break
            else:
                if isinstance(data,ModbusIOException):
                    _LOGGER.debug(f"io error reading register retries: {attempt}/{retries} connected {self._client.connected} address: {address} count: {count} unit id: {unit_id}  error: {data} ")
                elif isinstance(data, ExceptionResponse):
                    _LOGGER.debug(f"Exception response reading register retries: {attempt}/{retries} connected {self._client.connected} address: {address} count: {count} unit id: {unit_id}  {data}")
                else:
                    _LOGGER.debug(f"Unknown data response error reading register retries: {attempt}/{retries} connected {self._client.connected} address: {address} count: {count} unit id: {unit_id}  {data}")
                await asyncio.sleep(.2) 

        if data.isError():
            _LOGGER.error(f"error reading registers. retries: {attempt}/{retries} connected {self._client.connected} register: {address} count: {count} unit id: {unit_id} retries {retries} error: {data} ")
            return None

        return data

    async def get_registers(self, unit_id, address, count, retries = 0):
        data = await self.read_holding_registers(unit_id=unit_id, address=address, count=count)
        if data is None or data.isError():
            if isinstance(data,ModbusIOException):
                if retries < 1:
                    _LOGGER.debug(f"IO Error: {data}. Retrying...")
                    return await self.get_registers(address=address, count=count, retries = retries + 1)
                else:
                    _LOGGER.error(f"error reading register: {address} count: {count} unit id: {unit_id} error: {data} ")
            else:
                _LOGGER.error(f"error reading register: {address} count: {count} unit id: {unit_id} error: {data} ")
            return None
        return data.registers

    async def write_registers(self, unit_id, address, payload):
        """Write registers."""
        await self._check_and_reconnect()
        #_LOGGER.debug(f"write registers a: {address} p: {payload} unit_id: {unit_id}")

        try:
            result = await self._client.write_registers(address=address, values=payload, device_id=unit_id)
        except ModbusIOException as e:
            raise Exception(f'write_registers: IO error {self._client.connected} {e.fcode} {e}')
        except ConnectionException as e:
            raise Exception(f'write_registers: no connection {self._client.connected} {e} ')
        except Exception as e:
            raise Exception(f'write_registers: unknown error {self._client.connected} {type(e)} {e} ')

        if result.isError():
            raise Exception(f'write_registers: data error {self._client.connected} {type(result)} {result} ')
    
        #_LOGGER.debug(f'write result {type(result)} {result}')
        return result

    def strip_escapes(self, value:str):
        if value is None:
            return
        filter = ''.join([chr(i) for i in range(0, 32)])
        return value.translate(str.maketrans('', '', filter)).strip()

    def convert_from_registers_int8(self, regs):
        return [int(regs[0] >> 8), int(regs[0] & 0xFF)]

    def convert_from_registers_int4(self, regs):
        result = [int(regs[0] >> 4) & 0x0F, int(regs[0] & 0x0F)]
        return result

    def convert_from_registers(
        cls, registers: list[int], data_type: AsyncModbusTcpClient.DATATYPE, word_order: Literal["big", "little"] = "big"
    ) -> int | float | str | list[bool] | list[int] | list[float]:
        """Convert registers to int/float/str.

        # TODO: remove this function once HA has been upgraded to later pymodbus version

        :param registers: list of registers received from e.g. read_holding_registers()
        :param data_type: data type to convert to
        :param word_order: "big"/"little" order of words/registers
        :returns: scalar or array of "data_type"
        :raises ModbusException: when size of registers is not a multiple of data_type
        """
        if not (data_len := data_type.value[1]):
            byte_list = bytearray()
            if word_order == "little":
                registers.reverse()
            for x in registers:
                byte_list.extend(int.to_bytes(x, 2, "big"))
            if data_type == cls.DATATYPE.STRING:
                trailing_nulls_begin = len(byte_list)
                while trailing_nulls_begin > 0 and not byte_list[trailing_nulls_begin - 1]:
                    trailing_nulls_begin -= 1
                byte_list = byte_list[:trailing_nulls_begin]
                return byte_list.decode("utf-8")
            return unpack_bitstring(byte_list)
        if (reg_len := len(registers)) % data_len:
            raise Exception(
                f"Registers illegal size ({len(registers)}) expected multiple of {data_len}!"
            )

        result = []
        for i in range(0, reg_len, data_len):
            regs = registers[i:i+data_len]
            if word_order == "little":
                regs.reverse()
            byte_list = bytearray()
            for x in regs:
                byte_list.extend(int.to_bytes(x, 2, "big"))
            result.append(struct.unpack(f">{data_type.value[0]}", byte_list)[0])
        return result if len(result) != 1 else result[0]

    def get_value_from_dict(self, d, k, default='NA'):
        v = d.get(k)
        if not v is None:
            return v
        return f'{default}'
    
    def convert_from_byte_uint16(self, byteArray, pos, type='BE'): 
        try:
            if type == 'BE':
                result = byteArray[pos] * 256 + byteArray[pos + 1]
            else:
                result = byteArray[pos+1] * 256 + byteArray[pos]
        except:
          return 0
        return result

    def convert_from_byte_int16(self, byteArray, pos, type='BE'): 
        try:
            if type == 'BE':
                result = byteArray[pos] * 256 + byteArray[pos + 1]
            else:
                result = byteArray[pos+1] * 256 + byteArray[pos]
            if (result > 32768):
                result -= 65536
        except:
          return 0
        return result

    def bitmask_to_strings(self, bitmask, bitmask_list, bits=16):
        strings = []
        len_list = len(bitmask_list)
        for bit in range(bits):
            if bitmask & (1<<bit):
                if bit < len_list: 
                    value = bitmask_list[bit]
                else:
                    value = f'bit {bit} undefined'
                strings.append(value)
        return strings

    def bitmask_to_string(self, bitmask, bitmask_list, default='NA', max_length=255, bits=16):
        strings = self.bitmask_to_strings(bitmask = bitmask, bitmask_list = bitmask_list, bits = bits)
        return self.strings_to_string(strings=strings, default=default, max_length=max_length)
    
    def strings_to_string(self, strings, default='NA', max_length=255):
        if len(strings):
            return ','.join(strings)[:max_length]
        return default

    def calculate_value(self, value, sf, digits=2, lower_bound = None, upper_bound = None):
        if self.is_numeric(value) and self.is_numeric(sf):
            rvalue = round(value * 10**sf, digits)
            if not lower_bound is None and rvalue < lower_bound:
                _LOGGER.error(f'calculated value: {rvalue} below lower bound {lower_bound} value: {value} sf: {sf} digits {digits}', stack_info=True)
                return None
            if not upper_bound is None and rvalue > upper_bound:
                _LOGGER.error(f'calculated value: {rvalue} above upper bound {upper_bound} value: {value} sf: {sf} digits {digits}', stack_info=True)
                return None                    
            return round(value * 10**sf, digits)
        else:
            _LOGGER.debug(f'cannot calculate non numeric value: {value} sf: {sf} digits {digits}', stack_info=True)
        return None

    def is_numeric(self, value):
        if isinstance(value, (int, float, complex)) and not isinstance(value, bool):
            return True
        return False

    def get_string_from_registers(self, regs):
        return self.strip_escapes(self._client.convert_from_registers(regs, data_type = self._client.DATATYPE.STRING))
