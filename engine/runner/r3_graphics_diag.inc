/* Opt-in Round 3 stage-transition graphics capture.
 * Included by reverse_debug.c so it shares the existing bus tap and CPU state.
 * All reads are observational; no guest memory, VDP state, or scheduler fields
 * are written by this module. */

#include "video/genesis_machine.h"

#define R3_PRE_CAP       96u
#define R3_EVENT_CAP    512u
#define R3_SNAPSHOT_CAP  32u
#define R3_DISPATCH_WATCH_COUNT 3u
#define R3_SAT_BYTES 0x280u
#define R3_VRAM_BYTES GVDP_VRAM_SIZE
#define R3_DATA_VRAM 0x1u
#define R3_DATA_CRAM 0x3u
#define R3_DATA_VSRAM 0x5u

static const uint32_t s_r3_dispatch_targets[R3_DISPATCH_WATCH_COUNT] = {
    0x00202Cu, 0x0393CAu, 0x000FA6u
};

enum {
    R3_EV_MEM = 1,
    R3_EV_PROBE,
    R3_EV_DISPATCH_MISS,
    R3_EV_VDP_REG,
    R3_EV_VDP_CMD,
    R3_EV_VDP_DMA,
    R3_EV_VDP_FILL_ARM,
    R3_EV_VDP_COPY,
    R3_EV_VDP_SKIP,
    R3_EV_VDP_DATA_RUN
};

enum {
    R3_SNAP_STAGE_TRIGGER = 1,
    R3_SNAP_LOADER_PROBE,
    R3_SNAP_DMA_COMPLETE,
    R3_SNAP_SHUTDOWN
};

typedef struct {
    uint64_t seq;
    uint32_t frame, epoch, vdp_seq, pc, func;
    uint32_t arg0, arg1, arg2, arg3;
    uint32_t data_count, data_hash, first_pc, last_pc;
    uint32_t stage_cb, stage_next, zone, zone_flags;
    uint32_t cb_2a, cb_2e, cb_7a, cb_82;
    uint32_t d0, d1, a0, a1, a2, a5, a6, a7;
    uint16_t sr, selector_state;
    uint8_t kind, stage, vdp_code, vdp_reason;
} R3Event;

typedef struct {
    uint64_t seq;
    uint32_t frame, epoch, pc, func, vdp_seq;
    uint32_t src, dst, words, destination_hash;
    uint32_t plane_a_hash, plane_b_hash, window_hash, sat_hash, hscroll_hash;
    uint32_t vram_hash, cram_hash, vsram_hash;
    uint16_t plane_a_base, plane_b_base, window_base, sat_base, hscroll_base;
    uint16_t map_bytes;
    uint8_t reason, stage, zone, display;
    uint8_t regs[24];
    uint8_t code, reg15, dma_mode, reserved;
} R3Snapshot;

/* A pair of bounded raw display images closes the gap left by hash-only DMA
 * snapshots: the first watched stage-2 dispatch miss and normal shutdown. */
typedef struct {
    uint64_t seq;
    uint32_t frame, epoch, vdp_seq, pc, func;
    uint16_t sat_base;
    uint8_t stage, zone, valid;
    uint8_t regs[GVDP_NUM_REGISTERS];
    uint8_t vram[R3_VRAM_BYTES];
    uint16_t cram[GVDP_CRAM_ENTRIES];
    uint16_t vsram[GVDP_VSRAM_ENTRIES];
    uint8_t sat_staging[R3_SAT_BYTES];
} R3DisplayImage;

typedef struct {
    int initialized, dumped, enabled, triggered, trigger_reason;
    uint64_t seq, events_total, events_dropped, pre_total, pre_overwritten;
    uint64_t snapshots_total, snapshots_dropped, dispatch_misses;
    uint64_t dispatch_stage2_total;
    uint64_t dispatch_stage2_count[R3_DISPATCH_WATCH_COUNT];
    uint64_t probe_total, probe_suppressed, frame_regressions;
    uint32_t last_frame, epoch;
    int have_frame;
    uint32_t pre_write, pre_count, event_count;
    R3Event pre[R3_PRE_CAP];
    R3Event events[R3_EVENT_CAP];
    R3Event dispatch_first[R3_DISPATCH_WATCH_COUNT];
    uint8_t dispatch_first_valid[R3_DISPATCH_WATCH_COUNT];
    uint32_t snapshot_count;
    R3Snapshot snapshots[R3_SNAPSHOT_CAP];
    R3Snapshot latest_snapshot;
    uint8_t have_latest_snapshot;
    R3DisplayImage first_dispatch_display, shutdown_display;
    uint8_t have_first_dispatch_display, have_shutdown_display;
    uint8_t data_run_active;
    R3Event data_run;
    uint32_t data_run_last_addr;
    uint16_t data_run_inc;
    uint8_t data_run_code;
    uint32_t probe_pc[32], probe_count[32], probe_snapshot_mask;
} R3Diag;

int g_rdb_r3_diag_enabled = 0;
uint32_t g_rdb_r3_diag_pc = 0;
static R3Diag s_r3_diag;

static uint8_t r3_read8(uint32_t addr)
{
    return g_ram[addr & 0xFFFFu];
}

