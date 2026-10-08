"""Text wvISA assembler: source text -> ``list[Instruction]``.

Supported syntax (see docs/isa/virtual-isa.md):

    label:                      ; branch target
    nop | ret | bar [id]
    add r1, r2, r3              ; integer/float ALU (by opcode family)
    movi r0, 42 / addi r1, r2, -7
    get r1, %tid
    fma r1, r2, r3, r4 | mad r1, r2, r3, r4
    min r1, r2, r3 | max r1, r2, r3 | fmin r1, r2, r3 | fmax r1, r2, r3
    fabs r1, r2 | fneg r1, r2 | ex2 r1, r2 | lg2 r1, r2 | rsqrt r1, r2 | rcp r1, r2
    cmp.eq r1, r2 / cmpi.lt r3, 0
    cvt.s32.f32 r1, r2
    ld.global.u32 r1, [r2 + 64]
    st.shared.f32 [r0 - 8], r1
    mma.bf16.acc r4, r0, r1, r4, 16, 16, 16   ; block-wide tensor MMA
    bra.lt label | bra label | bra 7
    .version 0.1 / .target wattstone   (accepted, otherwise ignored)

All errors are ``ValueError`` and carry ``line <n>`` context.
"""

import re

from .encoding import (
    CONDS,
    MMA_ELEMS_PER_TILE,
    MMA_MAX_TILES,
    MEM_SPACES,
    MEM_TYPES,
    OPCODES,
    SPECIALS,
    Instruction,
    pack_mma_imm,
)

_R3 = frozenset(
    {"add", "sub", "mul", "div", "rem", "and", "or", "xor", "shl", "shr",
     "fadd", "fsub", "fmul", "min", "max", "fmin", "fmax"}
)
_UNARY_F = frozenset({"fabs", "fneg", "ex2", "lg2", "rsqrt", "rcp"})
_IMM2 = frozenset({"addi", "muli"})
_FUSED = frozenset({"fma", "mad"})
_MMA_SUFFIXES = frozenset({"bf16", "fp16", "ta", "tb", "acc"})
_DIRECTIVES = frozenset({".version", ".target"})

_REG_RE = re.compile(r"^r(\d+)$")
_LABEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")
_MEM_RE = re.compile(r"^\[\s*(r\d+)\s*(?:([+-])\s*([^\s\]]+))?\s*\]$")


def _err(line_no: int, msg: str) -> ValueError:
    return ValueError(f"line {line_no}: {msg}")


def _parse_reg(tok: str) -> int:
    m = _REG_RE.match(tok)
    if not m:
        raise ValueError(f"expected register, got '{tok}'")
    val = int(m.group(1))
    if val > 31:
        raise ValueError(f"register {tok} out of range r0..r31")
    return val


def _parse_int(tok: str) -> int:
    try:
        return int(tok, 0)
    except ValueError:
        pass
    try:
        return int(tok, 10)  # tolerate decimal with leading zeros, e.g. "08"
    except ValueError:
        raise ValueError(f"expected integer, got '{tok}'") from None


def _parse_mem(tok: str) -> tuple[int, int]:
    m = _MEM_RE.match(tok)
    if not m:
        raise ValueError(f"expected memory operand [rX + off], got '{tok}'")
    base = _parse_reg(m.group(1))
    off = 0
    if m.group(3) is not None:
        off = _parse_int(m.group(3))
        if m.group(2) == "-":
            off = -off
    return base, off


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _parse_instruction(line_no: int, text: str, labels: dict[str, int]) -> Instruction:
    parts = text.split(None, 1)
    mnem = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    args = [a.strip() for a in rest.split(",")] if rest else []
    pieces = mnem.split(".")
    suffixes = pieces[1:]
    base = pieces[0]
    if base not in OPCODES:
        raise _err(line_no, f"unknown mnemonic '{mnem}'")
    try:
        return _build(base, suffixes, args, labels)
    except ValueError as exc:
        raise _err(line_no, str(exc)) from None


