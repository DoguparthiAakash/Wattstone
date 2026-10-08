"""Transaction-level SIMT execution engine for wvISA kernels.

Execution model (mirrors the RTL core, see docs/rtl-architecture.md):

- One *block* executes at a time on one tile; threads of a block execute
  in lockstep: each step, the most common program counter among live
  threads is selected (ties -> lowest pc), every live thread at that pc
  executes one instruction, threads elsewhere are masked off.
- Per-thread state: 32 registers (u32 bit patterns), NZP condition flags,
  PC, liveness. Per-block state: shared scratchpad. Per-block/thread:
  local memory (grow-on-demand, capped).
- ``bar`` is a no-op fence: the lockstep issue order already serializes
  shared-memory accesses between the barrier's neighbors.
- ``mma`` (wvISA v0.3) is a *block-wide* tensor op: it executes ONCE per
  issue round on the modeled matrix engine (sim/me_model.py), no matter
  how many threads are at that pc; operand scratchpad offsets come from
  the lowest-numbered thread at the round (hardware model: one tensor
  issue port per block). It counts as one instruction, adds ME cycles to
  ``steps`` and ME MACs to ``Stats.macs``.
- Dynamic instruction count and per-space memory traffic are recorded in
  ``Stats`` — the inputs to the power model (docs/architecture/power-thermal.md).

Division/remainder by zero is defined to yield 0 (see the ISA spec).
"""

import struct
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from ..compiler.binary import KernelImage
from ..isa.encoding import MNEMONICS, Instruction, unpack_mma_imm
from . import me_model, sfu

_MASK = 0xFFFFFFFF
_LOCAL_CAP = 1 << 20  # bytes per thread
SPACES = ("global", "shared", "local", "constant")
TYPES = ("u8", "s8", "u32", "s32", "f32")
_WIDTH = {"u8": 1, "s8": 1, "u32": 4, "s32": 4, "f32": 4}
_SPECIALS = ("%tid", "%ctid", "%ntid", "%nctid")
_SFU_OPS = {"ex2": sfu.ex2, "lg2": sfu.lg2, "rsqrt": sfu.rsqrt, "rcp": sfu.rcp}
_INT_OPS = frozenset({
    "add", "sub", "mul", "div", "rem", "and", "or", "xor", "shl", "shr",
    "mov", "movi", "addi", "muli", "get", "mad", "min", "max",
})


def _mask(value: int) -> int:
    return value & _MASK


def _signed(value: int) -> int:
    return value - (1 << 32) if value & 0x80000000 else value


def _f32(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits & _MASK))[0]


def _fbits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _trunc_div(a: int, b: int) -> int:
    if b == 0:
        return 0
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def _trunc_rem(a: int, b: int) -> int:
    if b == 0:
        return 0
    r = abs(a) % abs(b)
    return -r if a < 0 else r


def _branch_taken(cond: int, flags: int) -> bool:
    n, z, p = bool(flags & 4), bool(flags & 2), bool(flags & 1)
    return {
        0: True,      # al
        1: z,         # eq
        2: not z,     # ne
        3: n,         # lt
        4: n or z,    # le
        5: p,         # gt
        6: p or z,    # ge
    }[cond]


@dataclass
class Stats:
    """Activity counters for one kernel run (power-model inputs)."""

    instructions: int = 0
    steps: int = 0  # lockstep issue rounds == modeled cycles
    branches: int = 0
    float_ops: int = 0
    int_ops: int = 0
    macs: int = 0  # ME MACs issued by block-wide mma (power model: mac_pj)
    bytes_read: dict = field(default_factory=lambda: {s: 0 for s in SPACES})
    bytes_written: dict = field(default_factory=lambda: {s: 0 for s in SPACES})


@dataclass
class SimResult:
    """Result of a kernel run: mutated global memory plus statistics."""

    memory: bytearray
    stats: Stats
    blocks: int
    threads: int