static uint16_t r3_read16(uint32_t addr)
{
    uint32_t o = addr & 0xFFFFu;
    return (uint16_t)(((uint16_t)g_ram[o] << 8) | g_ram[(o + 1u) & 0xFFFFu]);
}

static uint32_t r3_read32(uint32_t addr)
{
    uint32_t o = addr & 0xFFFFu;
    return ((uint32_t)g_ram[o] << 24) |
           ((uint32_t)g_ram[(o + 1u) & 0xFFFFu] << 16) |
           ((uint32_t)g_ram[(o + 2u) & 0xFFFFu] << 8) |
           g_ram[(o + 3u) & 0xFFFFu];
}

static uint32_t r3_fnv_byte(uint32_t h, uint8_t b)
{
    return (h ^ b) * 16777619u;
}

static uint32_t r3_fnv_vram(const uint8_t *p, uint32_t addr, uint32_t len)
{
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < len; ++i)
        h = r3_fnv_byte(h, p[(addr + i) & 0xFFFFu]);
    return h;
}

static uint32_t r3_fnv_cram(const uint16_t *p)
{
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < GVDP_CRAM_ENTRIES; ++i) {
        h = r3_fnv_byte(h, (uint8_t)(p[i] >> 8));
        h = r3_fnv_byte(h, (uint8_t)p[i]);
    }
    return h;
}

static uint32_t r3_fnv_vsram(const uint16_t *p)
{
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < GVDP_VSRAM_ENTRIES; ++i) {
        h = r3_fnv_byte(h, (uint8_t)(p[i] >> 8));
        h = r3_fnv_byte(h, (uint8_t)p[i]);
    }
    return h;
}

static uint32_t r3_fnv_vdp_words(const GVDP *v, uint8_t code, uint16_t dst,
                                 uint32_t words, uint16_t inc)
{
    uint32_t h = 2166136261u;
    uint32_t addr = dst;
    if (words > 0x10000u) words = 0x10000u;
    for (uint32_t i = 0; i < words; ++i, addr += inc) {
        uint16_t w = 0;
        switch (code & 0x0Fu) {
        case R3_DATA_VRAM: {
            uint32_t a = addr & 0xFFFEu;
            h = r3_fnv_byte(h, v->vram[a]);
            h = r3_fnv_byte(h, v->vram[(a + 1u) & 0xFFFFu]);
            continue;
        }
        case R3_DATA_CRAM:
            w = v->cram[(addr >> 1) & (GVDP_CRAM_ENTRIES - 1u)];
            break;
        case R3_DATA_VSRAM:
            w = v->vsram[(addr >> 1) % GVDP_VSRAM_ENTRIES];
            break;
        default:
            return 0;
        }
        h = r3_fnv_byte(h, (uint8_t)(w >> 8));
        h = r3_fnv_byte(h, (uint8_t)w);
    }
    return h;
}

static uint32_t r3_frame_now(void)
{
    uint32_t f = cmd_server_current_frame();
    if (s_r3_diag.have_frame && f < s_r3_diag.last_frame) {
        s_r3_diag.epoch++;
        s_r3_diag.frame_regressions++;
    }
    s_r3_diag.last_frame = f;
    s_r3_diag.have_frame = 1;
    return f;
}

static void r3_fill_context(R3Event *e, uint8_t kind)
{
    memset(e, 0, sizeof(*e));
    e->seq = ++s_r3_diag.seq;
    e->frame = r3_frame_now();
    e->epoch = s_r3_diag.epoch;
    e->pc = g_rdb_r3_diag_pc & 0xFFFFFFu;
    e->func = g_rdb_current_func & 0xFFFFFFu;
    e->kind = kind;
    e->stage = r3_read8(0xFF37A6u);
    e->zone = r3_read8(0xFF37AAu);
    e->zone_flags = r3_read16(0xFF379Cu);
    e->selector_state = r3_read16(0xFF0034u);
    e->stage_cb = r3_read32(0xFF002Au);
    e->stage_next = r3_read32(0xFF002Eu);
    e->cb_7a = r3_read32(0xFF007Au);
    e->cb_82 = r3_read32(0xFF0082u);
    e->d0 = g_cpu.D[0]; e->d1 = g_cpu.D[1];
    e->a0 = g_cpu.A[0]; e->a1 = g_cpu.A[1]; e->a2 = g_cpu.A[2];
    e->a5 = g_cpu.A[5]; e->a6 = g_cpu.A[6]; e->a7 = g_cpu.A[7];
    e->sr = g_cpu.SR;
}

static void r3_store_raw(const R3Event *e)
{
    s_r3_diag.events_total++;
    if (s_r3_diag.event_count < R3_EVENT_CAP)
        s_r3_diag.events[s_r3_diag.event_count++] = *e;
    else
        s_r3_diag.events_dropped++;
}

static void r3_push(const R3Event *e)
{
    if (s_r3_diag.triggered) {
        r3_store_raw(e);
        return;
    }
    s_r3_diag.pre_total++;
    if (s_r3_diag.pre_count == R3_PRE_CAP)
        s_r3_diag.pre_overwritten++;
    else
        s_r3_diag.pre_count++;
    s_r3_diag.pre[s_r3_diag.pre_write % R3_PRE_CAP] = *e;
    s_r3_diag.pre_write++;
}

