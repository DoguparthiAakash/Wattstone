"""Virtual ISA (PTX-like) fixed-width encoding: 64-bit instructions.

Bit layout:

    63:56 opcode | 55:50 rd | 49:44 ra | 43:38 rb | 37:32 rc | 31:0 imm

Which fields carry registers, immediates, condition codes, memory info, ...
depends on the opcode and is declared in ``FIELDS``; both ``encode`` and
``decode`` validate against that table so that decoding is unambiguous and
``decode(encode(i)) == i`` for every valid instruction.

See docs/isa/virtual-isa.md for the normative specification.
"""

from dataclasses import dataclass

# --- Opcode table -----------------------------------------------------------

OPCODES: dict[str, int] = {
    "nop": 0x00,
    "add": 0x01,
    "sub": 0x02,
    "mul": 0x03,
    "div": 0x04,
    "rem": 0x05,
    "and": 0x06,
    "or": 0x07,
    "xor": 0x08,
    "shl": 0x09,
    "shr": 0x0A,
    "mov": 0x0B,
    "movi": 0x0C,
    "addi": 0x0D,
    "muli": 0x0E,
    "get": 0x0F,
    "fadd": 0x10,
    "fsub": 0x11,
    "fmul": 0x12,
    "fma": 0x13,
    "mad": 0x14,
    "min": 0x15,
    "max": 0x16,
    "fmin": 0x17,
    "cmp": 0x18,
    "cmpi": 0x19,
    "cvt": 0x1A,
    "fabs": 0x1B,
    "fneg": 0x1C,
    "ex2": 0x1D,
    "lg2": 0x1E,
    "rsqrt": 0x1F,
    "ld": 0x20,
    "st": 0x21,
    "fmax": 0x22,
    "rcp": 0x23,
    "bra": 0x30,
    "ret": 0x31,
    "bar": 0x32,
    "mma": 0x40,
}
MNEMONICS: dict[int, str] = {code: name for name, code in OPCODES.items()}

# --- Field vocabularies -----------------------------------------------------

CONDS: dict[str, int] = {"al": 0, "eq": 1, "ne": 2, "lt": 3, "le": 4, "gt": 5, "ge": 6}
SPECIALS: dict[str, int] = {"%tid": 0, "%ctid": 1, "%ntid": 2, "%nctid": 3}
MEM_SPACES: dict[str, int] = {"global": 0, "shared": 1, "local": 2, "constant": 3}
MEM_TYPES: dict[str, int] = {"u8": 0, "s8": 1, "u32": 2, "s32": 3, "f32": 4}

MAX_REG = 31
IMM_MIN = -(1 << 31)
IMM_MAX = (1 << 31) - 1

# --- Tensor (mma) immediate packing ------------------------------------------

#: Data formats the ME accepts for A/B operands (C/D are always f32).
MMA_DTYPES: dict[str, int] = {"bf16": 0, "fp16": 1}

#: Elements per mma tile along each axis (M/N/K must be multiples of this).
MMA_ELEMS_PER_TILE = 16

#: Maximum tile count along one axis (5-bit field).
MMA_MAX_TILES = 31


@dataclass(frozen=True)
class MMAInfo:
    """Decoded ``mma`` immediate: tile sizes in elements plus shape flags.

    A is (M, K) row-major (or (K, M) when ``trans_a``, i.e. Aᵀ stored);
    B is (K, N) row-major (or (N, K) when ``trans_b``). C/D are (M, N)
    f32 row-major. A/B elements are 2 bytes (bf16/fp16), C/D are f32.
    """

    m: int
    n: int
    k: int
    dtype: str
    trans_a: bool
    trans_b: bool
    accumulate: bool


