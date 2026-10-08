<div align="center">
  <img src="assets/wattstone-logo.svg" width="1000" alt="Wattstone CPU" />
  <p><strong>A Next-Generation Open-Source Unified Architecture</strong></p>
</div>

---

## 📖 Overview

**Project Wattstone** is a highly ambitious, general-purpose open-source System-on-Chip (SoC) designed to serve as a high-performance, power-efficient alternative to proprietary x86 and ARM processors. 

Taking inspiration from modern integrated architectures, Wattstone unites a high-performance Central Processing Unit (CPU), Graphics Engine (GPU), Tensor Processing Unit (TPU), and Neural Processing Unit (NPU) onto a single piece of silicon. 

Crucially, all of these computation units are connected via a **Unified Memory Architecture (UMA)** utilizing a shared System Level Cache (SLC). This eliminates massive memory-copy bottlenecks, radically reducing power consumption and heat generation while drastically increasing throughput for modern workloads (AI, parallel compute, graphics, and general OS tasks).

---

## 🏛️ Architecture & Die Layout

Below is a conceptual block diagram representing the Wattstone SoC die layout. The architecture is modular and built to scale efficiently.

![Wattstone Die Layout](./docs/images/die_layout.png)

### Unified Components Structure

To maintain a cohesive design language and simplify development, all architectural blocks in Wattstone are integrated under logical namespaces. Here is how they all connect together on the die:

<details open>
<summary><b>Wattstone Unified SoC Top Architecture</b></summary>

```mermaid
block-beta
  columns 8
  
  %% Row 1: High Speed Interfaces
  PCIe["PCIe / Peripheral I/O"]:2 DISP["Display Engine"]:2 DDR1["LPDDR5 Ctrl 0"]:2 DDR2["LPDDR5 Ctrl 1"]:2
  
  %% Row 2: CPU and GPU
  CPU0["CPU 0"] CPU1["CPU 1"] CPU2["CPU 2"] CPU3["CPU 3"] GPU1["GPU Cluster 0"]:2 GPU2["GPU Cluster 1"]:2
  
  %% Row 3: Caches and GPU
  L2_0["L2 Cache"] L2_1["L2 Cache"] L2_2["L2 Cache"] L2_3["L2 Cache"] GPU3["GPU Cluster 2"]:2 GPU4["GPU Cluster 3"]:2
  
  %% Row 4: SLC and Crossbar
  SLC["8MB System Level Cache (SLC)"]:4 AXI["High-Speed AXI Interconnect Crossbar"]:4
  
  %% Row 5: AI Accelerators
  TPU_SA["TPU Systolic Array"]:2 TPU_Mem["TPU Memory"]:2 NPU_MAC["NPU MAC Engine"]:2 NPU_SRAM["NPU SRAM"]:2
  
  %% Style definitions
  classDef cpu fill:#ffb3ba,stroke:#ff6b6b,stroke-width:2px,color:#000
  classDef gpu fill:#bae1ff,stroke:#4dabf7,stroke-width:2px,color:#000
  classDef tpu fill:#e2cbff,stroke:#b197fc,stroke-width:2px,color:#000
  classDef npu fill:#baffc9,stroke:#69db7c,stroke-width:2px,color:#000
  classDef mem fill:#ffffba,stroke:#ffd43b,stroke-width:2px,color:#000
  classDef io fill:#e9ecef,stroke:#ced4da,stroke-width:2px,color:#000
  classDef uncore fill:#ffd8b1,stroke:#ffa94d,stroke-width:2px,color:#000

  class CPU0,CPU1,CPU2,CPU3 cpu
  class L2_0,L2_1,L2_2,L2_3 cpu
  class GPU1,GPU2,GPU3,GPU4 gpu
  class DISP gpu
  class TPU_SA,TPU_Mem tpu
  class NPU_MAC,NPU_SRAM npu
  class SLC,DDR1,DDR2 mem
  class PCIe io
  class AXI uncore
```
</details>

