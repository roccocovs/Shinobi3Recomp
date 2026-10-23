#include "genesis_runtime.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <process.h>
#define r4_getpid _getpid
#else
#include <unistd.h>
#define r4_getpid getpid
#endif

#define R4_TRACE_MAX_BYTES (4u * 1024u * 1024u)
#define R4_TRACE_RING_CAP  32768u
#define R4_TRACE_PRE_FRAMES 300u
#define R4_TRACE_POST_FRAMES 30u
#define R4_TRACE_MAX_FRAMES 3600u

uint32_t g_r4_scroll_trace_current_pc;

enum {
    EV_FRAME = 1, EV_STATE, EV_STAGE_SCROLL, EV_SCROLL_WRITE,
    EV_UPDATER, EV_SCROLL_CALC, EV_CONTINUATION, EV_VSRAM, EV_END
};

typedef struct R4TraceEvent {
    uint64_t seq;
    uint64_t frame;
    uint32_t pc, address, a0, old_value, new_value;
    uint32_t x[8];
    uint16_t state;
    uint8_t kind, width;
} R4TraceEvent;

static R4TraceEvent s_ring[R4_TRACE_RING_CAP];
static size_t s_ring_start, s_ring_count;
static uint64_t s_seq, s_ring_dropped, s_started_frame, s_phase2_restored_frame;
static FILE *s_file;
static size_t s_file_bytes;
static uint16_t s_last_vsram0;
static int s_phase_started[2], s_phase_restored[2], s_missing_active[2];
static int s_disabled, s_atexit_registered;
static char s_trace_path[128];

static void close_capture_at_exit(void);

static uint16_t ram16(uint32_t address)
{
    if (address < 0xFF0000u || address > 0xFFFFFEu) return 0;
    uint32_t o = address & 0xFFFFu;
    return (uint16_t)(((uint16_t)g_ram[o] << 8) | g_ram[(o + 1u) & 0xFFFFu]);
}

static uint32_t ram32(uint32_t address)
{
    return ((uint32_t)ram16(address) << 16) | ram16(address + 2u);
}

static int state_in_boss_window(uint16_t state)
{
    return state >= 0x0014u && state <= 0x003Cu;
}

static uint16_t manager_state(void) { return ram16(0xFF4186u); }
static uint16_t scroll_value(void) { return ram16(0x00FFF480u); }
static int boss_manager_active(void)
{
    return (ram16(0xFF4182u) & 0x8000u) != 0 &&
           state_in_boss_window(manager_state());
}

static const char *event_name(unsigned kind)
{
    switch (kind) {
    case EV_FRAME: return "frame";
    case EV_STATE: return "manager_state";
    case EV_STAGE_SCROLL: return "stage_default_scroll_write";
    case EV_SCROLL_WRITE: return "fff480_write";
    case EV_UPDATER: return "boss_updater_entry";
    case EV_SCROLL_CALC: return "boss_scroll_calculation";
    case EV_CONTINUATION: return "continuation_selected";
    case EV_VSRAM: return "vsram_write";
    case EV_END: return "capture_end";
    default: return "unknown";
    }
}

static int write_line(const char *line)
{
    if (!s_file || s_disabled) return 0;
    size_t n = strlen(line);
    if (n + s_file_bytes > R4_TRACE_MAX_BYTES) {
        static const char cap_line[] = "{\"event\":\"hard_cap_reached\"}\n";
        if (sizeof(cap_line) - 1u + s_file_bytes <= R4_TRACE_MAX_BYTES) {
            fwrite(cap_line, 1, sizeof(cap_line) - 1u, s_file);
            s_file_bytes += sizeof(cap_line) - 1u;
            fflush(s_file);
        }
        fclose(s_file);
        s_file = NULL;
        s_disabled = 1;
        return 0;
    }
    if (fwrite(line, 1, n, s_file) != n) {
        fclose(s_file);
        s_file = NULL;
        s_disabled = 1;
        return 0;
    }
    s_file_bytes += n;
    return 1;
}

static void serialize_event(const R4TraceEvent *e, char *out, size_t cap)
{
    snprintf(out, cap,
        "{\"seq\":%llu,\"guest_frame\":%llu,\"event\":\"%s\","
        "\"pc\":\"%06X\",\"address\":\"%06X\",\"a0\":\"%08X\","
        "\"state\":\"%04X\",\"width\":%u,\"old\":\"%08X\","
        "\"new\":\"%08X\",\"x\":[\"%08X\",\"%08X\",\"%08X\","
        "\"%08X\",\"%08X\",\"%08X\",\"%08X\",\"%08X\"]}\n",
        (unsigned long long)e->seq, (unsigned long long)e->frame,
        event_name(e->kind), e->pc & 0xFFFFFFu, e->address & 0xFFFFFFu,
        e->a0, e->state, e->width, e->old_value, e->new_value,
        e->x[0], e->x[1], e->x[2], e->x[3], e->x[4], e->x[5], e->x[6], e->x[7]);
}