static void r3_flush_data_run(void)
{
    if (!s_r3_diag.data_run_active) return;
    r3_push(&s_r3_diag.data_run);
    s_r3_diag.data_run_active = 0;
}

static void r3_snapshot(const GVDP *v, uint8_t reason, uint32_t vdp_seq,
                        uint32_t src, uint16_t dst, uint32_t words,
                        uint8_t dma_code)
{
    if (!g_rdb_r3_diag_enabled) return;
    s_r3_diag.snapshots_total++;
    R3Snapshot *s;
    if (s_r3_diag.snapshot_count < R3_SNAPSHOT_CAP) {
        s = &s_r3_diag.snapshots[s_r3_diag.snapshot_count++];
    } else if (reason == R3_SNAP_SHUTDOWN) {
        s = &s_r3_diag.latest_snapshot;
    } else {
        s_r3_diag.snapshots_dropped++;
        return;
    }
    memset(s, 0, sizeof(*s));
    s->seq = ++s_r3_diag.seq;
    s->frame = r3_frame_now();
    s->epoch = s_r3_diag.epoch;
    s->pc = g_rdb_r3_diag_pc & 0xFFFFFFu;
    s->func = g_rdb_current_func & 0xFFFFFFu;
    s->vdp_seq = vdp_seq;
    s->src = src; s->dst = dst; s->words = words;
    s->reason = reason;
    s->stage = r3_read8(0xFF37A6u);
    s->zone = r3_read8(0xFF37AAu);
    memcpy(s->regs, v->reg, sizeof(s->regs));
    s->code = v->code; s->reg15 = v->reg[0x0F];
    s->dma_mode = v->reg[0x17] & 0xC0u;
    s->display = (uint8_t)((v->reg[0x01] >> 6) & 1u);
    s->plane_a_base = (uint16_t)((v->reg[0x02] & 0x38u) << 10);
    s->window_base = (uint16_t)((v->reg[0x03] & 0x3Eu) << 10);
    s->plane_b_base = (uint16_t)((v->reg[0x04] & 0x07u) << 13);
    s->sat_base = (uint16_t)((v->reg[0x05] & 0x7Fu) << 9);
    s->hscroll_base = (uint16_t)((v->reg[0x0D] & 0x3Fu) << 10);
    {
        uint32_t cols = (v->reg[0x10] & 1u) ? 64u : 32u;
        uint32_t rows = (v->reg[0x10] & 2u) ? 64u : 32u;
        s->map_bytes = (uint16_t)(cols * rows * 2u);
    }
    s->vram_hash = r3_fnv_vram(v->vram, 0, GVDP_VRAM_SIZE);
    s->cram_hash = r3_fnv_cram(v->cram);
    s->vsram_hash = r3_fnv_vsram(v->vsram);
    s->plane_a_hash = r3_fnv_vram(v->vram, s->plane_a_base, s->map_bytes);
    s->plane_b_hash = r3_fnv_vram(v->vram, s->plane_b_base, s->map_bytes);
    s->window_hash = r3_fnv_vram(v->vram, s->window_base, 0x1000u);
    s->sat_hash = r3_fnv_vram(v->vram, s->sat_base, 640u);
    s->hscroll_hash = r3_fnv_vram(v->vram, s->hscroll_base, 0x400u);
    if (words)
        s->destination_hash = r3_fnv_vdp_words(v, dma_code, dst, words, v->reg[0x0F]);
    if (s == &s_r3_diag.latest_snapshot)
        s_r3_diag.have_latest_snapshot = 1;
}

static void r3_capture_display(R3DisplayImage *image, const GVDP *v)
{
    if (!g_rdb_r3_diag_enabled || !s_r3_diag.triggered || !image || !v) return;
    image->seq = ++s_r3_diag.seq;
    image->frame = r3_frame_now();
    image->epoch = s_r3_diag.epoch;
    image->vdp_seq = g_gvdp_event_seq;
    image->pc = g_rdb_r3_diag_pc & 0xFFFFFFu;
    image->func = g_rdb_current_func & 0xFFFFFFu;
    image->stage = r3_read8(0xFF37A6u);
    image->zone = r3_read8(0xFF37AAu);
    image->sat_base = (uint16_t)((v->reg[0x05] & 0x7Fu) << 9);
    memcpy(image->regs, v->reg, sizeof(image->regs));
    memcpy(image->vram, v->vram, sizeof(image->vram));
    memcpy(image->cram, v->cram, sizeof(image->cram));
    memcpy(image->vsram, v->vsram, sizeof(image->vsram));
    for (uint32_t i = 0; i < R3_SAT_BYTES; ++i)
        image->sat_staging[i] = g_ram[(0xF500u + i) & 0xFFFFu];
    image->valid = 1;
}

static void r3_begin_capture(uint8_t reason, const R3Event *trigger)
{
    if (s_r3_diag.triggered) return;
    r3_flush_data_run();
    s_r3_diag.triggered = 1;
    s_r3_diag.trigger_reason = reason;
    uint32_t start = s_r3_diag.pre_count < R3_PRE_CAP ? 0u : s_r3_diag.pre_write % R3_PRE_CAP;
    for (uint32_t i = 0; i < s_r3_diag.pre_count; ++i)
        r3_store_raw(&s_r3_diag.pre[(start + i) % R3_PRE_CAP]);
    if (trigger) r3_store_raw(trigger);
    r3_snapshot(&g_machine.vdp, R3_SNAP_STAGE_TRIGGER,
                g_gvdp_event_seq, 0, 0, 0, 0);
}

