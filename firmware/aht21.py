"""
AHT21 temperature/humidity sensor driver (I2C, addr 0x38).

MicroPython. Uses machine.I2C. The AHT20/AHT21 share this protocol:
  - init: 0xBE, 0x08, 0x00 (calibrate) once after power-up
  - measure: 0xAC, 0x33, 0x00, then wait ~80 ms, read 7 bytes
  - byte0 = status; [1..3]=humidity(20-bit), [3..6]=temperature(20-bit); byte6=CRC8
"""

import time


class AHT21:
    def __init__(self, i2c, addr=0x38):
        self.i2c = i2c
        self.addr = addr
        time.sleep_ms(40)
        # calibrate if not already
        status = self._status()
        if not (status & 0x08):
            self.i2c.writeto(self.addr, bytes([0xBE, 0x08, 0x00]))
            time.sleep_ms(10)

    def _status(self):
        return self.i2c.readfrom(self.addr, 1)[0]

    def measure(self):
        """Return (temp_c, humidity_pct). Raises OSError on bus fault,
        ValueError on CRC mismatch."""
        self.i2c.writeto(self.addr, bytes([0xAC, 0x33, 0x00]))
        # wait for the busy bit to clear (datasheet ~80 ms)
        for _ in range(20):
            time.sleep_ms(10)
            if not (self._status() & 0x80):
                break
        d = self.i2c.readfrom(self.addr, 7)
        if _crc8(d[:6]) != d[6]:
            raise ValueError("AHT21 CRC mismatch")
        raw_h = (d[1] << 12) | (d[2] << 4) | (d[3] >> 4)
        raw_t = ((d[3] & 0x0F) << 16) | (d[4] << 8) | d[5]
        humidity = raw_h * 100.0 / 0x100000
        temp = raw_t * 200.0 / 0x100000 - 50.0
        return temp, humidity


def _crc8(data, poly=0x31, init=0xFF):
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc
