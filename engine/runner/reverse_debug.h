/*
 * reverse_debug.h — Tier-1 reverse-debugger: ring buffer + bus tap.
 *
 * Design (simpler than the snesrecomp equivalent because 68K has a bus):
 *   - Generator emits `g_rdb_current_func = 0xXXXXXXu;` at the top of
 *     every func_XXXXXX body when --reverse-debug is on.
 *   - reverse_debug.c installs itself as g_mem_write_trace_fn (the
 *     shared bus-write callback that clownmdemu-core fires on every
 *     M68kWriteCallback).
 *   - Every bus write is recorded with (frame, adr, val, width, func,
 *     caller_return_addr), filtered by up to 8 configurable ranges.
 *
 * This works in BOTH the native build (recompiled C drives the bus) and
 * the oracle build (clown68000 interpreter drives the bus). In the
 * oracle build g_rdb_current_func stays 0 because no recompiled function
 * bodies run; the caller column (ret0 from A7) still gives useful
 * attribution against SMWDisX-equivalent disassembly.
 *
 * When SONIC_REVERSE_DEBUG is not defined, this header is empty and
 * nothing is linked in.
 */
#pragma once

#include <stdint.h>
#include <stddef.h>

#if SONIC_REVERSE_DEBUG

/* Updated at the start of every recompiled func_XXXXXX body (generator
 * writes `g_rdb_current_func = 0xAABBCCu;` as the first line of each
 * function). Read by the bus-tap callback at record time to attribute
 * each write to its source 68K function. Stays 0 in oracle builds. */
extern uint32_t g_rdb_current_func;

/* ---- Control API (called from cmd_server.c dispatcher) ---- */

/* Always-on bring-up: install the bus tap with a default WRAM-wide
 * range and start recording from boot. Per the project's ring-buffer
 * rule, observation must not require arm-then-attach: Tier 1 captures
 * every store from cycle 0 and probes query backward. Called from
 * main.c init (before the first 68K instruction executes). */
void rdb_autostart(void);

/* Register the Tier-1 bus tap with the shared write-trace hook slot in
 * bus-main-m68k.c. Chains any previously-installed callback so
 * --mem-write-log and rdb can coexist. Idempotent; safe to call more
 * than once. */
void rdb_install_bus_tap(void);

/* Remove the bus tap and restore the previous g_mem_write_trace_fn
 * (if any). Called from rdb_reset. */
void rdb_uninstall_bus_tap(void);

/* Add an address-range filter [lo,hi] (inclusive, 24-bit 68K bus addr).
 * Installs the bus tap on first call. Returns 0 if full (max 8). */
int  rdb_add_range(uint32_t lo, uint32_t hi);

/* Clear all ranges + ring + uninstall bus tap. */
void rdb_reset(void);

/* Snapshot API for paged dumps. During a snapshot the visible count is
 * frozen; new writes still append to the ring but aren't visible. */
void     rdb_snapshot_begin(void);
void     rdb_snapshot_end  (void);
uint32_t rdb_snapshot_count(void);

int rdb_range_count(void);
int rdb_range_get(int i, uint32_t *lo_out, uint32_t *hi_out);

/* Format the snapshot entry at index `i` as a JSON object into buf.
 * Returns bytes written or -1 on bad index / buffer overflow. */
int rdb_format_entry(uint32_t i, char *buf, size_t buflen);

/* Narrow trace for the Shinobi sound-driver's indexed JMPs at $069BB0/$069BCA.
 * The generated call records register values after the guest's own read
 * and index shift; it does not read or write guest memory. */
void rdb_sound_index_trace(uint32_t pc, uint32_t a5, uint32_t index_reg,
                           uint32_t target);
uint32_t rdb_sound_index_count(void);
int rdb_sound_index_format(uint32_t i, char *buf, size_t buflen);
int rdb_sound_first_fault_format(char *buf, size_t buflen);

/* =========================================================================
 * Tier 2: block-level stepper (native only).
 *
 * Generator emits `rdb_on_block(0x72A5Cu);` after each label_%06X:; and
 * at the top of every function. The fast path is one global load +
 * branch when no break is armed — cost-dominated by the load. Only the
 * slow path (rdb_on_block_slow) decides whether to park the game fiber.
 *
 * When the game fiber parks, it yields via glue_yield_for_break(); the
 * main loop drains cmd_server until a resume command clears the pending
 * flag, then SwitchToFiber(s_game_fiber) re-enters rdb_on_block_slow
 * and execution continues.
 *
 * Oracle build: these symbols compile but `rdb_on_block` is never
 * reached (clown68000 interpreter never enters recompiled function
 * bodies). All Tier 2 TCP commands reply with "native only".
 * ========================================================================= */

