"""Cycle/energy model of the systolic matrix engine (ME).

wvISA v0.3 added the block-wide ``mma`` opcode (0x40); this module is the
single source for how the simulator charges time and energy to it. The
constants are *not* measured silicon numbers — they are the modelled design
point, labeled per docs/architecture/README.md:

- ``PEAK_MACS_PER_CYCLE``: 128x128 BF16 MACs/cycle — the ME sizing `GOAL`
  from docs/architecture/compute.md.
- ``ME_UTILIZATION``: sustained utilization on the benchmark GEMM mixes —
  `GOAL` >= 0.60 (compute.md "Throughput goals"); 0.60 is the modelled
  default point.
- ``PIPELINE_RAMP_CYCLES``: per-``mma`` fill/drain overhead — `ESTIMATE`
  (+/-20% timing band), one constant independent of tile size.
- ``BF16_MAC_ENERGY_PJ``: energy per BF16 multiply + f32 accumulate —
  `ESTIMATE` +/-70% (PPA band), derived from Horowitz ISSCC 2014
  (45 nm: FP16 mul 1.1 pJ + FP16 add 0.4 pJ ~ 1.5 pJ) scaled ~1/3 to a
  modern node with an optimized array datapath.

Timing model: ``cycles = ceil(M*N*K / (PEAK * utilization)) + RAMP``.
The formula and constants are documented in compute.md; 2:4 sparsity is
NOT modeled here (the ME would skip zero columns — design goal only).
"""

import math

#: ME array size: MACs issued per cycle (GOAL sizing, compute.md).
PEAK_MACS_PER_CYCLE = 128 * 128

#: Modelled sustained utilization of the array (GOAL >= 0.60, compute.md).
ME_UTILIZATION = 0.60

#: Per-mma pipeline fill/drain cycles (ESTIMATE, +/-20%).
PIPELINE_RAMP_CYCLES = 64

#: Energy per BF16 MAC (multiply + f32 accumulate), pJ (ESTIMATE +/-70%).
BF16_MAC_ENERGY_PJ = 0.5


def me_cycles(m: int, n: int, k: int, *, utilization: float = ME_UTILIZATION) -> int:
    """Modeled cycles for one mma of shape (m, n, k) on the ME.

    Raises ValueError for non-positive shapes or utilization outside
    (0, 1].
    """
    if m <= 0 or n <= 0 or k <= 0:
        raise ValueError(f"mma tile sizes must be positive, got {m}x{n}x{k}")
    if not 0 < utilization <= 1:
        raise ValueError(f"utilization must be in (0, 1], got {utilization}")
    macs = m * n * k
    steady = math.ceil(macs / (PEAK_MACS_PER_CYCLE * utilization))
    return steady + PIPELINE_RAMP_CYCLES


def macs_energy_pj(m: int, n: int, k: int) -> float:
    """Modeled ME energy (pJ) for one mma of shape (m, n, k)."""
    if m <= 0 or n <= 0 or k <= 0:
        raise ValueError(f"mma tile sizes must be positive, got {m}x{n}x{k}")
    return m * n * k * BF16_MAC_ENERGY_PJ
