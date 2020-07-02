import time
import asyncio
import serial
from serial import SerialTimeoutException

readTimeoutException = SerialTimeoutException('Read timeout')
writeTimeoutException = SerialTimeoutException('Write timeout')


class AsyncSerial(serial.Serial):

    def __init__(self, *args, **kwargs):
        # Should not block read or write
        kwargs['timeout'] = 0.0
        kwargs['write_timeout'] = 0.0
        super().__init__(*args, **kwargs)
        self.async_lock = asyncio.Lock()

    async def read(self, size=1, timeout=None):
        # Non locking operation. Use read_until() to prevent concurrent reading form the port.
        result = bytes()
        if size < 0:
            size = self.in_waiting
        if size == 0:
            return result
        to = serial.Timeout(timeout)
        while len(result) < size:
            d = super().read(1)
            if d:
                result += d
                to.restart()
            if to.expired():
                raise readTimeoutException
            await asyncio.sleep(0)
        return result

    async def read_until(self, terminator=b'\r', size=None, timeout=None):
        """
        Read until a termination sequence is found ('\r' by default),
        the size is exceeded or timeout occurs.
        """
        result = bytearray()
        to = serial.Timeout(timeout)
        async with self.async_lock:
            while True:
                c = super().read(1)
                if c:
                    result += c
                    if terminator in result:
                        break
                    if size is not None and len(result) >= size:
                        break
                    to.restart()
                if to.expired():
                    raise readTimeoutException
                await asyncio.sleep(0)
        return bytes(result)

    async def write(self, data, timeout=None):
        to = serial.Timeout(timeout)
        result = 0
        async with self.async_lock:
            for d in data:
                n = super().write(d)
                if n <= 0:
                    raise SerialTimeoutException('Write error')
                result += n
                if to.expired():
                    raise writeTimeoutException
                await asyncio.sleep(0)
        return result

    async def flush(self, timeout=None):
        to = serial.Timeout(timeout)
        async with self.async_lock:
            while self.in_waiting > 0:
                if to.expired():
                    raise writeTimeoutException
                await asyncio.sleep(0)

    async def reset_input_buffer(self, timeout=None):
        """Clear input buffer, discarding all that is in the buffer."""
        to = serial.Timeout(timeout)
        async with self.async_lock:
            while self.in_waiting > 0:
                super().reset_input_buffer()
                if to.expired():
                    raise SerialTimeoutException('Read buffer reset timeout')
                await asyncio.sleep(0)

    # async def reset_output_buffer(self, timeout=None):
    #     """Clear output buffer, discarding all that is in the buffer."""
    #     super().reset_output_buffer()
    #     await asyncio.sleep(0)
