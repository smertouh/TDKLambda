#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import socket
import time
from threading import Lock
import asyncio

import serial
from serial import *
from EmulatedLambda import FakeComPort

from Counter import Counter
from TDKLambdaExceptions import *
from Async.AsyncSerial import Timeout


CR = b'\r'


class MoxaTCPComPort:
    def __init__(self, host: str, port: int = 4001):
        if ':' in host:
            n = host.find(':')
            self.host = host[:n].strip()
            try:
                self.port = int(host[n+1:].strip())
            except:
                self.port = port
        else:
            self.host = host
            self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))

    def close(self):
        self.socket.close()
        return True

    def write(self, cmd):
        self.socket.send(cmd)

    def read(self, n):
        return self.socket.recv(n)

    def isOpen(self):
        return True


class ComPort(serial.Serial):
    def __init__(self, port=None, *args, **kwargs):
        self.current_addr = -1
        self.lock = Lock()
        self.initialized = False
        #if port is None or port.upper().startswith('COM') or port.lower().startswith('tty'):
        try:
            super().__init__(port, *args, **kwargs)
            self.initialized = True
        except:
            if port.startswith('FAKE'):
                self.close = FakeComPort.close
                self.write = FakeComPort.write
                self.read = FakeComPort.read
                self.reset_input_buffer = FakeComPort.reset_input_buffer
                self.initialized = True
            else:
                self.moxa = MoxaTCPComPort(port)

    @property
    def ready(self):
        return self.initialized and self.isOpen()