/* Non-zero iff the slow path should consider parking. Set when any
 * breakpoint is armed OR a step command is pending. Read on every
 * block entry; the branch is almost always not-taken in a normal run. */
extern int g_rdb_break_pending;

void rdb_on_block_slow(uint32_t block_id);

/* Cheap unconditional ring recorder for the crash-report tool.
 * Same hot path as rdb_on_block, populates the recent-block ring
 * even when no breakpoint is armed so the watchdog dump can show
 * the last N block transitions. Defined in crash_report.c. */
void crash_report_record_block(uint32_t block_addr);

static inline void rdb_on_block(uint32_t block_id)
{
    crash_report_record_block(block_id);
    if (g_rdb_break_pending) rdb_on_block_slow(block_id);
}

/* Control API — called from cmd_server.c dispatcher. */
int  rdb_break_add(uint32_t block_id);   /* returns 0 if table full */
void rdb_break_clear_all(void);
int  rdb_break_count(void);
uint32_t rdb_break_get(int i);           /* 0 on bad index */

/* Step commands. Each arms the corresponding mode and sets the resume
 * flag that tells the main park-drain loop to SwitchToFiber back. */
void rdb_cmd_step_one  (void);
void rdb_cmd_step_over (void);
void rdb_cmd_continue  (void);

/* True while the game fiber is parked at a block. Cleared by the
 * yield's flag reset when the fiber resumes. */
int  rdb_is_parked(void);
uint32_t rdb_parked_block(void);

/* Main-loop side: set to 1 by a resume command; main park-drain loop
 * reads it, clears it, and switches back to the game fiber. */
extern int g_rdb_resume_now;

/* =========================================================================
 * Tier 4: per-instruction stepping (native, opt-in in generated C).
 *
 * Generator emits `rdb_on_insn(0xXXXXXXu);` alongside the cycle-bump
 * emission, so the hook fires once per 68K instruction (not per label
 * like Tier 2). The fast path is an inline that checks
 * g_rdb_insn_pending — almost always not taken when no per-insn break
 * or step is armed. When set, the slow path decides whether to park.
 *
 * Reuses Tier 2's fiber-yield + park-drain machinery. Breaks can be
 * armed at ANY 68K instruction PC, not just block entries.
 * ========================================================================= */

extern int g_rdb_insn_pending;

/* Narrow Round 2 object/renderer trace. Runtime opt-in is
 * GENESIS_R2_DIAG=1; the diagnostic build records only the manager-rooted
 * object fields, selected ROM PCs, and SAT DMA snapshots. */
extern int g_rdb_boss_diag_enabled;
extern uint32_t g_rdb_boss_diag_pc;
void rdb_boss_diag_probe(uint32_t pc);

/* Opt-in Round 3 transition capture, enabled only by GENESIS_R3_DIAG=1. */
struct GVDP;
extern int g_rdb_r3_diag_enabled;
extern uint32_t g_rdb_r3_diag_pc;
void rdb_r3_diag_probe(uint32_t pc);
void rdb_r3_diag_write(uint32_t byte_address, uint8_t before, uint8_t value);
void rdb_r3_diag_dispatch_miss(uint32_t target);
void rdb_r3_diag_vdp_event(const struct GVDP *vdp, uint32_t vdp_seq,
                           uint8_t kind, uint8_t code, uint16_t addr,
                           uint16_t value, uint16_t inc, uint16_t len,
                           uint32_t src, uint8_t reason);
void rdb_r3_diag_dma_complete(const struct GVDP *vdp, uint8_t kind,
                              uint32_t vdp_seq, uint32_t src, uint16_t dst,
                              uint32_t words, uint8_t code);
void rdb_r3_diag_shutdown(void);
void rdb_boss_diag_write(uint32_t byte_address, uint8_t value);
void rdb_boss_diag_sat_dma(uint32_t vdp_seq, uint32_t src, uint32_t dst,
                           uint32_t len_words, uint8_t code,
                           uint8_t reg5, uint8_t reg11, uint8_t reg13,
                           const uint8_t *vram);
void rdb_boss_diag_shutdown(void);

void rdb_on_insn_slow(uint32_t pc);

