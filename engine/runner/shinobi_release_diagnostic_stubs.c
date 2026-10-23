#include "genesis_runtime.h"
#include "r7_ending_diag.h"

/* The published release omits the opt-in Round 4 event recorder and Round 7
 * ending watchdog recorder. Keep their runtime ABI present, with no guest
 * state changes and no file or per-event I/O. Developer builds can compile
 * the real recorder sources by enabling SHINOBI_ENABLE_DEV_DIAGNOSTICS. */
uint32_t g_r4_scroll_trace_current_pc;

void r4_scroll_trace_instruction(uint32_t pc, uint32_t a0)
{ (void)pc; (void)a0; }
void r4_scroll_trace_continuation(uint32_t target, uint32_t pc)
{ (void)target; (void)pc; }
void r4_scroll_trace_memory_write(uint32_t addr, unsigned width,
                                  uint32_t old_value, uint32_t new_value,
                                  uint32_t pc)
{
    (void)addr; (void)width; (void)old_value; (void)new_value; (void)pc;
}
void r4_scroll_trace_vsram_write(uint32_t pc, unsigned index,
                                 uint16_t old_value, uint16_t new_value,
                                 uint8_t vdp_code, uint16_t vdp_address,
                                 uint8_t dma_active)
{
    (void)pc; (void)index; (void)old_value; (void)new_value;
    (void)vdp_code; (void)vdp_address; (void)dma_active;
}
void r4_scroll_trace_frame_end(void) { }

void r7_ending_diag_init(const char *default_path) { (void)default_path; }
int r7_ending_diag_is_enabled(void) { return 0; }
void r7_ending_diag_ram_write(const R7EndingDiagSnapshot *snapshot,
                              uint32_t address, unsigned width,
                              uint32_t old_value, uint32_t new_value)
{
    (void)snapshot; (void)address; (void)width;
    (void)old_value; (void)new_value;
}
void r7_ending_diag_dispatch_miss(const R7EndingDiagSnapshot *snapshot,
                                  uint32_t target)
{ (void)snapshot; (void)target; }
void r7_ending_diag_frame(const R7EndingDiagSnapshot *snapshot)
{ (void)snapshot; }
void r7_ending_diag_watchdog(const R7EndingDiagSnapshot *snapshot,
                             const char *reason,
                             const R7EndingDiagBusEvent *bus_events,
                             size_t bus_count, uint64_t bus_total)
{
    (void)snapshot; (void)reason; (void)bus_events;
    (void)bus_count; (void)bus_total;
}
void r7_ending_diag_shutdown(void) { }