class TDKLambda:
    LOG_LEVEL = logging.INFO
    EMULATE = True
    max_timeout = 0.8  # sec
    min_timeout = 0.15  # sec
    RETRIES = 3
    SUSPEND = 2.0
    sleep_small = 0.015
    devices = []
    ports = []

    def __init__(self, port: str, addr=6, checksum=False, baud_rate=9600, logger=None, auto_addr=True):
        # check device address
        if addr <= 0:
            raise wrongAddressException
        # input parameters
        self.port = port.upper().strip()
        self.addr = addr
        self.check = checksum
        self.baud = baud_rate
        self.logger = logger
        self.auto_addr = True
        # create variables
        self.command = b''
        self.response = b''
        self.error_count = Counter(3, self.suspend)
        self.time = time.time()
        self.suspend_to = time.time()
        self.suspend_flag = False
        self.retries = 0
        # timeouts
        self.read_timeout = self.min_timeout
        self.timeout_clear_input = 0.5
        # sleep timings
        self.sleep_after_write = 0.02
        self.sleep_clear_input = 0.0
        # default com port, id, and serial number
        self.com = None
        self.id = 'Unknown Device'
        self.sn = 0
        self.max_voltage = float('inf')
        self.max_current = float('inf')
        # configure logger
        self.configure_logger()
        # check if port and address are in use
        for d in TDKLambda.devices:
            if d.port == self.port and d.addr == self.addr and d != self:
                raise addressInUseException
        # create COM port
        self.create_com_port()
        #
        if self.com is None:
            msg = 'TDKLambda: %s port was not initialized' % self.port
            self.logger.info(msg)
            self.add_to_list()
            return
        #
        #if self.__class__ == TDKLambda:
        if not asyncio.iscoroutinefunction(self.init):
            self.init()

    def __del__(self):
        if self in TDKLambda.devices:
            TDKLambda.devices.remove(self)

    def configure_logger(self):
        if self.logger is None:
            self.logger = logging.getLogger(str(self))
            self.logger.propagate = False
            self.logger.setLevel(self.LOG_LEVEL)
            f_str = '%(asctime)s,%(msecs)3d %(levelname)-7s [%(process)d:%(thread)d] %(filename)s ' \
                    '%(funcName)s(%(lineno)s) ' + '%s:%d ' % (self.port, self.addr) + '%(message)s'
            log_formatter = logging.Formatter(f_str, datefmt='%H:%M:%S')
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(log_formatter)
            if not self.logger.hasHandlers():
                self.logger.addHandler(console_handler)

    def create_com_port(self):
        # if com port already exists
        for d in TDKLambda.devices:
            if d.port == self.port and d.com is not None:
                self.com = d.com
                return self.com
        # create new port
        try:
            if self.port.upper().startswith('FAKE'):
                self.com = FakeComPort(self.port)
            elif self.port.upper().startswith('COM') or self.port.lower().startswith('tty'):
                self.com = serial.Serial(self.port, baudrate=self.baud, timeout=0.0, write_timeout=0.0)
            else:
                self.com = MoxaTCPComPort(self.port)
            self.com.current_addr = -1
            self.com.lock = Lock()
            self.logger.debug('Port %s has been created', self.port)
        except:
            self.com = None
            self.logger.error('Port %s creation error', self.port)
            self.logger.debug('', exc_info=True)
        # update com for other devices with the same port
        for d in TDKLambda.devices:
            if d.port == self.port:
                d.com = self.com
        return self.com

    def init(self):
        if self.com is None:
            self.suspend()
            return
        # set device address
        response = self.set_addr()
        if not response:
            msg = 'TDKLambda: device is not initialized properly'
            self.logger.info(msg)
            self.add_to_list()
            return
        # read device type
        self.id = self.read_device_id()
        if self.id.find('LAMBDA') >= 0:
            # determine max current and voltage from model name
            n1 = self.id.find('GEN')
            n2 = self.id.find('-')
            if 0 <= n1 < n2:
                try:
                    self.max_voltage = float(self.id[n1+3:n2])
                    self.max_current = float(self.id[n2+1:])
                except:
                    pass
        # read device serial number
        self.sn = self.read_serial_number()
        # add device to list
        self.add_to_list()
        msg = 'TDKLambda: %s SN:%s has been initialized' % (self.id, self.sn)
        self.logger.debug(msg)

    def add_to_list(self):
        if self not in TDKLambda.devices:
            TDKLambda.devices.append(self)

    def read_device_id(self):
        try:
            if self._send_command(b'IDN?'):
                return self.response[:-1].decode()
            else:
                return 'Unknown Device'
        except:
            return 'Unknown Device'

    def read_serial_number(self):
        try:
            if self._send_command(b'SN?'):
                serial_number = int(self.response[:-1].decode())
                return serial_number
            else:
                return -1
        except:
            return -1

    def close_com_port(self):
        try:
            self.com.close()
        except:
            pass
        self.com = None
        self.suspend()
        for d in TDKLambda.devices:
            if d.port == self.port:
                d.com = None
                d.suspend()

    @staticmethod
    def checksum(cmd):
        s = 0
        for b in cmd:
            s += int(b)
        result = str.encode(hex(s)[-2:].upper())
        return result

    def suspend(self, duration=9.0):
        self.suspend_to = time.time() + duration
        self.suspend_flag = True
        msg = 'Suspended for %5.2f sec' % duration
        self.logger.info(msg)

    def unsuspend(self):
        self.suspend_to = 0.0
        self.suspend_flag = False
        self.logger.debug('Unsuspend')

    def is_suspended(self):
        if time.time() < self.suspend_to:   # if suspension does not expire
            return True
        else:                               # suspension expires
            if self.suspend_flag:           # if it was suspended and expires
                self.reset()
                if self.com is None:        # if initialization was not successful
                    # suspend again
                    self.suspend()
                    return True
                else:                       # initialization was successful
                    self.unsuspend()
                    return False
            else:                           # it was not suspended
                return False

    def _read(self, size=1, timeout=None):
        result = b''
        to = Timeout(timeout)
        # t0 = time.perf_counter()
        while len(result) < size:
            r = self.com.read(1)
            if len(r) > 0:
                result += r
                to.restart()
            else:
                if to.expired():
                    self.logger.debug('Read timeout')
                    raise SerialTimeoutException('Read timeout')
            # dt = (time.perf_counter() - t0) * 1000.0
            # self.logger.debug('%s %5.2f ms' % (r, dt))
        return result

    def read(self, size=1, retries=3):
        counter = 0
        result = b''
        t0 = time.time()
        while counter <= retries:
            try:
                result = self._read(size, self.read_timeout)
                dt = time.time() - t0
                self.read_timeout = max(2.0 * dt, self.min_timeout)
                #self.logger.debug('Reading timeout corrected to %5.2f s' % self.read_timeout)
                return result
            except SerialTimeoutException:
                counter += 1
                self.read_timeout = min(1.5 * self.read_timeout, self.max_timeout)
                self.logger.debug('Reading timeout increased to %5.2f s' % self.read_timeout)
            except:
                self.logger.info('Unexpected exception', exc_info=True)
                counter = retries
        return result

    def read_until(self, terminator=b'\r', size=None):
        result = b''
        t0 = time.time()
        while terminator not in result and not self.is_suspended():
            r = self.read(1)
            if len(r) <= 0:
                self.suspend()
            result += r
            if size is not None and len(result) >= size:
                break
        dt = (time.time() - t0) * 1000.0
        self.logger.debug('%s %s bytes in %4.0f ms' % (result, len(result), dt))
        return result

    def read_response(self):
        result = self.read_until(CR)
        self.response = result
        if CR not in result:
            self.logger.error('Response %s without CR' % self.response)
            self.error_count.inc()
            return False
        if not self.check:
            self.error_count.clear()
            return True
        # checksum calculation and check
        m = result.find(b'$')
        if m < 0:
            self.logger.error('No expected checksum in response')
            self.error_count.inc()
            return False
        else:
            cs = self.checksum(result[:m])
            if result[m+1:] != cs:
                self.logger.error('Incorrect checksum')
                self.error_count.inc()
                return False
            self.error_count.clear()
            self.response = result[:m]
            return True

    def check_response(self, expected=b'OK', response=None):
        if response is None:
            response = self.response
        if not response.startswith(expected):
            msg = 'Unexpected response %s (not %s)' % (response, expected)
            self.logger.info(msg)
            return False
        return True

    def clear_input_buffer(self):
        self.com.reset_input_buffer()

    def write(self, cmd):
        t0 = time.time()
        try:
            # clear input buffer
            self.clear_input_buffer()
            # write command
            #self.logger.debug('clear_input_buffer %4.0f ms' % ((time.time() - t0) * 1000.0))
            length = self.com.write(cmd)
            #time.sleep(self.sleep_after_write)
            if len(cmd) == length:
                result = True
            else:
                result = False
            self.logger.debug('%s %s bytes in %4.0f ms %s' % (cmd, length, (time.time() - t0) * 1000.0, result))
            return result
        except SerialTimeoutException:
            self.logger.error('Writing timeout')
            return False
        except:
            self.logger.error('Unexpected exception')
            self.logger.debug("", exc_info=True)
            return False

    def _send_command(self, cmd: bytes):
        self.command = cmd
        self.response = b''
        if not cmd.endswith(b'\r'):
            cmd += b'\r'
        t0 = time.time()
        # write command
        if not self.write(cmd):
            return False
        # read response (to CR by default)
        result = self.read_response()
        dt = (time.time()-t0)*1000.0
        self.logger.debug('%s -> %s %s %4.0f ms' % (cmd, self.response, result, dt))
        return result

    def send_command(self, cmd):
        if self.is_suspended():
            self.command = cmd
            self.response = b''
            return False
        try:
            # unify command
            cmd = cmd.upper().strip()
            # convert str to bytes
            if isinstance(cmd, str):
                cmd = str.encode(cmd)
            # add checksum
            if self.check:
                cs = self.checksum(cmd[:-1])
                cmd = b'%s$%s\r' % (cmd[:-1], cs)
            if self.com._current_addr != self.addr:
                result = self.set_addr()
                if not result:
                    self.suspend()
                    self.response = b''
                    return False
            result = self._send_command(cmd)
            if result:
                return True
            self.logger.warning('Repeat command %s' % cmd)
            result = self._send_command(cmd)
            if result:
                return True
            self.logger.error('Repeated command %s error' % cmd)
            self.suspend()
            self.response = b''
            return False
        except:
            self.logger.error('Unexpected exception')
            self.logger.debug("", exc_info=True)
            self.suspend()
            self.response = b''
            return b''

    def set_addr(self):
        if hasattr(self.com, '_current_addr'):
            a0 = self.com._current_addr
        else:
            a0 = -1
        result = self._send_command(b'ADR %d' % self.addr)
        if result and self.check_response(b'OK'):
            self.com._current_addr = self.addr
            self.logger.debug('Address %d -> %d' % (a0, self.addr))
            return True
        else:
            self.logger.error('Error set address %d -> %d' % (a0, self.addr))
            if self.com is not None:
                self.com._current_addr = -1
            return False

    def read_float(self, cmd):
        try:
            if not self.send_command(cmd):
                return float('Nan')
            v = float(self.response)
        except:
            self.logger.debug('%s is not a float' % self.response)
            v = float('Nan')
        return v

    def read_all(self):
        if not self.send_command(b'DVC?'):
            return [float('Nan')] * 6
        reply = self.response
        sv = reply.split(b',')
        vals = []
        for s in sv:
            try:
                v = float(s)
            except:
                self.logger.debug('%s is not a float' % reply)
                v = float('Nan')
            vals.append(v)
        if len(vals) <= 6:
            return vals
        else:
            return vals[:6]

    def read_value(self, cmd, v_type=type(str)):
        try:
            if self.send_command(cmd):
                v = v_type(self.response)
            else:
                v = None
        except:
            self.logger.info('Can not convert %s to %s' % (self.response, v_type))
            v = None
        return v

    def read_bool(self, cmd):
        if not self.send_command(cmd):
            return None
        response = self.response
        if response.upper() in (b'ON', b'1'):
            return True
        if response.upper() in (b'OFF', b'0'):
            return False
        self.check_response(response=b'Not boolean:' + response)
        return False

    def write_value(self, cmd: bytes, value, expect=b'OK'):
        cmd = cmd.upper().strip() + b' ' + str.encode(str(value))[:10] + b'\r'
        if self.send_command(cmd):
            return self.check_response(expect)
        else:
            return False

    def read_output(self):
        if not self.send_command(b'OUT?'):
            return None
        response = self.response.upper()
        if response.startswith((b'ON', b'1')):
            return True
        if response.startswith((b'OFF', b'0')):
            return False
        self.logger.info('Unexpected response %s' % response)
        return None

    def write_output(self, value):
        if value:
            t_value = 'ON'
        else:
            t_value = 'OFF'
        return self.write_value(b'OUT', t_value)

    def write_voltage(self, value):
        return self.write_value(b'PV', value)

    def write_current(self, value):
        return self.write_value(b'PC', value)

    def read_current(self):
        return self.read_value(b'MC?', v_type=float)

    def read_programmed_current(self):
        return self.read_value(b'PC?', v_type=float)

    def read_voltage(self):
        return self.read_value(b'MV?', v_type=float)

    def read_programmed_voltage(self):
        return self.read_value(b'PV?', v_type=float)

    def reset(self):
        self.logger.debug('Resetting %s' % self)
        if self.com is None:
            self.create_com_port()
            self.init()
            return
        # check working devices on same port
        for d in TDKLambda.devices:
            if d.port == self.port and d.initialized() and d != self:
                d.init()
                if d.initilized():
                    self.init()
                    return
        # no working devices on same port so try to recreate com port
        self.close_com_port()
        self.create_com_port()
        self.init()
        return

    def initialized(self):
        return self.com is not None and self.id.find('LAMBDA') > 0