def _build(
    base: str,
    suffixes: list[str],
    args: list[str],
    labels: dict[str, int],
) -> Instruction:
    op = OPCODES[base]

    if base in ("nop", "ret"):
        _require(not args, f"'{base}' takes no operands")
        return Instruction(op=op)
    if base == "bar":
        _require(len(args) <= 1, "'bar' takes at most one operand")
        return Instruction(op=op, rc=_parse_int(args[0]) if args else 0)
    if base in _R3:
        _require(len(args) == 3, f"'{base}' expects rd, ra, rb")
        return Instruction(op=op, rd=_parse_reg(args[0]), ra=_parse_reg(args[1]),
                           rb=_parse_reg(args[2]))
    if base in _UNARY_F:
        _require(len(args) == 2, f"'{base}' expects rd, ra")
        return Instruction(op=op, rd=_parse_reg(args[0]), ra=_parse_reg(args[1]))
    if base == "mov":
        _require(len(args) == 2, "'mov' expects rd, rs")
        return Instruction(op=op, rd=_parse_reg(args[0]), rb=_parse_reg(args[1]))
    if base == "movi":
        _require(len(args) == 2, "'movi' expects rd, imm")
        return Instruction(op=op, rd=_parse_reg(args[0]), imm=_parse_int(args[1]))
    if base in _IMM2:
        _require(len(args) == 3, f"'{base}' expects rd, ra, imm")
        return Instruction(op=op, rd=_parse_reg(args[0]), ra=_parse_reg(args[1]),
                           imm=_parse_int(args[2]))
    if base == "get":
        _require(len(args) == 2, "'get' expects rd, %special")
        if args[1] not in SPECIALS:
            raise ValueError(f"unknown special register '{args[1]}'")
        return Instruction(op=op, rd=_parse_reg(args[0]), rc=SPECIALS[args[1]])
    if base in _FUSED:
        _require(len(args) == 4, f"'{base}' expects rd, ra, rb, rc")
        return Instruction(op=op, rd=_parse_reg(args[0]), ra=_parse_reg(args[1]),
                           rb=_parse_reg(args[2]), rc=_parse_reg(args[3]))
    if base == "mma":
        dtype = "bf16"
        trans_a = trans_b = accumulate = False
        for suffix in suffixes:
            if suffix in ("bf16", "fp16"):
                _require(dtype == "bf16", "'mma' takes at most one dtype suffix")
                dtype = suffix
            elif suffix in _MMA_SUFFIXES:
                if suffix == "ta":
                    trans_a = True
                elif suffix == "tb":
                    trans_b = True
                else:
                    accumulate = True
            else:
                raise ValueError(f"unknown 'mma' suffix '.{suffix}'")
        _require(len(args) == 7,
                 "'mma' expects rd, ra, rb, rc, M, N, K (elements)")
        dims = []
        for tok in args[4:]:
            elems = _parse_int(tok)
            _require(elems % MMA_ELEMS_PER_TILE == 0,
                     f"'mma' size {elems} must be a multiple of {MMA_ELEMS_PER_TILE}")
            _require(
                0 < elems <= MMA_MAX_TILES * MMA_ELEMS_PER_TILE,
                f"'mma' size {elems} exceeds {MMA_MAX_TILES * MMA_ELEMS_PER_TILE}",
            )
            dims.append(elems)
        return Instruction(
            op=op,
            rd=_parse_reg(args[0]), ra=_parse_reg(args[1]),
            rb=_parse_reg(args[2]), rc=_parse_reg(args[3]),
            imm=pack_mma_imm(*dims, dtype=dtype, trans_a=trans_a,
                             trans_b=trans_b, accumulate=accumulate),
        )
    if base in ("cmp", "cmpi"):
        _require(len(suffixes) == 1, f"'{base}' needs a condition suffix, e.g. {base}.eq")
        if suffixes[0] not in CONDS:
            raise ValueError(f"unknown condition '{suffixes[0]}'")
        cond = CONDS[suffixes[0]]
        if base == "cmp":
            _require(len(args) == 2, "'cmp' expects ra, rb")
            return Instruction(op=op, ra=_parse_reg(args[0]), rb=_parse_reg(args[1]),
                               rc=cond)
        _require(len(args) == 2, "'cmpi' expects ra, imm")
        return Instruction(op=op, ra=_parse_reg(args[0]), imm=_parse_int(args[1]),
                           rc=cond)
    if base == "cvt":
        _require(len(suffixes) == 2, "'cvt' needs .from.to type suffixes")
        _require(suffixes[0] in MEM_TYPES, f"unknown type '{suffixes[0]}'")
        _require(suffixes[1] in MEM_TYPES, f"unknown type '{suffixes[1]}'")
        _require(len(args) == 2, "'cvt' expects rd, ra")
        rc = (MEM_TYPES[suffixes[0]] << 3) | MEM_TYPES[suffixes[1]]
        return Instruction(op=op, rd=_parse_reg(args[0]), ra=_parse_reg(args[1]), rc=rc)
    if base in ("ld", "st"):
        _require(len(suffixes) == 2, f"'{base}' needs .space.type suffixes")
        _require(suffixes[0] in MEM_SPACES, f"unknown memory space '{suffixes[0]}'")
        _require(suffixes[1] in MEM_TYPES, f"unknown type '{suffixes[1]}'")
        info = MEM_SPACES[suffixes[0]] | (MEM_TYPES[suffixes[1]] << 3)
        if base == "ld":
            _require(len(args) == 2, "'ld' expects rd, [ra + off]")
            base_reg, off = _parse_mem(args[1])
            return Instruction(op=op, rd=_parse_reg(args[0]), ra=base_reg,
                               rb=info, imm=off)
        _require(len(args) == 2, "'st' expects [ra + off], rs")
        base_reg, off = _parse_mem(args[0])
        return Instruction(op=op, rd=_parse_reg(args[1]), ra=base_reg,
                           rb=info, imm=off)
    if base == "bra":
        _require(len(suffixes) <= 1, "'bra' takes at most one condition suffix")
        cond = CONDS["al"]
        if suffixes:
            if suffixes[0] not in CONDS:
                raise ValueError(f"unknown condition '{suffixes[0]}'")
            cond = CONDS[suffixes[0]]
        _require(len(args) == 1, "'bra' expects a label or instruction index")
        tok = args[0]
        if _REG_RE.match(tok):
            raise ValueError("branch target must be a label or index, not a register")
        if re.match(r"^-?\d|^0x", tok):
            target = _parse_int(tok)
            _require(target >= 0, "branch target must be >= 0")
        else:
            if tok not in labels:
                raise ValueError(f"unknown label '{tok}'")
            target = labels[tok]
        return Instruction(op=op, rc=cond, imm=target)

    raise ValueError(f"unknown mnemonic '{base}'")


def assemble(source: str) -> list[Instruction]:
    """Assemble wvISA text into a list of Instructions (two-pass, labels resolved)."""
    labels: dict[str, int] = {}
    pending: list[tuple[int, str]] = []  # (line_no, code) per instruction
    for line_no, raw in enumerate(source.splitlines(), start=1):
        line = raw
        for marker in (";", "//"):
            cut = line.find(marker)
            if cut != -1:
                line = line[:cut]
        line = line.strip()
        if not line:
            continue
        if line.startswith("."):
            directive = line.split(None, 1)[0]
            if directive not in _DIRECTIVES:
                raise _err(line_no, f"unknown directive '{directive}'")
            continue
        m = _LABEL_RE.match(line)
        if m:
            name = m.group(1)
            if name in labels:
                raise _err(line_no, f"duplicate label '{name}'")
            labels[name] = len(pending)
            line = line[m.end():].strip()
            if not line:
                continue
        pending.append((line_no, line))
    return [_parse_instruction(n, text, labels) for n, text in pending]