*   **Wattstone Compute Core (CPU)**: A high-performance, superscalar, Out-of-Order (OoO) RISC-V processor cluster. Serves as the primary orchestrator, fully capable of booting and running modern UNIX-based operating systems (Linux/BSD).
*   **Wattstone Graphics Engine (GPU)**: A massively parallel graphics processor for 3D rendering and high-bandwidth rasterization workloads.
*   **Wattstone Tensor Core (TPU)**: A dedicated matrix-multiplication engine for accelerating large-scale vector processing and complex mathematical models.
*   **Wattstone Neural Core (NPU)**: An ultra-efficient accelerator focused on running quantized machine learning inferencing (edge AI) with minimal power draw.
*   **Wattstone Display Engine (Low-Power GPU)**: A tiny, highly efficient 2D graphics co-processor for UI rendering, basic display output, and power-saving modes when the main Graphics Engine is asleep.
*   **System Level Cache (SLC)**: A massive, unified L3/SLC cache bank that all engines read from and write to simultaneously.
*   **Unified Memory Controller**: Manages the wide, high-speed connection to off-chip LPDDR memory, ensuring the shared memory pool is fed with maximum bandwidth.

### Detailed Component Architectures

Below are detailed block diagrams of the individual logic cores, structurally mirroring the clean architecture style of the Wattstone display pipeline. These diagrams render natively in Markdown viewers (like GitHub).

<details>
<summary><b>Wattstone Compute Core (CPU)</b></summary>

```mermaid
graph TD
    classDef control fill:#ffeedd,stroke:#ddbb99,color:#000
    classDef compute fill:#ffeeaa,stroke:#ddbb99,color:#000
    classDef localmem fill:#ddeecc,stroke:#99bb99,color:#000
    classDef globalmem fill:#ccddff,stroke:#99aacc,color:#000

    subgraph CPU [Compute Core]
        direction TB
        IFU[Instruction Fetch Unit]:::control
        BPU[Branch Prediction Unit]:::control
        IDU[Instruction Decode Unit]:::control
        IQ[Instruction Queue]:::control
        ROB[Reorder Buffer]:::control
        
        IFU <--> BPU
        IFU --> IDU
        IDU --> IQ
        IQ --> ROB
        
        subgraph Exec [Execution Engines]
            ALU[ALU Cluster]:::compute
            FPU[FPU / Vector Unit]:::compute
            LSU[Load/Store Unit]:::globalmem
        end
        
        ROB --> ALU
        ROB --> FPU
        ROB --> LSU
        
        Reg[Physical Register File]:::localmem
        ALU --> Reg
        FPU --> Reg
        LSU --> Reg
        
        L1I[L1 Instruction Cache]:::localmem
        L1D[L1 Data Cache]:::localmem
        
        L1I --> IFU
        LSU <--> L1D
    end
```
</details>

<details>
<summary><b>Wattstone Graphics Engine (GPU)</b></summary>

```mermaid
graph TD
    classDef control fill:#ffeedd,stroke:#ddbb99,color:#000
    classDef compute fill:#ffeeaa,stroke:#ddbb99,color:#000
    classDef localmem fill:#ddeecc,stroke:#99bb99,color:#000
    classDef globalmem fill:#ccddff,stroke:#99aacc,color:#000

    subgraph GPU [Graphics Engine]
        direction TB
        CMD[Command Processor / Dispatcher]:::control
        DCR[Device Control Register]:::control
        
        CMD --> DCR
        
        subgraph ShaderCores [Compute Cores / Shaders]
            direction LR
            C1[Core 0]:::compute
            C2[Core 1]:::compute
            C3[Core 2]:::compute
            C4[Core 3]:::compute
        end
        
        DCR --> ShaderCores
        
        L2[Shared L2 Cache]:::localmem
        
        C1 --> L2
        C2 --> L2
        C3 --> L2
        C4 --> L2
        
        PMC[Program Memory Controller]:::globalmem
        DMC[Data Memory Controller]:::globalmem
        
        L2 <--> PMC
        L2 <--> DMC
    end
```
</details>

<details>
<summary><b>Wattstone Tensor Core (TPU)</b></summary>

