"""
HD44780 character LCD over a PCF8574 I2C backpack (addr 0x27/0x3F).

MicroPython. Standard 4-bit interface with backlight + enable strobe. Bit map on
the common backpack:  P0=RS  P1=RW  P2=EN  P3=backlight  P4..P7=D4..D7
"""

import time

_RS = 0x01
_EN = 0x04
_BL = 0x08  # backlight bit


class LCD:
    def __init__(self, i2c, addr=0x27, cols=16, rows=2):
        self.i2c = i2c
        self.addr = addr
        self.cols = cols
        self.rows = rows
        self._bl = _BL
        time.sleep_ms(50)
        # init sequence into 4-bit mode
        for v in (0x30, 0x30, 0x30, 0x20):
            self._write4(v)
            time.sleep_ms(5)
        self._cmd(0x28)  # 4-bit, 2 line, 5x8
        self._cmd(0x0C)  # display on, cursor off
        self._cmd(0x06)  # entry mode: increment
        self.clear()

    # -- low level --
    def _strobe(self, data):
        self.i2c.writeto(self.addr, bytes([data | _EN | self._bl]))
        time.sleep_us(1)
        self.i2c.writeto(self.addr, bytes([(data & ~_EN) | self._bl]))
        time.sleep_us(50)

    def _write4(self, nibble):
        self._strobe(nibble & 0xF0)

    def _send(self, value, rs):
        high = (value & 0xF0) | (rs)
        low = ((value << 4) & 0xF0) | (rs)
        self._strobe(high)
        self._strobe(low)

    def _cmd(self, value):
        self._send(value, 0)
        if value in (0x01, 0x02):
            time.sleep_ms(2)

    # -- public --
    def clear(self):
        self._cmd(0x01)

    def backlight(self, on):
        self._bl = _BL if on else 0
        self.i2c.writeto(self.addr, bytes([self._bl]))

    def move(self, col, row):
        row_off = (0x00, 0x40, 0x14, 0x54)  # 16x2 / 20x4 offsets
        self._cmd(0x80 | (col + row_off[row]))

    def put(self, text):
        for ch in text:
            self._send(ord(ch), _RS)

    def line(self, row, text):
        """Write a full row, padded/truncated to cols (no flicker-clear)."""
        self.move(0, row)
        self.put(text[: self.cols].ljust(self.cols))
