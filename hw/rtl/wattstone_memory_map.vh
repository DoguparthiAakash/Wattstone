`ifndef WATTSTONE_MEMORY_MAP_VH
`define WATTSTONE_MEMORY_MAP_VH

// ============================================================================
// File        : wattstone_memory_map.vh
// Description : Physical Memory Map definitions for the Wattstone SoC.
//               This map defines the address spaces for memory and all
//               accelerator MMIO (GPU, TPU, NPU) regions.
// ============================================================================

// ----------------------------------------------------------------------------
// Core Boot & System Registers
// ----------------------------------------------------------------------------
`define WATTSTONE_BOOT_ROM_BASE     64'h0000_0000_0000_1000
`define WATTSTONE_BOOT_ROM_SIZE     64'h0000_0000_0001_0000 // 64 KB

`define WATTSTONE_CLINT_BASE        64'h0000_0000_0200_0000
`define WATTSTONE_CLINT_SIZE        64'h0000_0000_0001_0000 // 64 KB

`define WATTSTONE_PLIC_BASE         64'h0000_0000_0C00_0000
`define WATTSTONE_PLIC_SIZE         64'h0000_0000_0400_0000 // 64 MB

// ----------------------------------------------------------------------------
// Basic Peripherals
// ----------------------------------------------------------------------------
`define WATTSTONE_UART0_BASE        64'h0000_0000_1000_0000
`define WATTSTONE_UART0_SIZE        64'h0000_0000_0000_1000 // 4 KB

// ----------------------------------------------------------------------------
// Accelerator MMIO Regions (Memory-Mapped I/O)
// ----------------------------------------------------------------------------
// GPU Subsystem Control Registers
`define WATTSTONE_GPU_MMIO_BASE     64'h0000_0000_3000_0000
`define WATTSTONE_GPU_MMIO_SIZE     64'h0000_0000_0100_0000 // 16 MB

// TPU Subsystem Control Registers
`define WATTSTONE_TPU_MMIO_BASE     64'h0000_0000_4000_0000
`define WATTSTONE_TPU_MMIO_SIZE     64'h0000_0000_0100_0000 // 16 MB

// NPU Subsystem Control Registers
`define WATTSTONE_NPU_MMIO_BASE     64'h0000_0000_5000_0000
`define WATTSTONE_NPU_MMIO_SIZE     64'h0000_0000_0100_0000 // 16 MB

// ----------------------------------------------------------------------------
// Unified Main Memory (DRAM)
// All cores (CPU, GPU, TPU, NPU) access this region directly.
// ----------------------------------------------------------------------------
`define WATTSTONE_DRAM_BASE         64'h0000_0000_8000_0000
// 16 GB of Unified RAM default assumption
`define WATTSTONE_DRAM_SIZE         64'h0000_0004_0000_0000 

`endif // WATTSTONE_MEMORY_MAP_VH
