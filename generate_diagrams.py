import base64
import zlib
import urllib.request
import os

def generate_diagram(mermaid_text, filename):
    print(f"Generating {filename}...")
    compressed = zlib.compress(mermaid_text.encode('utf-8'), 9)
    encoded = base64.urlsafe_b64encode(compressed).decode('utf-8')
    url = f"https://kroki.io/mermaid/png/{encoded}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response, open(filename, 'wb') as out_file:
            out_file.write(response.read())
        print(f"Success: {filename}")
    except Exception as e:
        print(f"Error generating {filename}: {e}")

cpu_diagram = """
graph TD
    classDef control fill:#ffeedd,stroke:#ddbb99,color:#000
    classDef compute fill:#ffeeaa,stroke:#ddbb99,color:#000
    classDef localmem fill:#ddeecc,stroke:#99bb99,color:#000
    classDef globalmem fill:#ccddff,stroke:#99aacc,color:#000

    subgraph CPU [Wattstone Compute Core]
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
"""

tpu_diagram = """
graph TD
    classDef control fill:#ffeedd,stroke:#ddbb99,color:#000
    classDef compute fill:#ffeeaa,stroke:#ddbb99,color:#000
    classDef localmem fill:#ddeecc,stroke:#99bb99,color:#000
    classDef globalmem fill:#ccddff,stroke:#99aacc,color:#000

    subgraph TPU [Wattstone Tensor Core]
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
"""

npu_diagram = """
graph TD
    classDef control fill:#ffeedd,stroke:#ddbb99,color:#000
    classDef compute fill:#ffeeaa,stroke:#ddbb99,color:#000
    classDef localmem fill:#ddeecc,stroke:#99bb99,color:#000
    classDef globalmem fill:#ccddff,stroke:#99aacc,color:#000

    subgraph NPU [Wattstone Neural Core]
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
"""

os.makedirs("e:/gpu/Wattstone/docs/images", exist_ok=True)
generate_diagram(cpu_diagram, "e:/gpu/Wattstone/docs/images/wattstone_cpu.png")
generate_diagram(tpu_diagram, "e:/gpu/Wattstone/docs/images/wattstone_tpu.png")
generate_diagram(npu_diagram, "e:/gpu/Wattstone/docs/images/wattstone_npu.png")

print("Done.")