def pack_mma_imm(
    m: int,
    n: int,
    k: int,
    *,
    dtype: str = "bf16",
    trans_a: bool = False,
    trans_b: bool = False,
    accumulate: bool = False,
) -> int:
    """Pack mma geometry into the 32-bit immediate (canonical form).

    Layout: bits[4:0] M/16, [9:5] N/16, [14:10] K/16, [16:15] dtype,
    bit 17 trans_a, bit 18 trans_b, bit 19 accumulate; bits[31:20] zero
    so the encoding stays injective under the signed-imm decode.
    """
    for name, elems in (("M", m), ("N", n), ("K", k)):
        if elems <= 0 or elems % MMA_ELEMS_PER_TILE or \
                elems > MMA_MAX_TILES * MMA_ELEMS_PER_TILE:
            raise ValueError(
                f"mma {name}={elems} must be a multiple of "
                f"{MMA_ELEMS_PER_TILE} and at most "
                f"{MMA_MAX_TILES * MMA_ELEMS_PER_TILE}"
            )
    if dtype not in MMA_DTYPES:
        raise ValueError(f"mma dtype must be one of {sorted(MMA_DTYPES)}, got {dtype!r}")
    return (
        (m // MMA_ELEMS_PER_TILE)
        | (n // MMA_ELEMS_PER_TILE) << 5
        | (k // MMA_ELEMS_PER_TILE) << 10
        | MMA_DTYPES[dtype] << 15
        | int(trans_a) << 17
        | int(trans_b) << 18
        | int(accumulate) << 19
    )


def unpack_mma_imm(imm: int) -> MMAInfo:
    """Decode an mma immediate (inverse of :func:`pack_mma_imm`). Raises ValueError."""
    if not 0 <= imm <= 0xFFFFFFFF:
        raise ValueError(f"mma immediate {imm} out of range")
    if imm >> 20:
        raise ValueError(f"mma immediate 0x{imm:08x} has reserved bits set")
    names = sorted(MMA_DTYPES, key=MMA_DTYPES.get)  # type: ignore[arg-type]
    dtype_id = (imm >> 15) & 3
    if dtype_id >= len(names):
        raise ValueError(f"mma immediate 0x{imm:08x} uses a reserved dtype")
    mt, nt, kt = imm & 31, (imm >> 5) & 31, (imm >> 10) & 31
    if 0 in (mt, nt, kt):
        raise ValueError(f"mma immediate 0x{imm:08x} has a zero tile count")
    return MMAInfo(
        m=mt * MMA_ELEMS_PER_TILE,
        n=nt * MMA_ELEMS_PER_TILE,
        k=kt * MMA_ELEMS_PER_TILE,
        dtype=names[dtype_id],
        trans_a=bool(imm & (1 << 17)),
        trans_b=bool(imm & (1 << 18)),
        accumulate=bool(imm & (1 << 19)),
    )

# Per-mnemonic field kinds. "zero" means the field must be 0 on encode and
# is validated as 0 on decode (canonical form -> injective roundtrip).
_KINDS = ("rd", "ra", "rb", "rc", "imm")
_REG3 = {"rd": "reg", "ra": "reg", "rb": "reg", "rc": "zero", "imm": "zero"}
_UNARY = {"rd": "reg", "ra": "reg", "rb": "zero", "rc": "zero", "imm": "zero"}
_FIELDS: dict[str, dict[str, str]] = {
    "nop": dict.fromkeys(_KINDS, "zero"),
    "add": _REG3, "sub": _REG3, "mul": _REG3, "div": _REG3, "rem": _REG3,
    "and": _REG3, "or": _REG3, "xor": _REG3, "shl": _REG3, "shr": _REG3,
    "fadd": _REG3, "fsub": _REG3, "fmul": _REG3,
    "mov": {"rd": "reg", "ra": "zero", "rb": "reg", "rc": "zero", "imm": "zero"},
    "movi": {"rd": "reg", "ra": "zero", "rb": "zero", "rc": "zero", "imm": "imm"},
    "addi": {"rd": "reg", "ra": "reg", "rb": "zero", "rc": "zero", "imm": "imm"},
    "muli": {"rd": "reg", "ra": "reg", "rb": "zero", "rc": "zero", "imm": "imm"},
    "get": {"rd": "reg", "ra": "zero", "rb": "zero", "rc": "special", "imm": "zero"},
    "fma": dict.fromkeys(("rd", "ra", "rb", "rc"), "reg") | {"imm": "zero"},
    "mad": dict.fromkeys(("rd", "ra", "rb", "rc"), "reg") | {"imm": "zero"},
    # Comparisons/selects and unary f32 ops (rd = f(ra)); ``fmax`` shares the
    # 3-register format.
    "min": _REG3, "max": _REG3, "fmin": _REG3, "fmax": _REG3,
    "fabs": _UNARY, "fneg": _UNARY, "ex2": _UNARY, "lg2": _UNARY,
    "rsqrt": _UNARY, "rcp": _UNARY,
    "cmp": {"rd": "zero", "ra": "reg", "rb": "reg", "rc": "cond", "imm": "zero"},
    "cmpi": {"rd": "zero", "ra": "reg", "rb": "zero", "rc": "cond", "imm": "imm"},
    "cvt": {"rd": "reg", "ra": "reg", "rb": "zero", "rc": "types", "imm": "zero"},
    "ld": {"rd": "reg", "ra": "reg", "rb": "meminfo", "rc": "zero", "imm": "imm"},
    "st": {"rd": "reg", "ra": "reg", "rb": "meminfo", "rc": "zero", "imm": "imm"},
    "bra": {"rd": "zero", "ra": "zero", "rb": "zero", "rc": "cond", "imm": "target"},
    "ret": dict.fromkeys(_KINDS, "zero"),
    "bar": {"rd": "zero", "ra": "zero", "rb": "zero", "rc": "barid", "imm": "zero"},
    # Block-wide tensor MMA: rd/ra/rb/rc hold scratchpad byte offsets of
    # D/A/B/C; the immediate packs the tile geometry (see pack_mma_imm).
    "mma": {"rd": "reg", "ra": "reg", "rb": "reg", "rc": "reg", "imm": "mmainfo"},
}
# Alias for readers: normative table for encoding.
FIELDS: dict[str, dict[str, str]] = _FIELDS


# --- Instruction ------------------------------------------------------------

@dataclass(frozen=True)
class Instruction:
    """One decoded/assembled vISA instruction (fields as per FIELDS kinds)."""

    op: int
    rd: int = 0
    ra: int = 0
    rb: int = 0
    rc: int = 0
    imm: int = 0


def _check_field(name: str, kind: str, value: int) -> None:
    if kind == "zero":
        if value != 0:
            raise ValueError(f"field {name} must be zero for this opcode, got {value}")
    elif kind == "reg":
        if not 0 <= value <= MAX_REG:
            raise ValueError(f"register {name}={value} out of range 0..{MAX_REG}")
    elif kind == "imm":
        if not IMM_MIN <= value <= IMM_MAX:
            raise ValueError(f"immediate {value} out of int32 range")
    elif kind == "target":
        if not 0 <= value <= IMM_MAX:
            raise ValueError(f"branch target {value} out of range")
    elif kind == "cond":
        if value not in CONDS.values():
            raise ValueError(f"condition code {value} out of range")
    elif kind == "special":
        if value not in SPECIALS.values():
            raise ValueError(f"special register id {value} out of range")
    elif kind == "types":
        if (value >> 3) not in MEM_TYPES.values() or (value & 7) not in MEM_TYPES.values():
            raise ValueError(f"conversion types {value} invalid")
    elif kind == "meminfo":
        if (value & 7) not in MEM_SPACES.values() or (value >> 3) not in MEM_TYPES.values():
            raise ValueError(f"memory space/type info {value} invalid")
    elif kind == "barid":
        if not 0 <= value <= 7:
            raise ValueError(f"barrier id {value} out of range 0..7")
    elif kind == "mmainfo":
        unpack_mma_imm(value & 0xFFFFFFFF)
    else:  # pragma: no cover - developer error in FIELDS table
        raise TypeError(f"unknown field kind {kind!r}")


def encode(instr: Instruction) -> int:
    """Encode an instruction into a 64-bit unsigned word. Raises ValueError."""
    try:
        mnemonic = MNEMONICS[instr.op]
    except KeyError as exc:
        raise ValueError(f"unknown opcode 0x{instr.op:02x}") from exc
    fields = FIELDS[mnemonic]
    values = {"rd": instr.rd, "ra": instr.ra, "rb": instr.rb, "rc": instr.rc,
              "imm": instr.imm}
    for name in _KINDS:
        _check_field(name, fields[name], values[name])
    imm_bits = instr.imm & 0xFFFFFFFF
    return (
        (instr.op & 0xFF) << 56
        | (instr.rd & 0x3F) << 50
        | (instr.ra & 0x3F) << 44
        | (instr.rb & 0x3F) << 38
        | (instr.rc & 0x3F) << 32
        | imm_bits
    )


def decode(word: int) -> Instruction:
    """Decode a 64-bit unsigned word into an Instruction. Raises ValueError."""
    if not 0 <= word < (1 << 64):
        raise ValueError(f"word 0x{word:x} does not fit 64 bits")
    op = (word >> 56) & 0xFF
    try:
        mnemonic = MNEMONICS[op]
    except KeyError as exc:
        raise ValueError(f"unknown opcode 0x{op:02x}") from exc
    rd = (word >> 50) & 0x3F
    ra = (word >> 44) & 0x3F
    rb = (word >> 38) & 0x3F
    rc = (word >> 32) & 0x3F
    raw_imm = word & 0xFFFFFFFF
    imm = raw_imm - (1 << 32) if raw_imm & 0x80000000 else raw_imm
    fields = FIELDS[mnemonic]
    for name, value in (("rd", rd), ("ra", ra), ("rb", rb), ("rc", rc), ("imm", imm)):
        _check_field(name, fields[name], value)
    return Instruction(op=op, rd=rd, ra=ra, rb=rb, rc=rc, imm=imm)