static int r3_is_memory_watch(uint32_t addr)
{
    if (addr >= 0xFF37A6u && addr <= 0xFF37ABu) return 1;
    if (addr >= 0xFF379Au && addr <= 0xFF379Fu) return 1;
    if (addr >= 0xFF002Au && addr <= 0xFF0031u) return 1;
    if (addr == 0xFF0034u || addr == 0xFF0035u) return 1;
    if (addr >= 0xFF007Au && addr <= 0xFF007Du) return 1;
    if (addr >= 0xFF0082u && addr <= 0xFF0085u) return 1;
    if (addr >= 0xFF9C10u && addr <= 0xFF9C17u) return 1;
    return 0;
}

void rdb_r3_diag_write(uint32_t byte_address, uint8_t before, uint8_t value)
{
    if (!g_rdb_r3_diag_enabled) return;
    uint32_t addr = byte_address & 0xFFFFFFu;
    if (!r3_is_memory_watch(addr)) return;
    r3_flush_data_run();
    R3Event e;
    r3_fill_context(&e, R3_EV_MEM);
    e.arg0 = addr; e.arg1 = before; e.arg2 = value;
    if (!s_r3_diag.triggered && addr == 0xFF37A6u && value == 2u && before != value) {
        r3_begin_capture(R3_SNAP_STAGE_TRIGGER, &e);
        return;
    }
    r3_push(&e);
}

static int r3_probe_index(uint32_t pc)
{
    static const uint32_t pcs[] = {
        0x00F418u, 0x00F432u, 0x00F440u, 0x0046FAu, 0x00460Eu,
        0x004264u, 0x0115C0u, 0x0115CAu, 0x0115CEu, 0x0115D2u,
        0x0115D6u, 0x0115DAu, 0x0115DEu, 0x0115E2u, 0x0115E6u,
        0x01165Au, 0x01169Eu, 0x0116ACu, 0x011924u, 0x0119F2u,
        0x00202Cu, 0x0393CAu, 0x000FA6u, 0x003326u, 0x00099Au,
        0x0390E2u
    };
    for (int i = 0; i < (int)(sizeof(pcs) / sizeof(pcs[0])); ++i)
        if (pcs[i] == (pc & 0xFFFFFFu)) return i;
    return -1;
}

void rdb_r3_diag_probe(uint32_t pc)
{
    if (!g_rdb_r3_diag_enabled) return;
    int idx = r3_probe_index(pc);
    if (idx < 0) return;
    if (!s_r3_diag.triggered && r3_read8(0xFF37A6u) == 2u) {
        R3Event trigger;
        r3_fill_context(&trigger, R3_EV_PROBE);
        trigger.arg0 = pc & 0xFFFFFFu;
        r3_begin_capture(R3_SNAP_LOADER_PROBE, &trigger);
        return;
    }
    if (!s_r3_diag.triggered) {
        R3Event pre;
        r3_fill_context(&pre, R3_EV_PROBE);
        pre.arg0 = pc & 0xFFFFFFu;
        r3_push(&pre);
        return;
    }
    s_r3_diag.probe_total++;
    uint32_t count = s_r3_diag.probe_count[idx]++;
    if (count >= 6u) { s_r3_diag.probe_suppressed++; return; }
    r3_flush_data_run();
    R3Event e;
    r3_fill_context(&e, R3_EV_PROBE);
    e.arg0 = pc & 0xFFFFFFu; e.arg1 = count;
    r3_push(&e);
    if ((pc == 0x00F440u || pc == 0x0046FAu || pc == 0x00460Eu ||
         pc == 0x0115C0u || pc == 0x01165Au) &&
        !(s_r3_diag.probe_snapshot_mask & (1u << idx))) {
        s_r3_diag.probe_snapshot_mask |= (1u << idx);
        r3_snapshot(&g_machine.vdp, R3_SNAP_LOADER_PROBE,
                    g_gvdp_event_seq, 0, 0, 0, 0);
    }
}

void rdb_r3_diag_dispatch_miss(uint32_t target)
{
    if (!g_rdb_r3_diag_enabled) return;
    target &= 0xFFFFFFu;
    uint32_t target_index = R3_DISPATCH_WATCH_COUNT;
    for (uint32_t i = 0; i < R3_DISPATCH_WATCH_COUNT; ++i) {
        if (s_r3_dispatch_targets[i] == target) {
            target_index = i;
            break;
        }
    }
    if (target_index == R3_DISPATCH_WATCH_COUNT) return;
    r3_flush_data_run();
    R3Event e;
    r3_fill_context(&e, R3_EV_DISPATCH_MISS);
    e.arg0 = target;
    s_r3_diag.dispatch_misses++;
    if (!s_r3_diag.triggered && e.stage == 2u)
        r3_begin_capture(R3_SNAP_LOADER_PROBE, &e);
    else
        r3_push(&e);
    if (s_r3_diag.triggered && e.stage == 2u) {
        s_r3_diag.dispatch_stage2_total++;
        s_r3_diag.dispatch_stage2_count[target_index]++;
        if (!s_r3_diag.dispatch_first_valid[target_index]) {
            s_r3_diag.dispatch_first[target_index] = e;
            s_r3_diag.dispatch_first_valid[target_index] = 1;
        }
        if (!s_r3_diag.have_first_dispatch_display) {
            r3_capture_display(&s_r3_diag.first_dispatch_display, &g_machine.vdp);
            s_r3_diag.have_first_dispatch_display =
                s_r3_diag.first_dispatch_display.valid;
        }
    }
}

