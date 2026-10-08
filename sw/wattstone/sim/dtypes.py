"""Half-width float conversions for the tensor path (wvISA ``mma``).

The ME consumes 2-byte operands (bf16/fp16) and accumulates in f32, so the
simulator needs exact conversions in both directions:

- bf16 is the top 16 bits of an f32; packing is round-to-nearest-even
  (the ``+0x7FFF + lsb`` carry trick), unpacking is exact (``<< 16``).
- fp16 is IEEE binary16; ``struct`` 'e' performs the hardware-standard
  round-to-nearest-even conversion, including inf/NaN saturation.

These match the formats in docs/architecture/compute.md (precision matrix).
"""

import struct

_F32 = struct.Struct("<f")
_U32 = struct.Struct("<I")
_F16 = struct.Struct("<e")
_U16 = struct.Struct("<H")


def f32_to_bf16(value: float) -> int:
    """float64 -> bf16 as a 16-bit uint, round-to-nearest-even."""
    bits = _U32.unpack(_F32.pack(value))[0]
    lsb = (bits >> 16) & 1
    return ((bits + 0x7FFF + lsb) >> 16) & 0xFFFF


def bf16_to_f32(bits: int) -> float:
    """bf16 bits (16-bit uint) -> float, exact."""
    return _F32.unpack(_U32.pack((bits & 0xFFFF) << 16))[0]


def f32_to_fp16(value: float) -> int:
    """float64 -> fp16 bits (16-bit uint), round-to-nearest-even."""
    return _U16.unpack(_F16.pack(value))[0]


def fp16_to_f32(bits: int) -> float:
    """fp16 bits (16-bit uint) -> float, exact (including inf/NaN)."""
    return _F16.unpack(_U16.pack(bits & 0xFFFF))[0]
