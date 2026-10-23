#ifndef R7_ENDING_DIAG_H
#define R7_ENDING_DIAG_H

#include <stddef.h>
#include <stdint.h>

#define R7_ENDING_DIAG_BUS_MAX 64u
#define R7_ENDING_DIAG_RECORD_CAP 256u

typedef struct R7EndingDiagBusEvent {
    uint32_t address;
    uint32_t pc;
    uint8_t kind;
} R7EndingDiagBusEvent;

typedef struct R7EndingDiagSnapshot {
    uint64_t wall_frame;
    uint64_t sound_frame;
    uint64_t native_instructions;
    uint64_t chunk_yields;
    uint64_t audio_events;
    uint32_t audio_cycle;
    uint64_t audio_port_events[5];
    uint32_t d[8];
    uint32_t a[7];
    uint32_t pc;
    uint32_t cpu_pc;
    uint32_t current_function;
    uint32_t sp;
    uint32_t returns[4];
    uint32_t callback;
    uint32_t master_cycle;
    uint32_t z80_cycle_debt;
    uint32_t vint_count;
    uint32_t object_pointer;
    uint32_t audio_queue;
    uint16_t ending_state;
    uint16_t previous_state;
    uint16_t ending_flags;
    uint16_t stage;
    uint16_t act;
    uint16_t timer;
    uint16_t script_done;
    uint16_t z80_pc;
    uint16_t vdp_scanline;
    uint16_t object_state;
    uint16_t object_tick;
    uint16_t object_frame;
    uint16_t object_x;
    uint16_t object_y;
    uint16_t object_vx;
    uint16_t object_vy;
    uint16_t sr;
    uint8_t z80_iff1;
    uint8_t z80_irq_pending;
    uint8_t z80_busreq;
    uint8_t z80_reset_off;
    uint8_t z80_mailbox_1ffd;
    uint8_t z80_mailbox_busy_seen;
    uint8_t vdp_in_vblank;
    uint8_t vdp_in_hblank;
    uint8_t vdp_reg1;
    uint8_t vdp_reg10;
    uint8_t vdp_reg11;
} R7EndingDiagSnapshot;

void r7_ending_diag_init(const char *default_path);
int r7_ending_diag_is_enabled(void);
void r7_ending_diag_ram_write(const R7EndingDiagSnapshot *snapshot,
                              uint32_t address, unsigned width,
                              uint32_t old_value, uint32_t new_value);
void r7_ending_diag_dispatch_miss(const R7EndingDiagSnapshot *snapshot,
                                  uint32_t target);
void r7_ending_diag_frame(const R7EndingDiagSnapshot *snapshot);
void r7_ending_diag_watchdog(const R7EndingDiagSnapshot *snapshot,
                             const char *reason,
                             const R7EndingDiagBusEvent *bus_events,
                             size_t bus_count, uint64_t bus_total);
void r7_ending_diag_shutdown(void);

#endif