static int r3_vdp_event_relevant(uint8_t kind, uint8_t code)
{
    switch (kind) {
    case GVDP_EVT_REG:
        return code <= 0x17u;
    case GVDP_EVT_CMD:
    case GVDP_EVT_DMA_68K:
    case GVDP_EVT_DMA_FILL_ARM:
    case GVDP_EVT_DMA_COPY:
    case GVDP_EVT_DMA_SKIP:
        return 1;
    case GVDP_EVT_DATA:
        return (code & 0x0Fu) == R3_DATA_VRAM ||
               (code & 0x0Fu) == R3_DATA_CRAM ||
               (code & 0x0Fu) == R3_DATA_VSRAM;
    default:
        return 0;
    }
}

void rdb_r3_diag_vdp_event(const struct GVDP *vdp, uint32_t vdp_seq,
                           uint8_t kind, uint8_t code, uint16_t addr,
                           uint16_t value, uint16_t inc, uint16_t len,
                           uint32_t src, uint8_t reason)
{
    if (!g_rdb_r3_diag_enabled || !vdp || !r3_vdp_event_relevant(kind, code)) return;
    if (kind == GVDP_EVT_DATA) {
        uint32_t pc = g_rdb_r3_diag_pc & 0xFFFFFFu;
        if (s_r3_diag.data_run_active && s_r3_diag.data_run_code == code &&
            s_r3_diag.data_run_inc == inc &&
            s_r3_diag.data_run_last_addr == addr) {
            R3Event *run = &s_r3_diag.data_run;
            run->arg1 = addr;
            run->arg3 = value;
            run->data_count++;
            run->last_pc = pc;
            run->vdp_seq = vdp_seq;
            run->data_hash = r3_fnv_byte(run->data_hash, (uint8_t)(value >> 8));
            run->data_hash = r3_fnv_byte(run->data_hash, (uint8_t)value);
            s_r3_diag.data_run_last_addr = (uint16_t)(addr + inc);
            return;
        }
        r3_flush_data_run();
        R3Event *run = &s_r3_diag.data_run;
        r3_fill_context(run, R3_EV_VDP_DATA_RUN);
        run->vdp_seq = vdp_seq;
        run->arg0 = addr; run->arg1 = addr;
        run->arg2 = value; run->arg3 = value;
        run->data_count = 1;
        run->vdp_code = code;
        run->first_pc = pc; run->last_pc = pc;
        run->data_hash = r3_fnv_byte(2166136261u, (uint8_t)(value >> 8));
        run->data_hash = r3_fnv_byte(run->data_hash, (uint8_t)value);
        s_r3_diag.data_run_last_addr = (uint16_t)(addr + inc);
        s_r3_diag.data_run_inc = inc;
        s_r3_diag.data_run_code = code;
        s_r3_diag.data_run_active = 1;
        return;
    }
    r3_flush_data_run();
    R3Event e;
    uint8_t event_kind = R3_EV_VDP_CMD;
    if (kind == GVDP_EVT_REG) event_kind = R3_EV_VDP_REG;
    else if (kind == GVDP_EVT_DMA_68K) event_kind = R3_EV_VDP_DMA;
    else if (kind == GVDP_EVT_DMA_FILL_ARM) event_kind = R3_EV_VDP_FILL_ARM;
    else if (kind == GVDP_EVT_DMA_COPY) event_kind = R3_EV_VDP_COPY;
    else if (kind == GVDP_EVT_DMA_SKIP) event_kind = R3_EV_VDP_SKIP;
    r3_fill_context(&e, event_kind);
    e.vdp_seq = vdp_seq;
    e.arg0 = addr; e.arg1 = value; e.arg2 = src;
    e.arg3 = ((uint32_t)len << 16) | inc;
    e.vdp_code = code;
    e.vdp_reason = reason;
    if (!s_r3_diag.triggered && e.stage == 2u)
        r3_begin_capture(R3_SNAP_LOADER_PROBE, &e);
    else
        r3_push(&e);
}

void rdb_r3_diag_dma_complete(const struct GVDP *vdp, uint8_t kind,
                              uint32_t vdp_seq, uint32_t src, uint16_t dst,
                              uint32_t words, uint8_t code)
{
    if (!g_rdb_r3_diag_enabled || !vdp) return;
    if (!s_r3_diag.triggered && r3_read8(0xFF37A6u) == 2u) {
        R3Event trigger;
        r3_fill_context(&trigger, R3_EV_VDP_DMA);
        trigger.vdp_seq = vdp_seq; trigger.arg0 = dst;
        trigger.arg1 = words; trigger.arg2 = src; trigger.arg3 = kind;
        r3_begin_capture(R3_SNAP_LOADER_PROBE, &trigger);
    }
    if (!s_r3_diag.triggered) return;
    r3_flush_data_run();
    r3_snapshot(vdp, R3_SNAP_DMA_COMPLETE, vdp_seq, src, dst, words, code);
}

