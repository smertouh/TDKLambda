#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import logging
import socket
import time
from threading import Lock, Thread
from collections import deque
import asyncio

import serial
from serial import *

from TDKLambda import ms, TDKLambda
sys.path.append('../TangoUtils')
from config_logger import config_logger
from log_exception import log_exception


LF = b'\n'
DEVICE_NAME = 'IT6900'
DEVICE_FAMILY = 'IT6900 family Power Supply'
SUSPEND_TIME = 3.0


class IT6900Exception(Exception):
    pass


class IT6900:

    def __init__(self, port: str, *args, logger=None, **kwargs):
        # configure logger
        self.logger = config_logger()
        # parameters
        self.read_count = 0
        self.avg_read_time = 0.0
        self.max_read_time = 0.0
        self.suspend_to = 0.0
        self.suspend_flag = False
        self.ready = False
        self.port = port.strip()
        self.args = args
        self.kwargs = kwargs
        # create variables
        self.command = b''
        self.response = b''
        self.t0 = 0.0
        # timeouts
        self.read_timeout = 0.5
        self.min_read_time = self.read_timeout
        # default com port, id, and serial number
        self.com = None
        self.id = 'Unknown Device'
        self.sn = 0
        self.max_voltage = float('inf')
        self.max_current = float('inf')
        # create and open COM port
        self.com = self.create_com_port()
        # further initialization (for possible async use)
        # self.init()

    def create_com_port(self):
        # COM port will be openet automatically after creation
        self.com = serial.Serial(self.port, timeout=0, baudrate=115200, **self.kwargs)
        if self.com.isOpen():
            self.logger.debug('Port %s is ready', self.port)
        else:
            self.logger.error('Port %s creation error', self.port)
        return self.com

    def init(self):
        self.unsuspend()
        if not self.com.isOpen():
            self.suspend()
            return
        return
        # set device address
        self.logger.info('%s: device was not initialized properly', DEVICE_NAME)
        return
        # read device serial number
        self.sn = self.read_serial_number()
        # read device type
        self.id = self.read_device_id()
        if self.id.find('LAMBDA') >= 0:
            # determine max current and voltage from model name
            n1 = self.id.find('GEN')
            n2 = self.id.find('-')
            if 0 <= n1 < n2:
                try:
                    self.max_voltage = float(self.id[n1 + 3:n2])
                    self.max_current = float(self.id[n2 + 1:])
                except:
                    pass
        else:
            self.suspend()
            msg = 'TDKLambda: device was not initialized properly'
            self.logger.info(msg)
            return
        msg = 'TDKLambda: %s SN:%s has been initialized' % (self.id, self.sn)
        self.logger.debug(msg)

    def suspend(self, duration=SUSPEND_TIME):
        self.suspend_to = time.time() + duration
        self.suspend_flag = True
        self.logger.debug('Suspended for %5.2f sec', duration)

    def unsuspend(self):
        self.suspend_to = 0.0
        self.suspend_flag = False
        self.logger.debug('Unsuspended')

    # check if suspended and try to reset
    def is_suspended(self):
        if time.time() < self.suspend_to:  # if suspension does not expire
            return True
        # suspension expires
        if self.suspend_flag:  # if it was suspended and expires
            self.suspend_flag = False
            self.reset()
            if self.suspend_flag:  # was suspended during reset()
                return True
            else:
                return False
        else:  # it was not suspended
            return False

    def send_command(self, cmd):
        if self.is_suspended():
            self.command = cmd
            self.response = b''
            self.logger.debug('Command %s to suspended device ignored', cmd)
            return False
        try:
            # unify command
            cmd = cmd.upper().strip()
            # convert str to bytes
            if isinstance(cmd, str):
                cmd = str.encode(cmd)
            if not cmd.endswith(LF):
                cmd += LF
            self.response = b''
            t0 = time.time()
            # write command
            if not self.write(cmd):
                return False
            # read response (to LF by default)
            result = self.read_response()
            # reding time stats
            dt = time.time() - t0
            if result and dt < self.min_read_time:
                self.min_read_time = dt
            if result and dt > self.max_read_time:
                self.max_read_time = dt
            self.read_count += 1
            self.avg_read_time = (self.avg_read_time * (self.read_count - 1) + dt) / self.read_count
            self.logger.debug('%s -> %s %s %4.0f ms', cmd, self.response, result, dt*1000)
            return result
        except:
            self.logger.error('Unexpected exception %s', sys.exc_info()[0])
            self.logger.debug("", exc_info=True)
            self.suspend()
            self.response = b''
            return False

    def read(self, size=1, timeout=None):
        result = b''
        t0 = time.perf_counter()
        while len(result) < size:
            r = self.com.read(1)
            if len(r) > 0:
                result += r
            else:
                if timeout is not None and time.perf_counter() - t0 > timeout:
                    raise SerialTimeoutException('Reading timeout')
        return result

    def read_until(self, terminator=b'\r', size=None):
        result = b''
        t0 = time.perf_counter()
        while terminator not in result:
            try:
                r = self.read(1, timeout=1)
                if len(r) <= 0:
                    break
                result += r
                if size is not None and len(result) >= size:
                    break
                if time.perf_counter() - t0 > self.read_timeout:
                    break
            except:
                log_exception(self, '')
                return result
        #self.logger.debug('%s %s bytes in %4.0f ms', result, len(result), (time.perf_counter() - t0)*1000)
        return result

    def read_response(self):
        result = self.read_until(LF)
        self.response = result
        if LF not in result:
            self.logger.error('Response %s without LF', self.response)
            return False
        return True

    def write(self, cmd):
        length = 0
        result = False
        t0 = time.perf_counter()
        try:
            # reset input buffer
            self.com.reset_input_buffer()
            # write command
            length = self.com.write(cmd)
            if len(cmd) == length:
                result = True
            else:
                result = False
            dt = (time.perf_counter() - t0) * 1000.0
            self.logger.debug('%s %s bytes in %4.0f ms %s', cmd, length, dt, result)
            return result
        except SerialTimeoutException:
            self.logger.error('Writing timeout')
            dt = (time.perf_counter() - t0) * 1000.0
            self.logger.debug('%s %s bytes in %4.0f ms %s', cmd, length, dt, result)
            return False
        except:
            self.logger.error('Unexpected exception %s', sys.exc_info()[0])
            dt = (time.perf_counter() - t0) * 1000.0
            self.logger.debug('%s %s bytes in %4.0f ms %s', cmd, length, dt, result)
            self.logger.debug("", exc_info=True)
            return False

    def read_value(self, cmd, v_type=str):
        try:
            if self.send_command(cmd):
                v = v_type(self.response)
            else:
                v = None
        except:
            self.logger.info('Can not convert %s to %s', self.response, v_type)
            v = None
        return v

    def write_value(self, cmd, value):
        if isinstance(cmd, str):
            cmd = cmd.encode()
        cmd1 = cmd.upper().strip()
        cmd2 = cmd1 + b' ' + str(value).encode() + b';' + cmd1 + b'?'
        return self.send_command(cmd2)

    def read_output(self):
        if not self.send_command(b'OUTP?'):
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
        return self.write_value(b'OUTP', t_value)

    def write_voltage(self, value):
        return self.write_value(b'VOLT', value)

    def write_current(self, value):
        return self.write_value(b'CURR', value)

    def read_current(self):
        return self.read_value(b'MEAS:CURR?', float)

    def read_programmed_current(self):
        return self.read_value(b'CURR?', v_type=float)

    def read_voltage(self):
        return self.read_value(b'MEAS:VOLT?', v_type=float)

    def read_programmed_voltage(self):
        return self.read_value(b'VOLT?', float)





    def read_device_id(self):
        try:
            if self.send_command(b'*IDN?'):
                return self.response[:-1].decode()
            else:
                return 'Unknown Device'
        except:
            return 'Unknown Device'

    def read_serial_number(self):
        try:
            if self.send_command(b'SN?'):
                try:
                    serial_number = int(self.response[:-1].decode())
                except:
                    serial_number = -1
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

    def check_response(self, expected=b'OK', response=None):
        if response is None:
            response = self.response
        if not response.startswith(expected):
            msg = 'Unexpected response %s (not %s)' % (response, expected)
            self.logger.info(msg)
            return False
        return True

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
                self.logger.debug('%s is not a float', reply)
                v = float('Nan')
            vals.append(v)
        if len(vals) <= 6:
            vals = [*vals, *[float('Nan')] * 6]
        return vals[:6]

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

    def reset(self):
        self.logger.debug('Resetting')
        # if port was not initialized
        if not self.com.ready:
            self.com.close()
            self.com.init()
            if self.com.ready:
                self.init()
            else:
                # suspend all devices on same port
                for d in TDKLambda.devices:
                    if d.port == self.port:
                        d.suspend()
            return
        # port is OK, find working devices on same port
        for d in TDKLambda.devices:
            if d != self and d.port == self.port and d.alive():
                self.init()
                return
        # no working devices on same port so try to recreate com port
        self.com.close()
        self.com.init()
        if self.com.ready:
            self.init()
        else:
            # suspend all devices on same port
            for d in TDKLambda.devices:
                if d.port == self.port:
                    d.suspend()
        return

    def initialized(self):
        return self.com.ready and self.id.find('LAMBDA') > 0

    def alive(self):
        return self.read_serial_number() > 0


if __name__ == "__main__":
    pd1 = IT6900("COM3")
    for i in range(5):
        t_0 = time.time()
        v1 = pd1.send_command("*IDN?")
        dt1 = int((time.time() - t_0) * 1000.0)  # ms
        print(pd1.port, 'PC? ->', v1, '%4d ms ' % dt1, '%5.3f' % pd1.min_read_time)
