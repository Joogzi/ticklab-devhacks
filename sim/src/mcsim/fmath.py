"""Java float/double helpers: f32 rounding and Minecraft's table-based sin/cos."""
import math
import struct

_pack = struct.Struct("<f")


def f32(x: float) -> float:
    """Round a Python float (double) to the nearest Java float, returned as a double."""
    return _pack.unpack(_pack.pack(x))[0]


def fmul(a: float, b: float) -> float:
    return f32(a * b)


def fdiv(a: float, b: float) -> float:
    return f32(a / b)


def fadd(a: float, b: float) -> float:
    return f32(a + b)


def fsqrt(a: float) -> float:
    return f32(math.sqrt(a))


SIN_SCALE = 10430.378350470453  # 65536 / (2*pi)
_SIN = None


def _table():
    global _SIN
    if _SIN is None:
        _SIN = [f32(math.sin(i / SIN_SCALE)) for i in range(65536)]
    return _SIN


def _java_long(x: float) -> int:
    return int(x)  # Java d2l truncates toward zero (no NaN/inf here)


def mth_sin(v: float) -> float:
    return _table()[_java_long(v * SIN_SCALE) & 65535]


def mth_cos(v: float) -> float:
    return _table()[_java_long(v * SIN_SCALE + 16384.0) & 65535]


DEG_TO_RAD_F = f32(0.017453292)
