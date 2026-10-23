#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

#include "genesis_runtime.h"
#include "video/genesis_machine.h"

M68KState g_cpu;
uint8_t g_ram[0x10000];
GenesisMachine g_machine;
uint32_t g_rdb_current_func;
uint32_t g_gvdp_event_seq;

static uint32_t s_test_frame;
uint32_t cmd_server_current_frame(void) { return s_test_frame; }

#include "../../engine/runner/r3_graphics_diag.inc"

int main(void)
{
    memset(&g_cpu, 0, sizeof(g_cpu));
    memset(g_ram, 0, sizeof(g_ram));
    memset(&g_machine, 0, sizeof(g_machine));
    rdb_r3_diag_init();

    g_ram[0x37A6u] = 2;
    g_ram[0x37AAu] = 1;
    g_ram[0xF500u] = 0x7B;
    g_machine.vdp.reg[0x05] = 0x5E;
    g_machine.vdp.vram[0] = 0x11;
    g_machine.vdp.cram[0] = 0x0123;
    g_machine.vdp.vsram[0] = 0x0042;
    g_rdb_current_func = 0x001234u;
    g_rdb_r3_diag_pc = 0x00F440u;
    s_test_frame = 100;

    /* Stage-2 probe arms the same bounded capture path as the live runner. */
    rdb_r3_diag_probe(0x00F440u);

    g_cpu.D[0] = 0x11223344u;
    g_cpu.A[0] = 0x00ABCDEFu;
    g_rdb_r3_diag_pc = 0x003326u;
    s_test_frame++;
    rdb_r3_diag_dispatch_miss(0x00202Cu);

    /* Later changes must not replace the first-dispatch evidence. */
    g_machine.vdp.vram[0] = 0xEE;
    g_machine.vdp.cram[0] = 0x0789;
    g_machine.vdp.vsram[0] = 0x4321;
    g_ram[0xF500u] = 0xA4;
    for (uint32_t i = 0; i < 700u; ++i) {
        g_cpu.D[0] = i;
        s_test_frame++;
        rdb_r3_diag_dispatch_miss(0x00202Cu);
    }

    g_gvdp_event_seq = 77;
    s_test_frame++;
    rdb_r3_diag_shutdown();
    return 0;
}