static const char *r3_kind_name(uint8_t kind)
{
    switch (kind) {
    case R3_EV_MEM: return "mem";
    case R3_EV_PROBE: return "rom_probe";
    case R3_EV_DISPATCH_MISS: return "dispatch_miss";
    case R3_EV_VDP_REG: return "vdp_reg";
    case R3_EV_VDP_CMD: return "vdp_cmd";
    case R3_EV_VDP_DMA: return "vdp_dma";
    case R3_EV_VDP_FILL_ARM: return "vdp_fill_arm";
    case R3_EV_VDP_COPY: return "vdp_copy";
    case R3_EV_VDP_SKIP: return "vdp_skip";
    case R3_EV_VDP_DATA_RUN: return "vdp_data_run";
    default: return "unknown";
    }
}

static void r3_write_json_event(FILE *f, const R3Event *e, const char *record_kind)
{
    fprintf(f,
        "{\"kind\":\"%s\",\"seq\":%llu,\"frame\":%u,\"epoch\":%u,\"vdp_seq\":%u,"
        "\"type\":\"%s\",\"pc\":\"%06X\",\"func\":\"%06X\","
        "\"stage\":%u,\"zone\":%u,\"state\":%u,\"cb2a\":\"%08X\",\"cb2e\":\"%08X\","
        "\"cb7a\":\"%08X\",\"cb82\":\"%08X\",\"d0\":\"%08X\",\"d1\":\"%08X\","
        "\"a0\":\"%08X\",\"a1\":\"%08X\",\"a2\":\"%08X\",\"a5\":\"%08X\","
        "\"a6\":\"%08X\",\"a7\":\"%08X\",\"sr\":\"%04X\","
        "\"arg0\":\"%08X\",\"arg1\":\"%08X\",\"arg2\":\"%08X\",\"arg3\":\"%08X\","
        "\"count\":%u,\"hash\":\"%08X\",\"first_pc\":\"%06X\",\"last_pc\":\"%06X\","
        "\"vdp_code\":%u,\"vdp_reason\":%u}\n",
        record_kind, (unsigned long long)e->seq, e->frame, e->epoch, e->vdp_seq,
        r3_kind_name(e->kind), e->pc, e->func, e->stage, e->zone,
        e->selector_state, e->cb_2a, e->cb_2e, e->cb_7a, e->cb_82,
        e->d0, e->d1, e->a0, e->a1, e->a2, e->a5, e->a6, e->a7, e->sr,
        e->arg0, e->arg1, e->arg2, e->arg3, e->data_count, e->data_hash,
        e->first_pc, e->last_pc, e->vdp_code, e->vdp_reason);
}

static void r3_write_json_snapshot(FILE *f, const R3Snapshot *s, const char *record_kind)
{
    fprintf(f,
        "{\"kind\":\"%s\",\"seq\":%llu,\"frame\":%u,\"epoch\":%u,"
        "\"vdp_seq\":%u,\"reason\":%u,\"stage\":%u,\"zone\":%u,"
        "\"pc\":\"%06X\",\"func\":\"%06X\",\"src\":\"%06X\",\"dst\":\"%04X\","
        "\"words\":%u,\"dest_hash\":\"%08X\",\"plane_a_base\":\"%04X\","
        "\"plane_b_base\":\"%04X\",\"window_base\":\"%04X\",\"sat_base\":\"%04X\","
        "\"hscroll_base\":\"%04X\",\"map_bytes\":%u,\"display\":%u,\"code\":%u,"
        "\"reg15\":%u,\"dma_mode\":%u,\"vram_hash\":\"%08X\",\"cram_hash\":\"%08X\","
        "\"vsram_hash\":\"%08X\",\"plane_a_hash\":\"%08X\",\"plane_b_hash\":\"%08X\","
        "\"window_hash\":\"%08X\",\"sat_hash\":\"%08X\",\"hscroll_hash\":\"%08X\",\"regs\":[",
        record_kind, (unsigned long long)s->seq, s->frame, s->epoch, s->vdp_seq, s->reason,
        s->stage, s->zone, s->pc, s->func, s->src, s->dst, s->words,
        s->destination_hash, s->plane_a_base, s->plane_b_base, s->window_base,
        s->sat_base, s->hscroll_base, s->map_bytes, s->display, s->code,
        s->reg15, s->dma_mode, s->vram_hash, s->cram_hash, s->vsram_hash,
        s->plane_a_hash, s->plane_b_hash, s->window_hash, s->sat_hash,
        s->hscroll_hash);
    for (unsigned i = 0; i < sizeof(s->regs); ++i)
        fprintf(f, "%s%u", i ? "," : "", (unsigned)s->regs[i]);
    fputs("]}\n", f);
}

static void r3_write_hex(FILE *f, const uint8_t *bytes, size_t count)
{
    static const char hex[] = "0123456789ABCDEF";
    for (size_t i = 0; i < count; ++i) {
        fputc(hex[bytes[i] >> 4], f);
        fputc(hex[bytes[i] & 0x0Fu], f);
    }
}