static inline void rdb_on_insn(uint32_t pc)
{
    if (g_rdb_r3_diag_enabled) {
        /* This branch is cold unless the dedicated stage capture is enabled. */
        g_rdb_r3_diag_pc = pc & 0xFFFFFFu;
        switch (pc) {
        case 0x00F418u: case 0x00F432u: case 0x00F440u:
        case 0x0046FAu: case 0x00460Eu: case 0x004264u:
        case 0x0115C0u: case 0x0115CAu: case 0x0115CEu: case 0x0115D2u:
        case 0x0115D6u: case 0x0115DAu: case 0x0115DEu: case 0x0115E2u:
        case 0x0115E6u: case 0x01165Au: case 0x01169Eu: case 0x0116ACu:
        case 0x011924u: case 0x0119F2u: case 0x00202Cu: case 0x0393CAu:
        case 0x000FA6u: case 0x003326u: case 0x00099Au: case 0x0390E2u:
            rdb_r3_diag_probe(pc);
            break;
        default:
            break;
        }
    }
    if (g_rdb_boss_diag_enabled) {
        /* Native code calls this immediately before each translated guest
         * instruction. Keep its PC so the bus tap can attribute a watched
         * object-field write to the exact producer instruction. */
        g_rdb_boss_diag_pc = pc & 0xFFFFFFu;
        switch (pc) {
        case 0x02A3CCu: case 0x02A3CEu: case 0x02A414u:
        case 0x02A4A4u: case 0x02B104u: case 0x02B290u:
        case 0x02B51Cu: case 0x02B624u: case 0x02BF68u:
        case 0x0366A6u: case 0x0366BCu: case 0x0366C2u:
        case 0x0366C6u: case 0x0366CCu: case 0x0366D0u:
        case 0x0366F0u: case 0x0366F4u: case 0x0366FAu: case 0x0366FEu:
        case 0x03670Cu: case 0x036716u: case 0x03671Au:
        case 0x036794u: case 0x03679Au:
        case 0x03679Eu: case 0x0367A2u: case 0x0367A6u:
        case 0x0367DEu: case 0x036948u: case 0x036952u:
        case 0x03695Cu: case 0x03696Au: case 0x036982u:
        case 0x036988u: case 0x03698Cu: case 0x036990u: case 0x036994u:
            rdb_boss_diag_probe(pc);
            break;
        default:
            if ((pc >= 0x001488u && pc <= 0x001552u) ||
                pc == 0x0017A4u || pc == 0x0019D4u)
                rdb_boss_diag_probe(pc);
            break;
        }
    }
    if (g_rdb_insn_pending) rdb_on_insn_slow(pc);
}

/* Per-instruction breakpoint table (separate from block breaks). */
int  rdb_insn_break_add(uint32_t pc);
void rdb_insn_break_clear_all(void);
int  rdb_insn_break_count(void);
uint32_t rdb_insn_break_get(int i);

/* Single-instruction step — park on the next rdb_on_insn. */
void rdb_cmd_step_insn(void);

/* Where we parked (only valid while rdb_is_parked()). */
uint32_t rdb_parked_pc(void);

/* =========================================================================
 * Stage-A instrumentation: VBla-fire event ring.
 *
 * Records each call to the native VBla-fire site in glue_check_vblank.
 * Distribution over wall frames tells us whether native multi-fires per
 * wall frame — the specific measurement we need before considering the
 * cycle-pacing cap.
 *
 * Oracle is 1:1 by architecture (core calls RaiseVerticalInterruptIfNeeded
 * once per machine step). A step counter exposed below lets us
 * sanity-check that invariant rather than assume it.
 * ========================================================================= */

#define RDB_FIRE_REASON_THRESHOLD  0   /* glue_check_vblank while-loop */
#define RDB_FIRE_REASON_SUPPRESSED 1   /* IRQ mask blocked handler */
#define RDB_FIRE_REASON_FORCED     2   /* reserved: end-of-wall-frame force */

void     rdb_record_vbla_fire(uint32_t cycle_acc, uint64_t game_frame,
                              int reason);
void     rdb_record_iterate(void);

void     rdb_vbla_snapshot_begin(void);
void     rdb_vbla_snapshot_end  (void);
uint32_t rdb_vbla_snapshot_count(void);
uint64_t rdb_iterate_count(void);

/* JSON-format the snapshot entry at index `i`:
 *   {"wall":W,"acc":A,"game":G,"reason":R}
 * where `wall` is cmd_server's wall-frame counter AT fire, and `game`
 * is the native build's g_frame_count (both 0 on oracle). */
int  rdb_vbla_format_entry(uint32_t i, char *buf, size_t buflen);

/* Stage-C instruction-count accessors. Each returns the counter that
 * lives on its build: native returns g_native_insn_count (ticked from
 * generated C), oracle returns g_oracle_insn_count (ticked from
 * t3_pre_insn). The other counter is 0 on each build. */
uint64_t rdb_native_insn_count(void);
uint64_t rdb_oracle_insn_count(void);

#endif /* SONIC_REVERSE_DEBUG */