static void write_event(const R4TraceEvent *e)
{
    char line[512];
    serialize_event(e, line, sizeof(line));
    (void)write_line(line);
}

static void append_ring(const R4TraceEvent *e)
{
    size_t at;
    if (s_ring_count < R4_TRACE_RING_CAP) {
        at = (s_ring_start + s_ring_count++) % R4_TRACE_RING_CAP;
    } else {
        at = s_ring_start;
        s_ring_start = (s_ring_start + 1u) % R4_TRACE_RING_CAP;
        s_ring_dropped++;
    }
    s_ring[at] = *e;
}

static void dump_recent_ring(void)
{
    uint64_t cutoff = g_frame_count > R4_TRACE_PRE_FRAMES
        ? g_frame_count - R4_TRACE_PRE_FRAMES : 0;
    for (size_t i = 0; i < s_ring_count && s_file; ++i) {
        const R4TraceEvent *e = &s_ring[(s_ring_start + i) % R4_TRACE_RING_CAP];
        if (e->frame >= cutoff) write_event(e);
    }
    if (s_file) fflush(s_file);
}

static void start_capture(unsigned phase)
{
    if (phase > 1u || s_disabled) return;
    s_phase_started[phase] = 1;
    s_missing_active[phase] = 1;
    s_started_frame = g_frame_count;
    if (s_file) return;
    unsigned long pid = (unsigned long)r4_getpid();
    snprintf(s_trace_path, sizeof(s_trace_path), "R4-scroll-provenance-%lu-%llu-%lu.jsonl",
             (unsigned long)time(NULL), (unsigned long long)g_frame_count, pid);
    s_file = fopen(s_trace_path, "wb");
    if (!s_file) { s_disabled = 1; return; }
    char header[1024];
    snprintf(header, sizeof(header),
        "{\"schema\":1,\"capture\":\"round4-boss-scroll-provenance\","
        "\"trigger_state\":\"%02X\",\"pretrigger_frames\":%u,"
        "\"output_cap_bytes\":%u,\"ring_dropped_events_before_trigger\":%llu,"
        "\"field_guide\":\"old/new are memory values except updater events where they are rte_pending/split_sp_popped; updater x=state,+24,+42,FFE004,D0,FFF480,stack0,stack4; calc x=state,+24,+42,FFE004,formula,D0,FFF480,A7; vsram x=code,address,dma,FFF480,FFE004,FF0006\"}\n",
        phase ? 0x38 : 0x28, R4_TRACE_PRE_FRAMES, R4_TRACE_MAX_BYTES,
        (unsigned long long)s_ring_dropped);
    if (!write_line(header)) return;

    dump_recent_ring();
    if (!s_atexit_registered) { atexit(close_capture_at_exit); s_atexit_registered = 1; }
    fprintf(stderr, "[r4-scroll] automatic provenance capture: %s\n", s_trace_path);
}

static void record_event(R4TraceEvent *e, int trigger_phase)
{
    if (s_disabled) return;
    int was_recording = s_file != NULL;
    e->seq = ++s_seq;
    e->frame = g_frame_count;
    append_ring(e);
    if (was_recording) write_event(e);
    if (trigger_phase >= 0 && !s_missing_active[trigger_phase])
        start_capture((unsigned)trigger_phase);
}

static void close_capture_at_exit(void)
{
    if (!s_file) return;
    R4TraceEvent end;
    memset(&end, 0, sizeof(end));
    end.kind = EV_END;
    end.pc = g_r4_scroll_trace_current_pc;
    end.state = manager_state();
    end.x[0] = s_phase_started[0]; end.x[1] = s_phase_restored[0];
    end.x[2] = s_phase_started[1]; end.x[3] = s_phase_restored[1];
    end.x[4] = s_ring_dropped; end.new_value = 2; /* process shutdown */
    record_event(&end, -1);
    if (s_file) { fclose(s_file); s_file = NULL; }
}

static R4TraceEvent base_event(unsigned kind, uint32_t pc)
{
    R4TraceEvent e;
    memset(&e, 0, sizeof(e));
    e.kind = (uint8_t)kind;
    e.pc = pc;
    e.state = manager_state();
    return e;
}