class _Engine:
    def __init__(
        self,
        image: KernelImage,
        *,
        threads: int,
        blocks: int,
        memory: bytearray,
        scratchpad_size: int,
        constants: bytes,
        max_steps: int,
    ) -> None:
        self.code = image.code
        self.entry = image.entry
        self.threads = threads
        self.blocks = blocks
        self.memory = memory
        self.scratchpad_size = scratchpad_size
        self.constants = constants
        self.max_steps = max_steps
        self.stats = Stats()
        self.steps = 0
        self.regs = [[0] * 32 for _ in range(threads)]
        self.pc = [self.entry] * threads
        self.flags = [0] * threads
        self.alive = [True] * threads
        self.scratch = bytearray(scratchpad_size)
        self.local = [bytearray() for _ in range(threads)]
        self.block_id = 0

    # --- memory helpers ----------------------------------------------------

    def _bounds(self, space: str, addr: int, width: int, storage_len: int) -> None:
        if addr < 0 or addr + width > storage_len:
            raise ValueError(
                f"{space} memory access out of bounds at address {addr} "
                f"(width {width}, size {storage_len})"
            )

    def _load(self, space: str, addr: int, typ: str, t: int) -> int:
        width = _WIDTH[typ]
        if space == "global":
            self._bounds(space, addr, width, len(self.memory))
            raw: bytes = bytes(self.memory[addr:addr + width])
        elif space == "shared":
            self._bounds(space, addr, width, len(self.scratch))
            raw = bytes(self.scratch[addr:addr + width])
        elif space == "constant":
            self._bounds(space, addr, width, len(self.constants))
            raw = self.constants[addr:addr + width]
        else:  # local
            loc = self.local[t]
            if addr + width > len(loc):
                if addr + width > _LOCAL_CAP:
                    raise ValueError(
                        f"local memory access out of bounds at address {addr}"
                    )
                loc.extend(bytes(addr + width - len(loc)))
            raw = bytes(loc[addr:addr + width])
        self.stats.bytes_read[space] += width
        value = int.from_bytes(raw, "little")
        if typ == "s8" and value & 0x80:
            value |= 0xFFFFFF00
        return _mask(value)

    def _store(self, space: str, addr: int, typ: str, t: int, value: int) -> None:
        if space == "constant":
            raise ValueError("cannot store to constant memory")
        width = _WIDTH[typ]
        data = (value & 0xFF).to_bytes(1, "little") if width == 1 \
            else value.to_bytes(4, "little")
        if space == "global":
            self._bounds(space, addr, width, len(self.memory))
            self.memory[addr:addr + width] = data
        elif space == "shared":
            self._bounds(space, addr, width, len(self.scratch))
            self.scratch[addr:addr + width] = data
        else:  # local
            loc = self.local[t]
            if addr + width > len(loc):
                if addr + width > _LOCAL_CAP:
                    raise ValueError(
                        f"local memory access out of bounds at address {addr}"
                    )
                loc.extend(bytes(addr + width - len(loc)))
            loc[addr:addr + width] = data
        self.stats.bytes_written[space] += width

    # --- instruction execution ---------------------------------------------

    def _exec(self, instr: Instruction, t: int) -> None:
        reg = self.regs[t]
        op = MNEMONICS[instr.op]
        rd, ra, rb, rc = instr.rd, instr.ra, instr.rb, instr.rc
        next_pc = self.pc[t] + 1
        if op in ("nop", "bar"):
            pass
        elif op == "add":
            reg[rd] = _mask(reg[ra] + reg[rb])
        elif op == "sub":
            reg[rd] = _mask(reg[ra] - reg[rb])
        elif op == "mul":
            reg[rd] = _mask(reg[ra] * reg[rb])
        elif op == "div":
            reg[rd] = _mask(_trunc_div(_signed(reg[ra]), _signed(reg[rb])))
        elif op == "rem":
            reg[rd] = _mask(_trunc_rem(_signed(reg[ra]), _signed(reg[rb])))
        elif op == "and":
            reg[rd] = reg[ra] & reg[rb]
        elif op == "or":
            reg[rd] = reg[ra] | reg[rb]
        elif op == "xor":
            reg[rd] = reg[ra] ^ reg[rb]
        elif op == "shl":
            reg[rd] = _mask(reg[ra] << (reg[rb] & 31))
        elif op == "shr":
            reg[rd] = _mask(_signed(reg[ra]) >> (reg[rb] & 31))
        elif op == "mov":
            reg[rd] = reg[rb]
        elif op == "movi":
            reg[rd] = _mask(instr.imm)
        elif op == "addi":
            reg[rd] = _mask(reg[ra] + instr.imm)
        elif op == "muli":
            reg[rd] = _mask(reg[ra] * instr.imm)
        elif op == "get":
            reg[rd] = _mask(
                (t, self.block_id, self.threads, self.blocks)[rc]
            )
        elif op in ("fadd", "fsub", "fmul"):
            a, b = _f32(reg[ra]), _f32(reg[rb])
            value = {"fadd": a + b, "fsub": a - b, "fmul": a * b}[op]
            reg[rd] = _fbits(value)
            self.stats.float_ops += 1
        elif op == "min":
            a, b = _signed(reg[ra]), _signed(reg[rb])
            reg[rd] = _mask(a if a < b else b)
        elif op == "max":
            a, b = _signed(reg[ra]), _signed(reg[rb])
            reg[rd] = _mask(a if a > b else b)
        elif op in ("fmin", "fmax"):
            # Select semantics (see the ISA): rd = ra ?rb : rb on f32 order.
            a, b = _f32(reg[ra]), _f32(reg[rb])
            take_a = a < b if op == "fmin" else a > b
            reg[rd] = reg[ra] if take_a else reg[rb]
            self.stats.float_ops += 1
        elif op == "fabs":
            reg[rd] = reg[ra] & 0x7FFFFFFF
            self.stats.float_ops += 1
        elif op == "fneg":
            reg[rd] = reg[ra] ^ 0x80000000
            self.stats.float_ops += 1
        elif op in _SFU_OPS:
            reg[rd] = _fbits(_SFU_OPS[op](_f32(reg[ra])))
            self.stats.float_ops += 1
        elif op == "fma":
            reg[rd] = _fbits(_f32(reg[ra]) * _f32(reg[rb]) + _f32(reg[rc]))
            self.stats.float_ops += 1
        elif op == "mad":
            reg[rd] = _mask(_signed(reg[ra]) * _signed(reg[rb]) + _signed(reg[rc]))
        elif op in ("cmp", "cmpi"):
            a = _signed(reg[ra])
            b = _signed(reg[instr.rb] if op == "cmp" else _mask(instr.imm))
            self.flags[t] = (int(a < b) << 2) | (int(a == b) << 1) | int(a > b)
        elif op == "cvt":
            reg[rd] = self._convert(reg[ra], (rc >> 3) & 7, rc & 7)
        elif op in ("ld", "st"):
            info = instr.rb
            space, typ = SPACES[info & 7], TYPES[(info >> 3) & 7]
            addr = reg[ra] + instr.imm  # unchecked: negative/huge -> out of bounds
            if op == "ld":
                reg[rd] = self._load(space, addr, typ, t)
            else:
                self._store(space, addr, typ, t, reg[rd])
        elif op == "bra":
            self.stats.branches += 1
            if _branch_taken(rc, self.flags[t]):
                next_pc = instr.imm
                if not 0 <= next_pc < len(self.code):
                    raise ValueError(f"branch target {next_pc} out of range")
        elif op == "ret":
            self.alive[t] = False
            next_pc = self.pc[t]
        else:  # pragma: no cover - FIELDS in encoding.py guarantees coverage
            raise ValueError(f"unexecutable opcode '{op}'")
        self.stats.instructions += 1
        if op in _INT_OPS:
            self.stats.int_ops += 1
        self.pc[t] = next_pc

    def _mma_operand(
        self, off: int, rows: int, cols: int, trans: bool, dtype: str,
        nbytes: int,
    ) -> np.ndarray:
        """Read an mma A/B operand from the scratchpad as an f32 (rows, cols)."""
        raw = bytes(self.scratch[off:off + nbytes])
        if dtype == "bf16":
            tile = np.frombuffer(raw, dtype="<u2").reshape(rows, cols)
            f32 = (tile.astype(np.uint32) << 16).view(np.float32)
        else:  # fp16
            tile = np.frombuffer(raw, dtype="<f2").reshape(rows, cols)
            f32 = tile.astype(np.float32)
        return f32.T if trans else f32

    def _exec_mma(self, instr: Instruction, at_pc: list[int]) -> None:
        """Block-wide tensor MMA (wvISA v0.3): D = (acc ? C : 0) + A @ B.

        One execution per issue round (see the module docstring); the ME
        model (sim/me_model.py) charges modeled cycles and MAC energy.
        """
        info = unpack_mma_imm(instr.imm & 0xFFFFFFFF)
        m, n, k = info.m, info.n, info.k
        elem = 2  # bf16/fp16 operand bytes
        src = self.regs[at_pc[0]]
        d_off, a_off = src[instr.rd], src[instr.ra]
        b_off, c_off = src[instr.rb], src[instr.rc]
        regions = [
            ("A", a_off, m * k * elem),
            ("B", b_off, k * n * elem),
            ("D", d_off, m * n * 4),
        ]
        if info.accumulate:
            regions.append(("C", c_off, m * n * 4))
        for name, off, nbytes in regions:
            if off < 0 or off + nbytes > len(self.scratch):
                raise ValueError(
                    f"mma {name} tile [{off}:{off + nbytes}) exceeds the "
                    f"scratchpad ({len(self.scratch)} bytes)"
                )
        # A: stored (m, k), or (k, m) when trans_a; B: (k, n), or (n, k).
        a = self._mma_operand(
            a_off, k if info.trans_a else m, m if info.trans_a else k,
            info.trans_a, info.dtype, m * k * elem,
        )
        b = self._mma_operand(
            b_off, n if info.trans_b else k, k if info.trans_b else n,
            info.trans_b, info.dtype, k * n * elem,
        )
        product = a @ b
        if info.accumulate:
            c = np.frombuffer(
                bytes(self.scratch[c_off:c_off + m * n * 4]), dtype="<f4"
            ).reshape(m, n)
            product = c + product
        self.scratch[d_off:d_off + m * n * 4] = \
            product.astype("<f4").tobytes()

        self.stats.instructions += 1
        self.stats.macs += m * n * k
        cycles = me_model.me_cycles(m, n, k)
        self.steps += cycles - 1  # run() already counted this issue round
        self.stats.bytes_read["shared"] += (
            m * k * elem + k * n * elem + (m * n * 4 if info.accumulate else 0)
        )
        self.stats.bytes_written["shared"] += m * n * 4
        for t in at_pc:
            self.pc[t] += 1

    def _convert(self, value: int, from_t: int, to_t: int) -> int:
        src, dst = TYPES[from_t], TYPES[to_t]
        if src == "f32":
            if dst == "f32":
                return value & _MASK  # identity (same float32 bit pattern)
            number = int(_f32(value))  # truncate toward zero
        elif src in ("u8", "s8"):
            low = value & 0xFF
            number = (low - 256) if (src == "s8" and low & 0x80) else low
        elif src == "s32":
            number = _signed(value)
        else:  # u32
            number = value
        if dst == "f32":
            return _fbits(float(number))
        if dst == "u8":
            return number & 0xFF
        if dst == "s8":
            low = number & 0xFF
            return _mask(low | 0xFFFFFF00) if low & 0x80 else low
        return _mask(number)

    # --- driver ------------------------------------------------------------

    def step_lockstep(self) -> None:
        live = [t for t in range(self.threads) if self.alive[t]]
        if not live:
            return
        counts = Counter(self.pc[t] for t in live)
        best = max(counts.values())
        chosen = {p for p, c in counts.items() if c == best}
        shared_pc = min(self.pc[t] for t in live if self.pc[t] in chosen)
        if not 0 <= shared_pc < len(self.code):
            raise ValueError(f"pc {shared_pc} out of range ({len(self.code)} instrs)")
        instr = self.code[shared_pc]
        if MNEMONICS[instr.op] == "mma":
            self._exec_mma(instr, [t for t in live if self.pc[t] == shared_pc])
            return
        for t in live:
            if self.alive[t] and self.pc[t] == shared_pc:
                self._exec(instr, t)

    def run(self) -> SimResult:
        for block_id in range(self.blocks):
            self.block_id = block_id
            self.scratch = bytearray(self.scratchpad_size)
            self.regs = [[0] * 32 for _ in range(self.threads)]
            self.pc = [self.entry] * self.threads
            self.flags = [0] * self.threads
            self.alive = [True] * self.threads
            self.local = [bytearray() for _ in range(self.threads)]
            while any(self.alive):
                self.steps += 1
                if self.steps > self.max_steps:
                    raise RuntimeError(
                        f"step limit exceeded ({self.max_steps}); kernel may "
                        "not be terminating"
                    )
                self.step_lockstep()
        self.stats.steps = self.steps
        return SimResult(
            memory=self.memory, stats=self.stats,
            blocks=self.blocks, threads=self.threads,
        )


def run(
    image: KernelImage,
    *,
    threads: int,
    memory: bytearray,
    blocks: int = 1,
    scratchpad_size: int = 4096,
    constants: bytes = b"",
    max_steps: int = 10_000_000,
) -> SimResult:
    """Execute a kernel image on the transaction-level simulator."""
    if threads < 1 or blocks < 1:
        raise ValueError(f"threads and blocks must be >= 1, got {threads}/{blocks}")
    if not image.code:
        raise ValueError("kernel image has no code")
    engine = _Engine(
        image, threads=threads, blocks=blocks, memory=memory,
        scratchpad_size=scratchpad_size, constants=constants, max_steps=max_steps,
    )
    return engine.run()