static void r3_write_json_display_image(FILE *f, const R3DisplayImage *image,
                                        const char *record_kind)
{
    if (!image->valid) return;
    fprintf(f,
        "{\"kind\":\"%s\",\"seq\":%llu,\"frame\":%u,\"epoch\":%u,"
        "\"vdp_seq\":%u,\"stage\":%u,\"zone\":%u,\"pc\":\"%06X\","
        "\"func\":\"%06X\",\"sat_base\":\"%04X\",\"vram_bytes\":%u,"
        "\"cram_words\":%u,\"vsram_words\":%u,\"sat_staging_bytes\":%u,"
        "\"regs\":[",
        record_kind, (unsigned long long)image->seq, image->frame, image->epoch,
        image->vdp_seq, image->stage, image->zone, image->pc, image->func,
        image->sat_base, R3_VRAM_BYTES, GVDP_CRAM_ENTRIES,
        GVDP_VSRAM_ENTRIES, R3_SAT_BYTES);
    for (unsigned i = 0; i < sizeof(image->regs); ++i)
        fprintf(f, "%s%u", i ? "," : "", (unsigned)image->regs[i]);
    fputs("],\"vram_hex\":\"", f);
    r3_write_hex(f, image->vram, sizeof(image->vram));
    fputs("\",\"cram_words_hex\":\"", f);
    for (unsigned i = 0; i < GVDP_CRAM_ENTRIES; ++i)
        fprintf(f, "%04X", (unsigned)image->cram[i]);
    fputs("\",\"vsram_words_hex\":\"", f);
    for (unsigned i = 0; i < GVDP_VSRAM_ENTRIES; ++i)
        fprintf(f, "%04X", (unsigned)image->vsram[i]);
    fputs("\",\"sat_staging_hex\":\"", f);
    r3_write_hex(f, image->sat_staging, sizeof(image->sat_staging));
    fputs("\"}\n", f);
}