static int trigger_for(uint16_t state, uint16_t scroll)
{
    if (state == 0x0028u && scroll == 0x0100u && !s_missing_active[0]) return 0;
    if (state == 0x0038u && scroll == 0x0100u && !s_missing_active[1]) return 1;
    return -1;
}

void r4_scroll_trace_instruction(uint32_t pc, uint32_t a0)
{
    uint16_t state = manager_state();
    if (!s_file && (!boss_manager_active() || !state_in_boss_window(state))) return;
    if (pc != 0x02EE38u && !(pc >= 0x02EF28u && pc <= 0x02EF36u)) return;
    R4TraceEvent e = base_event(pc == 0x02EF36u ? EV_SCROLL_CALC : EV_UPDATER, pc);
    e.a0 = a0;
    e.address = g_cpu.A[7];
    e.x[0] = ram16(a0 + 4u);          /* effective object state */
    e.x[1] = ram16(a0 + 0x24u);       /* live +$24 input */
    e.x[2] = ram16(a0 + 0x42u);       /* live +$42 input */
    e.x[3] = ram16(0x00FFE004u);     /* stage scroll base */
    if (pc == 0x02EF36u) {
        e.x[4] = (uint16_t)(e.x[3] + e.x[2] - e.x[1]); /* ROM formula result */
        e.x[5] = g_cpu.D[0];                         /* effective D0 */
        e.x[6] = ram16(0x00FFF480u);                 /* destination before store */
        e.x[7] = g_cpu.A[7];
    } else {
        e.x[4] = g_cpu.D[0];
        e.x[5] = ram16(0x00FFF480u);
        e.x[6] = ram32(g_cpu.A[7]);                 /* return-slot contents */
        e.x[7] = ram32(g_cpu.A[7] + 4u);
    }
    e.old_value = (uint32_t)g_rte_pending;
    e.new_value = (uint32_t)g_split_sp_popped;
    record_event(&e, trigger_for(state, scroll_value()));
}

void r4_scroll_trace_continuation(uint32_t target, uint32_t pc)
{
    if ((target & 0xFFFFFFu) != 0x02EE38u) return;
    uint16_t state = manager_state();
    if (!s_file && (!boss_manager_active() || !state_in_boss_window(state))) return;
    R4TraceEvent e = base_event(EV_CONTINUATION, pc);
    e.address = target;
    e.a0 = g_cpu.A[0];
    e.x[0] = g_cpu.A[7];
    e.x[1] = ram32(g_cpu.A[7]);
    e.x[2] = ram32(g_cpu.A[7] + 4u);
    e.x[3] = (uint32_t)g_rte_pending;
    e.x[4] = (uint32_t)g_split_sp_popped;
    e.x[5] = g_cpu.D[0];
    e.x[6] = ram16(0x00FFF480u);
    record_event(&e, trigger_for(state, scroll_value()));
}

void r4_scroll_trace_memory_write(uint32_t addr, unsigned width,
                                  uint32_t old_value, uint32_t new_value,
                                  uint32_t pc)
{
    addr &= 0xFFFFFFu;
    uint16_t state = manager_state();
    uint16_t active = ram16(0xFF4182u);
    int is_state = addr == 0xFF4186u || addr == 0xFF4187u;
    int is_scroll = addr == 0xFFF480u;
    if (!is_state && !is_scroll) return;
    if (!s_file && !(active & 0x8000u) && !state_in_boss_window(state)) return;

    if (is_state) {
        uint16_t next_state = state;
        if (width == 2 && addr == 0xFF4186u) next_state = (uint16_t)new_value;
        else if (addr == 0xFF4186u) next_state = (uint16_t)((state & 0x00FFu) | ((new_value & 0xFFu) << 8));
        else next_state = (uint16_t)((state & 0xFF00u) | (new_value & 0xFFu));
        if (!s_file && !(active & 0x8000u) &&
            !state_in_boss_window(state) && !state_in_boss_window(next_state)) return;
        R4TraceEvent e = base_event(EV_STATE, pc);
        e.address = addr; e.width = (uint8_t)width;
        e.old_value = old_value; e.new_value = new_value;
        e.state = next_state;
        int trigger = trigger_for(next_state, scroll_value());
        record_event(&e, trigger);
        return;
    }

    R4TraceEvent e = base_event(pc >= 0x0023C0u && pc <= 0x0023D0u
                                ? EV_STAGE_SCROLL : EV_SCROLL_WRITE, pc);
    e.address = addr; e.width = (uint8_t)width;
    e.old_value = old_value; e.new_value = new_value;
    e.x[0] = ram16(0x00FFE004u);
    int trigger = trigger_for(state, (uint16_t)new_value);
    record_event(&e, trigger);
}