```mermaid
graph TD
    classDef control fill:#ffeedd,stroke:#ddbb99,color:#000
    classDef compute fill:#ffeeaa,stroke:#ddbb99,color:#000
    classDef localmem fill:#ddeecc,stroke:#99bb99,color:#000
    classDef globalmem fill:#ccddff,stroke:#99aacc,color:#000

    subgraph TPU [Tensor Core]
        direction TB
        Dispatch[Instruction Dispatcher]:::control
        DMA[DMA Controller]:::globalmem
        
        subgraph Memory [Local Memory]
            WM[Weight Memory]:::localmem
            AM[Activation Memory]:::localmem
            ACC[Accumulator Memory]:::localmem
        end
        
        DMA --> WM
        DMA --> AM
        
        subgraph MMU [Matrix Multiply Unit]
            SA[Systolic Array 128x128]:::compute
        end
        
        WM --> SA
        AM --> SA
        SA --> ACC
        ACC --> VPU[Vector Processing Unit]:::compute
        VPU --> AM
    end
```
</details>

<details>
<summary><b>Wattstone Neural Core (NPU)</b></summary>

```mermaid
graph TD
    classDef control fill:#ffeedd,stroke:#ddbb99,color:#000
    classDef compute fill:#ffeeaa,stroke:#ddbb99,color:#000
    classDef localmem fill:#ddeecc,stroke:#99bb99,color:#000
    classDef globalmem fill:#ccddff,stroke:#99aacc,color:#000

    subgraph NPU [Neural Core]
        direction TB
        Seq[Sequencer / Controller]:::control
        AXI[AXI Interface]:::globalmem
        
        SRAM[On-Chip SRAM Buffer]:::localmem
        
        AXI <--> SRAM
        
        subgraph Engines [Compute Engines]
            MAC[MAC Array]:::compute
            Act[Activation Engine]:::compute
            Pool[Pooling Engine]:::compute
        end
        
        Seq --> MAC
        Seq --> Act
        Seq --> Pool
        
        SRAM --> MAC
        MAC --> Act
        Act --> Pool
        Pool --> SRAM
    end
```
</details>

---

## 📂 Repository Structure

```text
Wattstone/
├── hw/                   # Hardware designs and configurations
│   ├── rtl/              # SystemVerilog/Verilog integration code
│   │   ├── ip/           # Contains all Core IP blocks (CPU, GPU, NPU, TPU)
│   │   ├── slc/          # System Level Cache logic and controllers
│   │   ├── memory/       # DDR and memory controller wrappers
│   │   ├── interconnect/ # AXI/TileLink interconnect crossbars
│   │   └── wattstone_top.sv  # Main SoC wrapper uniting all blocks
├── sw/                   # Software ecosystem
│   ├── linux/            # Linux kernel source tree and Device Trees (DTS)
│   ├── drivers/          # Custom kernel drivers for GPU, TPU, and NPU
│   └── qemu/             # QEMU machine definitions for software emulation
├── docs/                 # Extended documentation and architecture specs
└── tests/                # System-level verification and testbenches
```

---

## 🚀 Getting Started

Wattstone is designed to be fully testable in simulation before moving to FPGA prototyping. We use QEMU to emulate the SoC architecture for rapid software development.

### 1. Prerequisites
Ensure you have the following installed on your development machine:
- Verilator & Chisel toolchains
- GNU RISC-V Cross-Compiler (`riscv64-unknown-linux-gnu-gcc`)
- QEMU (compiled for `riscv64` system emulation)

### 2. Booting Linux in Simulation
To test the Wattstone architecture and unified memory map in QEMU:

```bash
# 1. Compile the Wattstone Linux Kernel
cd sw/linux
make ARCH=riscv CROSS_COMPILE=riscv64-unknown-linux-gnu- defconfig
make ARCH=riscv CROSS_COMPILE=riscv64-unknown-linux-gnu- -j$(nproc)

# 2. Launch QEMU with the Wattstone Machine definition
cd ../qemu
./qemu-system-riscv64 -M wattstone -kernel ../linux/arch/riscv/boot/Image -nographic
```

---

## 🤝 Contributing

We welcome contributions to make open-source hardware a reality! 
When contributing, please:
1. Ensure all new logic uses the unified **Wattstone** naming conventions.
2. Update the Unified Memory Map (`hw/rtl/wattstone_memory_map.vh`) if adding new IP endpoints.
3. Verify your design against the unified AXI interconnect standards.

---
*Project Wattstone: Powering the next generation of open computing.*
