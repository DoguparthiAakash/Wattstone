# Wattstone Intellectual Property (IP) Cores

This directory contains the specific RTL (Register-Transfer Level) source code required by the Wattstone SoC that is derived from external open-source projects.

## Architecture Guidelines
To keep the main Wattstone repository clean and avoid "direct placing" of massive external Git repositories (which bloats our tree with unnecessary build scripts, tests, and documentation), we follow this methodology:

1. **External Placement**: The complete source repositories for our components (XiangShan, OpenGPU, OpenTPU, CoralNPU) are placed OUTSIDE this project tree (e.g., in `e:\gpu\use`).
2. **Generation and Extraction**: We compile or generate the final Verilog/SystemVerilog sources from those external repositories.
3. **Clean Injection**: We copy ONLY the finalized, generated `.v` or `.sv` code into the respective subdirectories here:
   - `cpu/` : Contains the generated Verilog from XiangShan-kunminghu-v3.
   - `gpu/` : Contains the synthesized OpenGPU source.
   - `tpu/` : Contains the OpenTPU core logic.
   - `npu/` : Contains the CoralNPU inference logic.

This ensures that our integration codebase (`hw/rtl/wattstone_top.sv`) can easily reference and synthesize the entire SoC without dealing with the complex, conflicting build systems of the individual IP cores.