void r4_scroll_trace_vsram_write(uint32_t pc, unsigned index,
                                 uint16_t old_value, uint16_t new_value,
                                 uint8_t vdp_code, uint16_t vdp_address,
                                 uint8_t dma_active)
{
    if (index != 0) return;
    static uint64_t last_frame;
    static uint16_t last_value;
    static uint32_t last_pc;
    if (last_frame == g_frame_count && last_value == new_value && last_pc == pc)
        return; /* repeated identical H-INT transfers within one frame */
    last_frame = g_frame_count; last_value = new_value; last_pc = pc;
    s_last_vsram0 = new_value;
    uint16_t state = manager_state();
    if (!s_file && (!boss_manager_active() || !state_in_boss_window(state))) return;
    R4TraceEvent e = base_event(EV_VSRAM, pc);
    e.address = index; e.width = 2; e.old_value = old_value; e.new_value = new_value;
    e.x[0] = vdp_code;
    e.x[1] = vdp_address;
    e.x[2] = dma_active;
    e.x[3] = ram16(0x00FFF480u);
    e.x[4] = ram16(0x00FFE004u);
    e.x[5] = ram32(0xFF0006u);
    record_event(&e, trigger_for(state, scroll_value()));
}

void r4_scroll_trace_frame_end(void)
{
    if (s_disabled) return;
    if (!s_file && !boss_manager_active()) return;
    uint16_t state = manager_state();
    uint16_t scroll = scroll_value();
    R4TraceEvent e = base_event(EV_FRAME, g_r4_scroll_trace_current_pc);
    e.address = 0xFF4182u;
    e.x[0] = ram16(0xFF4182u);
    e.x[1] = scroll;
    e.x[2] = ram16(0x00FFE004u);
    e.x[3] = ram32(0xFF0006u);
    e.x[4] = s_last_vsram0;
    e.x[5] = (uint32_t)g_rte_pending;
    e.x[6] = (uint32_t)g_split_sp_popped;
    int trigger = trigger_for(state, scroll);
    record_event(&e, trigger);
    if (s_file) fflush(s_file);

    if (s_missing_active[0] && state == 0x0024u && scroll != 0x0100u) {
        s_phase_restored[0] = 1;
        s_missing_active[0] = 0;
    }
    if (s_phase_started[1] && state == 0x003Cu && scroll != 0x0100u) {
        if (!s_phase_restored[1]) s_phase2_restored_frame = g_frame_count;
        s_phase_restored[1] = 1;
        s_missing_active[1] = 0;
    }
    if (s_file && s_phase_restored[0] && s_phase_restored[1] &&
        g_frame_count >= s_phase2_restored_frame + R4_TRACE_POST_FRAMES) {
        R4TraceEvent end = base_event(EV_END, g_r4_scroll_trace_current_pc);
        end.x[0] = s_phase_started[0]; end.x[1] = s_phase_restored[0];
        end.x[2] = s_phase_started[1]; end.x[3] = s_phase_restored[1];
        end.x[4] = s_ring_dropped;
        end.x[5] = s_file_bytes;
        record_event(&end, -1);
        fclose(s_file); s_file = NULL; s_disabled = 1;
    } else if (s_file && g_frame_count > s_started_frame + R4_TRACE_MAX_FRAMES) {
        R4TraceEvent end = base_event(EV_END, g_r4_scroll_trace_current_pc);
        end.x[0] = s_phase_started[0]; end.x[1] = s_phase_restored[0];
        end.x[2] = s_phase_started[1]; end.x[3] = s_phase_restored[1];
        end.x[4] = s_ring_dropped; end.new_value = 1; /* bounded timeout */
        record_event(&end, -1);
        fclose(s_file); s_file = NULL; s_disabled = 1;
    }
}

#ifdef R4_SCROLL_TRACE_TESTING
void r4_scroll_trace_test_reset(void)
{
    if (s_file) fclose(s_file);
    memset(s_ring, 0, sizeof(s_ring));
    s_ring_start = s_ring_count = 0; s_seq = s_ring_dropped = 0;
    s_started_frame = s_phase2_restored_frame = 0;
    s_file = NULL; s_file_bytes = 0; s_last_vsram0 = 0;
    memset(s_trace_path, 0, sizeof(s_trace_path));
    memset(s_phase_started, 0, sizeof(s_phase_started));
    memset(s_phase_restored, 0, sizeof(s_phase_restored));
    memset(s_missing_active, 0, sizeof(s_missing_active));
    s_disabled = s_atexit_registered = 0;
}
const char *r4_scroll_trace_test_path(void) { return s_trace_path; }
#endif