static void rdb_r3_diag_dump_once(void)
{
    if (!g_rdb_r3_diag_enabled || s_r3_diag.dumped) return;
    s_r3_diag.dumped = 1;
    r3_flush_data_run();
    time_t now = time(NULL);
    struct tm tmv;
#ifdef _WIN32
    localtime_s(&tmv, &now);
    int pid = _getpid();
#else
    localtime_r(&now, &tmv);
    int pid = (int)getpid();
#endif
    char path[256];
    snprintf(path, sizeof(path), "R3-graphics-trace-%04d%02d%02d-%02d%02d%02d-%d-%llu.jsonl",
             tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday,
             tmv.tm_hour, tmv.tm_min, tmv.tm_sec, pid,
             (unsigned long long)s_r3_diag.seq);
    FILE *f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "[R3-DIAG] failed to write %s\n", path); return; }
    fprintf(f,
        "{\"kind\":\"header\",\"schema\":3,\"env\":\"GENESIS_R3_DIAG=1\","
        "\"pre_capacity\":%u,\"event_capacity\":%u,\"snapshot_capacity\":%u,"
        "\"dispatch_first_capacity\":%u,\"snapshot_policy\":\"first-capacity-plus-shutdown\","
        "\"dispatch_display_images\":\"first-watched-stage2-miss-and-shutdown\","
        "\"display_image_bytes\":%zu,"
        "\"triggered\":%u,\"trigger_reason\":%u}\n",
        R3_PRE_CAP, R3_EVENT_CAP, R3_SNAPSHOT_CAP,
        R3_DISPATCH_WATCH_COUNT,
        R3_VRAM_BYTES + sizeof(((R3DisplayImage *)0)->cram) +
            sizeof(((R3DisplayImage *)0)->vsram) + R3_SAT_BYTES,
        (unsigned)s_r3_diag.triggered, (unsigned)s_r3_diag.trigger_reason);
    if (!s_r3_diag.triggered) {
        uint32_t start = s_r3_diag.pre_count < R3_PRE_CAP ? 0u : s_r3_diag.pre_write % R3_PRE_CAP;
        for (uint32_t i = 0; i < s_r3_diag.pre_count; ++i)
            r3_write_json_event(f, &s_r3_diag.pre[(start + i) % R3_PRE_CAP], "event");
    } else {
        for (uint32_t i = 0; i < s_r3_diag.event_count; ++i)
            r3_write_json_event(f, &s_r3_diag.events[i], "event");
    }
    for (uint32_t i = 0; i < s_r3_diag.snapshot_count; ++i)
        r3_write_json_snapshot(f, &s_r3_diag.snapshots[i], "snapshot");
    for (uint32_t i = 0; i < R3_DISPATCH_WATCH_COUNT; ++i) {
        if (s_r3_diag.dispatch_first_valid[i])
            r3_write_json_event(f, &s_r3_diag.dispatch_first[i], "dispatch_first");
    }
    uint64_t latest_snapshot_extra = 0;
    if (s_r3_diag.have_latest_snapshot && s_r3_diag.snapshot_count > 0 &&
        s_r3_diag.latest_snapshot.seq !=
            s_r3_diag.snapshots[s_r3_diag.snapshot_count - 1u].seq) {
        r3_write_json_snapshot(f, &s_r3_diag.latest_snapshot, "snapshot_shutdown");
        latest_snapshot_extra = 1;
    }
    r3_write_json_display_image(f, &s_r3_diag.first_dispatch_display,
                                "display_first_watched_dispatch");
    r3_write_json_display_image(f, &s_r3_diag.shutdown_display,
                                "display_shutdown");
    uint64_t snapshots_omitted = s_r3_diag.snapshots_total -
        s_r3_diag.snapshot_count - latest_snapshot_extra;
    fprintf(f,
        "{\"kind\":\"summary\",\"triggered\":%u,\"trigger_reason\":%u,"
        "\"event_capacity\":%u,\"events_retained_in_capture_buffer\":%u,"
        "\"events_total_in_capture_buffer\":%llu,"
        "\"events_dropped\":%llu,\"pre_capacity\":%u,\"pre_total\":%llu,"
        "\"pre_retained\":%u,\"pre_overwritten\":%llu,\"snapshots_capacity\":%u,"
        "\"snapshots_retained\":%u,\"snapshots_total\":%llu,\"snapshots_dropped\":%llu,"
        "\"snapshot_latest_retained\":%llu,\"dispatch_misses\":%llu,"
        "\"dispatch_stage2_total\":%llu,\"dispatch_first_records\":%u,"
        "\"dispatch_stage2_00202C\":%llu,\"dispatch_stage2_0393CA\":%llu,"
        "\"dispatch_stage2_000FA6\":%llu,\"probes\":%llu,\"probe_suppressed\":%llu,"
        "\"display_first_dispatch_retained\":%u,\"display_shutdown_retained\":%u,"
        "\"frame_regressions\":%llu,\"epoch\":%u}\n",
        (unsigned)s_r3_diag.triggered, (unsigned)s_r3_diag.trigger_reason,
        R3_EVENT_CAP, s_r3_diag.event_count,
        (unsigned long long)s_r3_diag.events_total,
        (unsigned long long)s_r3_diag.events_dropped,
        R3_PRE_CAP, (unsigned long long)s_r3_diag.pre_total,
        s_r3_diag.pre_count, (unsigned long long)s_r3_diag.pre_overwritten,
        R3_SNAPSHOT_CAP, s_r3_diag.snapshot_count,
        (unsigned long long)s_r3_diag.snapshots_total,
        (unsigned long long)snapshots_omitted,
        (unsigned long long)latest_snapshot_extra,
        (unsigned long long)s_r3_diag.dispatch_misses,
        (unsigned long long)s_r3_diag.dispatch_stage2_total,
        (unsigned)(s_r3_diag.dispatch_first_valid[0] +
                   s_r3_diag.dispatch_first_valid[1] +
                   s_r3_diag.dispatch_first_valid[2]),
        (unsigned long long)s_r3_diag.dispatch_stage2_count[0],
        (unsigned long long)s_r3_diag.dispatch_stage2_count[1],
        (unsigned long long)s_r3_diag.dispatch_stage2_count[2],
        (unsigned long long)s_r3_diag.probe_total,
        (unsigned long long)s_r3_diag.probe_suppressed,
        (unsigned)s_r3_diag.have_first_dispatch_display,
        (unsigned)s_r3_diag.have_shutdown_display,
        (unsigned long long)s_r3_diag.frame_regressions, s_r3_diag.epoch);
    fclose(f);
    fprintf(stderr,
        "[R3-DIAG] wrote %s (triggered=%u events=%u/%u dropped=%llu snapshots=%u/%u dropped=%llu pre-overwritten=%llu)\n",
        path, (unsigned)s_r3_diag.triggered, s_r3_diag.event_count, R3_EVENT_CAP,
        (unsigned long long)s_r3_diag.events_dropped,
        s_r3_diag.snapshot_count, R3_SNAPSHOT_CAP,
        (unsigned long long)snapshots_omitted,
        (unsigned long long)s_r3_diag.pre_overwritten);
}

void rdb_r3_diag_shutdown(void)
{
    r3_flush_data_run();
    if (g_rdb_r3_diag_enabled && s_r3_diag.triggered) {
        r3_snapshot(&g_machine.vdp, R3_SNAP_SHUTDOWN, g_gvdp_event_seq,
                    0, 0, 0, 0);
        r3_capture_display(&s_r3_diag.shutdown_display, &g_machine.vdp);
        s_r3_diag.have_shutdown_display = s_r3_diag.shutdown_display.valid;
    }
    rdb_r3_diag_dump_once();
}

static void rdb_r3_diag_init(void)
{
    if (s_r3_diag.initialized) return;
    s_r3_diag.initialized = 1;
    const char *env = getenv("GENESIS_R3_DIAG");
    if (env && strcmp(env, "1") == 0) {
        s_r3_diag.enabled = 1;
        g_rdb_r3_diag_enabled = 1;
        atexit(rdb_r3_diag_dump_once);
        fprintf(stderr,
            "[R3-DIAG] transition capture enabled (pre=%u events=%u snapshots=%u; trigger stage selector 1->2 or first stage-2 load probe)\n",
            R3_PRE_CAP, R3_EVENT_CAP, R3_SNAPSHOT_CAP);
    }
}
