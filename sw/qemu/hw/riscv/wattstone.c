/*
 * QEMU RISC-V "Wattstone" Machine Model
 *
 * This machine model mimics the physical memory map of the Wattstone SoC.
 * It provides the RISC-V CPU core and dummy MMIO regions for the GPU,
 * TPU, and NPU so that Linux can boot and drivers can be tested in emulation.
 */

#include "qemu/osdep.h"
#include "qemu/units.h"
#include "qemu/error-report.h"
#include "qapi/error.h"
#include "hw/boards.h"
#include "hw/loader.h"
#include "hw/sysbus.h"
#include "hw/riscv/riscv_hart.h"
#include "hw/riscv/boot.h"
#include "hw/riscv/numa.h"
#include "hw/char/serial.h"
#include "target/riscv/cpu.h"
#include "sysemu/sysemu.h"

/* Memory Map corresponding to hw/rtl/wattstone_memory_map.vh */
static const MemMapEntry wattstone_memmap[] = {
    [0] = { 0x00001000,       0x10000 }, /* ROM */
    [1] = { 0x02000000,       0x10000 }, /* CLINT */
    [2] = { 0x0C000000,     0x4000000 }, /* PLIC */
    [3] = { 0x10000000,        0x1000 }, /* UART0 */
    [4] = { 0x30000000,     0x1000000 }, /* GPU_MMIO */
    [5] = { 0x40000000,     0x1000000 }, /* TPU_MMIO */
    [6] = { 0x50000000,     0x1000000 }, /* NPU_MMIO */
    [7] = { 0x80000000,           0x0 }, /* DRAM (size dynamic) */
};

typedef struct WattstoneState {
    MachineState parent;
    RISCVHartArrayState soc[1];
} WattstoneState;

#define TYPE_WATTSTONE_MACHINE "wattstone"
#define WATTSTONE_MACHINE(obj) \
    OBJECT_CHECK(WattstoneState, (obj), TYPE_WATTSTONE_MACHINE)

static void wattstone_machine_init(MachineState *machine)
{
    const MemMapEntry *memmap = wattstone_memmap;
    WattstoneState *s = WATTSTONE_MACHINE(machine);
    MemoryRegion *system_memory = get_system_memory();
    MemoryRegion *main_mem = g_new(MemoryRegion, 1);
    MemoryRegion *mask_rom = g_new(MemoryRegion, 1);

    /* Initialize RISC-V Hart (CPU) */
    object_initialize_child(OBJECT(machine), "soc", &s->soc[0],
                            TYPE_RISCV_HART_ARRAY);
    object_property_set_str(OBJECT(&s->soc[0]), "cpu-type",
                            machine->cpu_type, &error_abort);
    object_property_set_int(OBJECT(&s->soc[0]), "num-harts",
                            machine->smp.cpus, &error_abort);
    sysbus_realize(SYS_BUS_DEVICE(&s->soc[0]), &error_fatal);

    /* Register RAM */
    memory_region_init_ram(main_mem, NULL, "wattstone.ram",
                           machine->ram_size, &error_fatal);
    memory_region_add_subregion(system_memory, memmap[7].base, main_mem);

    /* Register Boot ROM */
    memory_region_init_rom(mask_rom, OBJECT(machine), "wattstone.mrom",
                           memmap[0].size, &error_fatal);
    memory_region_add_subregion(system_memory, memmap[0].base, mask_rom);

    /* UART */
    serial_mm_init(system_memory, memmap[3].base,
                   0, qdev_get_gpio_in(DEVICE(&s->soc[0]), 10),
                   115200, serial_hd(0), DEVICE_LITTLE_ENDIAN);

    /* 
     * In a full implementation, we would register specific QEMU Device models 
     * for the GPU, TPU, and NPU MMIO spaces here.
     */

    /* Boot setup */
    riscv_setup_rom_reset_vec(machine, &s->soc[0], memmap[7].base,
                              memmap[0].base, memmap[0].size, 0, 0, NULL);
}

static void wattstone_machine_class_init(ObjectClass *oc, void *data)
{
    MachineClass *mc = MACHINE_CLASS(oc);
    mc->desc = "RISC-V Board compatible with Wattstone SoC";
    mc->init = wattstone_machine_init;
    mc->max_cpus = 8;
    mc->default_cpu_type = TYPE_RISCV_CPU_BASE;
    mc->default_ram_id = "wattstone.ram";
}

static const TypeInfo wattstone_machine_typeinfo = {
    .name       = TYPE_WATTSTONE_MACHINE,
    .parent     = TYPE_MACHINE,
    .class_init = wattstone_machine_class_init,
    .instance_size = sizeof(WattstoneState),
};

static void wattstone_machine_init_register_types(void)
{
    type_register_static(&wattstone_machine_typeinfo);
}

type_init(wattstone_machine_init_register_types)
