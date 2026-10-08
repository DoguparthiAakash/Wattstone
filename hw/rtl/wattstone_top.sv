`timescale 1ns / 1ps
`include "wattstone_memory_map.vh"

// ============================================================================
// Module      : wattstone_top
// Description : Top-level SoC wrapper for the Wattstone processor.
//               Integrates XiangShan CPU (TileLink), OpenGPU (AXI), 
//               OpenTPU (AXI), and CoralNPU (AXI) using a Unified Memory
//               Architecture (UMA) with a central System Level Cache (SLC).
// ============================================================================

module wattstone_top (
    input  logic         clk_sys,        // System Clock
    input  logic         rst_n,          // Active-low Reset
    
    // External LPDDR5 Memory Controller Interface (AXI4 Master to DDR PHY)
    output logic [3:0]   ddr_awid,
    output logic [31:0]  ddr_awaddr,
    output logic [7:0]   ddr_awlen,
    output logic [2:0]   ddr_awsize,
    output logic [1:0]   ddr_awburst,
    output logic         ddr_awvalid,
    input  logic         ddr_awready,
    
    output logic [255:0] ddr_wdata,
    output logic [31:0]  ddr_wstrb,
    output logic         ddr_wlast,
    output logic         ddr_wvalid,
    input  logic         ddr_wready,
    
    input  logic [3:0]   ddr_bid,
    input  logic [1:0]   ddr_bresp,
    input  logic         ddr_bvalid,
    output logic         ddr_bready,
    
    output logic [3:0]   ddr_arid,
    output logic [31:0]  ddr_araddr,
    output logic [7:0]   ddr_arlen,
    output logic [2:0]   ddr_arsize,
    output logic [1:0]   ddr_arburst,
    output logic         ddr_arvalid,
    input  logic         ddr_arready,
    
    input  logic [3:0]   ddr_rid,
    input  logic [255:0] ddr_rdata,
    input  logic [1:0]   ddr_rresp,
    input  logic         ddr_rlast,
    input  logic         ddr_rvalid,
    output logic         ddr_rready,

    // UART
    input  logic         uart_rx,
    output logic         uart_tx
);

    // ========================================================================
    // Power & Clock Management Unit (PMU)
    // Dynamic Voltage and Frequency Scaling (DVFS) logic
    // ========================================================================
    logic clk_cpu, clk_gpu, clk_tpu, clk_npu;
    logic rst_cpu_n, rst_gpu_n, rst_tpu_n, rst_npu_n;
    
    // In a real implementation, these would come from PLLs controlled via MMIO
    assign clk_cpu = clk_sys;
    assign clk_gpu = clk_sys;
    assign clk_tpu = clk_sys;
    assign clk_npu = clk_sys;
    
    assign rst_cpu_n = rst_n;
    assign rst_gpu_n = rst_n;
    assign rst_tpu_n = rst_n;
    assign rst_npu_n = rst_n;

    // ========================================================================
    // CPU Subsystem (XiangShan - TileLink Interface)
    // ========================================================================
    // XiangShan outputs a TileLink interface, which we will bridge to AXI4
    logic [31:0] tl_cpu_a_opcode, tl_cpu_a_param, tl_cpu_a_size, tl_cpu_a_source, tl_cpu_a_address, tl_cpu_a_mask, tl_cpu_a_data;
    logic tl_cpu_a_corrupt, tl_cpu_a_valid, tl_cpu_a_ready;
    // ... (other TileLink channels B, C, D, E omitted for brevity)
    
    xiangshan_kunminghu_top u_cpu_xiangshan (
        .clk        (clk_cpu),
        .rst_n      (rst_cpu_n),
        // TileLink Memory Port
        .tl_a_valid (tl_cpu_a_valid),
        .tl_a_ready (tl_cpu_a_ready)
        // ... (remaining TL ports)
    );

    // TileLink to AXI4 Bridge
    logic [31:0] cpu_axi_awaddr;
    logic        cpu_axi_awvalid, cpu_axi_awready;
    
    tl_to_axi4_bridge u_tl_axi_bridge (
        .clk        (clk_cpu),
        .rst_n      (rst_cpu_n),
        // TileLink in
        .tl_a_valid (tl_cpu_a_valid),
        .tl_a_ready (tl_cpu_a_ready),
        // AXI4 out
        .axi_awaddr (cpu_axi_awaddr),
        .axi_awvalid(cpu_axi_awvalid),
        .axi_awready(cpu_axi_awready)
    );

    // ========================================================================
    // Accelerator Subsystems (AXI4 Interfaces)
    // ========================================================================
    
    // GPU Subsystem: OpenGPU
    logic [31:0] gpu_axi_awaddr;
    logic        gpu_axi_awvalid, gpu_axi_awready;
    
    opengpu_top u_gpu_opengpu (
        .clk        (clk_gpu),
        .rst_n      (rst_gpu_n),
        .mmio_base  (`WATTSTONE_GPU_MMIO_BASE), // Base address configuration
        .axi_awaddr (gpu_axi_awaddr),
        .axi_awvalid(gpu_axi_awvalid),
        .axi_awready(gpu_axi_awready)
    );

    // TPU Subsystem: OpenTPU
    logic [31:0] tpu_axi_awaddr;
    logic        tpu_axi_awvalid, tpu_axi_awready;
    
    opentpu_top u_tpu_opentpu (
        .clk        (clk_tpu),
        .rst_n      (rst_tpu_n),
        .mmio_base  (`WATTSTONE_TPU_MMIO_BASE),
        .axi_awaddr (tpu_axi_awaddr),
        .axi_awvalid(tpu_axi_awvalid),
        .axi_awready(tpu_axi_awready)
    );

    // NPU Subsystem: CoralNPU
    logic [31:0] npu_axi_awaddr;
    logic        npu_axi_awvalid, npu_axi_awready;
    
    coralnpu_top u_npu_coralnpu (
        .clk        (clk_npu),
        .rst_n      (rst_npu_n),
        .mmio_base  (`WATTSTONE_NPU_MMIO_BASE),
        .axi_awaddr (npu_axi_awaddr),
        .axi_awvalid(npu_axi_awvalid),
        .axi_awready(npu_axi_awready)
    );

    // ========================================================================
    // Central AXI Crossbar (The "Fabric")
    // ========================================================================
    // Routes traffic between Masters (CPU, GPU, TPU, NPU) and Slaves (SLC, MMIO)
    
    logic [31:0] slc_axi_awaddr;
    logic        slc_axi_awvalid, slc_axi_awready;
    
    axi_crossbar_4x2 u_central_fabric (
        .clk        (clk_sys),
        .rst_n      (rst_n),
        
        // Masters
        .m0_awaddr  (cpu_axi_awaddr), .m0_awvalid(cpu_axi_awvalid), .m0_awready(cpu_axi_awready),
        .m1_awaddr  (gpu_axi_awaddr), .m1_awvalid(gpu_axi_awvalid), .m1_awready(gpu_axi_awready),
        .m2_awaddr  (tpu_axi_awaddr), .m2_awvalid(tpu_axi_awvalid), .m2_awready(tpu_axi_awready),
        .m3_awaddr  (npu_axi_awaddr), .m3_awvalid(npu_axi_awvalid), .m3_awready(npu_axi_awready),
        
        // Slaves
        .s0_awaddr  (slc_axi_awaddr), .s0_awvalid(slc_axi_awvalid), .s0_awready(slc_axi_awready)
        // s1 used for MMIO peripherals (UART, PLIC, etc)
    );

    // ========================================================================
    // System Level Cache (SLC) & UMA
    // ========================================================================
    // The SLC caches data for the unified memory, giving fast access to all cores
    
    system_level_cache u_slc (
        .clk        (clk_sys),
        .rst_n      (rst_n),
        
        // AXI interface from Fabric
        .s_axi_awaddr  (slc_axi_awaddr),
        .s_axi_awvalid (slc_axi_awvalid),
        .s_axi_awready (slc_axi_awready),
        
        // AXI interface out to DDR Controller
        .m_axi_awid    (ddr_awid),
        .m_axi_awaddr  (ddr_awaddr),
        .m_axi_awlen   (ddr_awlen),
        .m_axi_awsize  (ddr_awsize),
        .m_axi_awburst (ddr_awburst),
        .m_axi_awvalid (ddr_awvalid),
        .m_axi_awready (ddr_awready),
        
        .m_axi_wdata   (ddr_wdata),
        .m_axi_wstrb   (ddr_wstrb),
        .m_axi_wlast   (ddr_wlast),
        .m_axi_wvalid  (ddr_wvalid),
        .m_axi_wready  (ddr_wready),
        
        .m_axi_bid     (ddr_bid),
        .m_axi_bresp   (ddr_bresp),
        .m_axi_bvalid  (ddr_bvalid),
        .m_axi_bready  (ddr_bready),
        
        .m_axi_arid    (ddr_arid),
        .m_axi_araddr  (ddr_araddr),
        .m_axi_arlen   (ddr_arlen),
        .m_axi_arsize  (ddr_arsize),
        .m_axi_arburst (ddr_arburst),
        .m_axi_arvalid (ddr_arvalid),
        .m_axi_arready (ddr_arready),
        
        .m_axi_rid     (ddr_rid),
        .m_axi_rdata   (ddr_rdata),
        .m_axi_rresp   (ddr_rresp),
        .m_axi_rlast   (ddr_rlast),
        .m_axi_rvalid  (ddr_rvalid),
        .m_axi_rready  (ddr_rready)
    );

endmodule