if __name__ == "__main__":
    pd1 = TDKLambda("COM6", 6)
    pd2 = TDKLambda("COM6", 7)
    for i in range(5):
        t_0 = time.time()
        v1 = pd1.read_float("PC?")
        dt1 = int((time.time() - t_0) * 1000.0)    # ms
        print(pd1.port, pd1.addr, 'PC? ->', v1, '%4d ms ' % dt1, 'to=', '%5.3f' % pd1.read_timeout)
        t_0 = time.time()
        v1 = pd1.read_float("MV?")
        dt1 = int((time.time() - t_0) * 1000.0)    # ms
        print(pd1.port, pd1.addr, 'MV? ->', v1, '%4d ms ' % dt1, 'to=', '%5.3f' % pd1.read_timeout)
        t_0 = time.time()
        v1 = pd1.send_command("PV 1.0")
        dt1 = int((time.time() - t_0) * 1000.0)    # ms
        print(pd1.port, pd1.addr, 'PV? ->', v1, '%4d ms ' % dt1, 'to=', '%5.3f' % pd1.read_timeout)
        t_0 = time.time()
        v1 = pd1.read_float("PV?")
        dt1 = int((time.time() - t_0) * 1000.0)    # ms
        print(pd1.port, pd1.addr, 'PV? ->', v1, '%4d ms ' % dt1, 'to=', '%5.3f' % pd1.read_timeout)
        t_0 = time.time()
        v1 = pd1.read_all()
        dt1 = int((time.time() - t_0) * 1000.0)    # ms
        print(pd1.port, pd1.addr, 'DVC? ->', v1, '%4d ms ' % dt1, 'to=', '%5.3f' % pd1.read_timeout)
        t_0 = time.time()
        v1 = pd2.read_float("PC?")
        dt1 = int((time.time() - t_0) * 1000.0)    # ms
        print(pd2.port, pd2.addr, 'PC? ->', v1, '%4d ms ' % dt1, 'to=', '%5.3f' % pd2.read_timeout)
        t_0 = time.time()
        v1 = pd2.read_all()
        dt1 = int((time.time() - t_0) * 1000.0)    # ms
        print(pd2.port, pd2.addr, 'DVC? ->', v1, '%4d ms ' % dt1, 'to=', '%5.3f' % pd2.read_timeout)
        #time.sleep(0.1)
        #pd1.reset()
        #pd2.reset()
