/*
 * reverse_debug.c — Tier-1 reverse-debugger implementation.
 *
 * Only compiled when SONIC_REVERSE_DEBUG=1. The generator emits a
 * `g_rdb_current_func = 0xXXXXXXu;` assignment at the entry of every
 * recompiled function body; this file installs itself as the shared
 * bus-write callback (g_mem_write_trace_fn, defined in
 * clownmdemu-core/bus-main-m68k.c) and records every bus write with
 * (frame, adr, val, width, func, caller) attribution.
 *
 * Native + oracle share the same bus-callback path, so Tier 1 observes
 * both. Range filter is applied before recording so 1M-entry ring never
 * drowns on unfiltered traffic.
 */

#if SONIC_REVERSE_DEBUG

#include "reverse_debug.h"
#include "cmd_server.h"
#include "glue.h"
#include "backend_decls.h"
#include "include/genesis_runtime.h"
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

/* Read $FFFExxxx as a longword from the 68K work-RAM mirror.
 * Used to capture Vint_runcount (the cross-binary state-sync key) in
 * every Tier-1 store ring entry. */
extern uint8_t g_ram[0x10000];
static inline uint32_t rdb_read_wram32(uint16_t off)
{
    return ((uint32_t)g_ram[off] << 24) | ((uint32_t)g_ram[(uint16_t)(off + 1)] << 16) |
           ((uint32_t)g_ram[(uint16_t)(off + 2)] << 8) | (uint32_t)g_ram[(uint16_t)(off + 3)];
}

/* ---- Narrow Round 2 boss producer/renderer trace ----------------------- */

#define RDB_BOSS_EVENT_CAP          8192u
#define RDB_BOSS_FIRST_WRITE_CAP    512u
#define RDB_BOSS_SAT_RING_CAP       16u
#define RDB_BOSS_FIRST_SAT_CAP     4u
#define RDB_BOSS_SAT_BYTES          640u /* H40 maximum: 80 eight-byte SAT rows */
#define RDB_BOSS_FOCUS_CAP          1024u
#define RDB_BOSS_FOCUS_FIRST_CAP    256u
#define RDB_BOSS_FOCUS_SAT_CAP      32u
#define RDB_BOSS_FOCUS_STAGE_CAP    256u

enum { RDB_BOSS_PROBE = 1, RDB_BOSS_ROOT_WRITE = 2,
       RDB_BOSS_FIELD_WRITE = 3 };

typedef struct {
    uint16_t active, type, state, word08, map, x, y, vx, vy, cursor;
    uint32_t callback, link;
} RdbBossObject;

typedef struct {
    uint16_t active, type, state, word08, map, x, y, vx, vy, cursor;
    uint16_t anim2a, timer2c, word2e, word30, word32, word34, word38;
    uint16_t word3a, word3c, word3e, word40, word42, word44;
    uint32_t callback, link;
} RdbBossFocusObject;

typedef struct {
    uint64_t seq;
    uint32_t frame, epoch, pc, func, addr, raw_manager, manager;
    uint32_t d[8], a[8];
    uint16_t sr;
    uint8_t kind, stage, value;
    RdbBossObject object;
} RdbBossEvent;

typedef struct {
    uint64_t seq;
    uint32_t frame, epoch, pc, func, vdp_seq, src, dst, len_words;
    uint32_t raw_manager, manager;
    uint8_t stage, code, reg5, reg11, reg13, staging_valid;
    uint16_t byte_count;
    uint8_t staging[RDB_BOSS_SAT_BYTES];
    uint8_t sat[RDB_BOSS_SAT_BYTES];
    RdbBossObject object;
} RdbBossSatEvent;

typedef struct {
    uint64_t seq;
    uint32_t frame, epoch, pc, func, addr, raw_manager, manager;
    uint32_t object_ptr, before, after;
    uint32_t d[8], a[8];
    uint16_t sr;
    uint8_t kind, stage, value, field;
    RdbBossFocusObject object;
} RdbBossFocusEvent;

int g_rdb_boss_diag_enabled = 0;
uint32_t g_rdb_boss_diag_pc = 0;

static struct {
    int initialized, dumped;
    uint64_t seq, event_total, event_overwritten;
    uint64_t probe_total, probe_non_r2, probe_invalid_manager, probe_recorded;
    uint64_t write_total, first_write_overflow;
    uint64_t sat_dma_stage, sat_dma_not_active_sat, sat_dma_no_manager;
    uint64_t sat_total, sat_overwritten, first_sat_overflow;
    uint64_t focus_total, focus_overwritten, focus_first_overflow;
    uint64_t focus_stage_write_total, focus_stage_write_overflow;
    uint64_t focus_sat_overflow, focus_anim_probe_total, focus_anim_manager_matches;
    uint64_t focus_anim_pool_manager_matches;
    uint64_t frame_regressions;
    uint32_t timeline_epoch, first_frame, last_frame;
    int have_frame;
    uint32_t event_write, event_count, first_write_count, last_manager;
    uint32_t sat_write, sat_count, first_sat_count;
    uint32_t focus_write, focus_count, focus_first_count, focus_sat_count;
    uint32_t focus_candidate, focus_manager, focus_field_object;
    uint32_t focus_render_manager, focus_render_frame, focus_render_epoch;
    uint32_t focus_render_write_count;
    uint32_t focus_render_state, focus_render_map, focus_render_cursor;
    uint16_t focus_render_active_word;
    uint32_t focus_probe_pc[32], focus_probe_frame[32], focus_probe_epoch[32];
    uint32_t focus_probe_next;
    uint32_t focus_sat_manager;
    uint16_t focus_sat_active, focus_sat_state, focus_sat_map, focus_sat_cursor;
    uint32_t focus_field_cache[10];
    uint8_t focus_candidate_bytes[0x54];
    uint8_t focus_constructor_active, focus_candidate_bytes_valid;
    uint8_t focus_candidate_confirmed, focus_render_active;
    uint8_t focus_field_cache_valid, focus_render_signature_valid;
    uint8_t focus_sat_signature_valid;
    uint32_t focus_last_sample_frame, focus_last_epoch, focus_stage_count;
    uint32_t focus_map_source_address, focus_map_source_index;
    uint8_t focus_last_valid, focus_map_source_valid;
    RdbBossFocusObject focus_last_object;
    RdbBossEvent events[RDB_BOSS_EVENT_CAP];
    RdbBossEvent first_writes[RDB_BOSS_FIRST_WRITE_CAP];
    RdbBossSatEvent sat_events[RDB_BOSS_SAT_RING_CAP];
    RdbBossSatEvent first_sat[RDB_BOSS_FIRST_SAT_CAP];
    RdbBossFocusEvent focus_events[RDB_BOSS_FOCUS_CAP];
    RdbBossFocusEvent focus_first[RDB_BOSS_FOCUS_FIRST_CAP];
    RdbBossFocusEvent focus_stage_events[RDB_BOSS_FOCUS_STAGE_CAP];
    RdbBossSatEvent focus_sat[RDB_BOSS_FOCUS_SAT_CAP];
} s_boss_diag;

static uint8_t rdb_boss_read8(uint32_t addr)
{
    return g_ram[addr & 0xFFFFu];
}

static uint16_t rdb_boss_read16(uint32_t addr)
{
    uint32_t o = addr & 0xFFFFu;
    return (uint16_t)(((uint16_t)g_ram[o] << 8) | g_ram[(o + 1u) & 0xFFFFu]);
}

static uint32_t rdb_boss_read32(uint32_t addr)
{
    uint32_t o = addr & 0xFFFFu;
    return ((uint32_t)g_ram[o] << 24) | ((uint32_t)g_ram[(o + 1u) & 0xFFFFu] << 16) |
           ((uint32_t)g_ram[(o + 2u) & 0xFFFFu] << 8) | g_ram[(o + 3u) & 0xFFFFu];
}

/* Accept only genuine 24-bit values or sign-extended 24-bit values, then
 * require an aligned WRAM address with enough room for the watched fields.
 * This is a capture-side validation, not a guest-memory accessor. */
static uint32_t rdb_boss_normalize_object(uint32_t raw)
{
    uint32_t high = raw >> 24;
    if (high != 0 && high != 0xFFu) return 0;
    uint32_t addr = raw & 0xFFFFFFu;
    if ((addr & 1u) || addr < 0xFF0000u || addr > 0xFFFFACu) return 0;
    return addr;
}

static void rdb_boss_snapshot(uint32_t *raw_out, uint32_t *ptr_out,
                             uint8_t *stage_out, RdbBossObject *out)
{
    uint32_t raw = rdb_boss_read32(0xFF5EE6u);
    uint32_t ptr = rdb_boss_normalize_object(raw);
    uint8_t stage = rdb_boss_read8(0xFF37A6u);
    memset(out, 0, sizeof(*out));
    if (ptr) {
        out->active   = rdb_boss_read16(ptr + 0x00u);
        out->type     = rdb_boss_read16(ptr + 0x02u);
        out->state    = rdb_boss_read16(ptr + 0x04u);
        out->word08   = rdb_boss_read16(ptr + 0x08u);
        out->map      = rdb_boss_read16(ptr + 0x0Au);
        out->x        = rdb_boss_read16(ptr + 0x0Cu);
        out->y        = rdb_boss_read16(ptr + 0x0Eu);
        out->vx       = rdb_boss_read16(ptr + 0x10u);
        out->vy       = rdb_boss_read16(ptr + 0x12u);
        out->cursor   = rdb_boss_read16(ptr + 0x28u);
        out->callback = rdb_boss_read32(ptr + 0x48u);
        out->link     = rdb_boss_read32(ptr + 0x50u);
    }
    if (raw_out) *raw_out = raw;
    if (ptr_out) *ptr_out = ptr;
    if (stage_out) *stage_out = stage;
}

static void rdb_boss_snapshot_at(uint32_t ptr, RdbBossObject *out)
{
    memset(out, 0, sizeof(*out));
    if (!ptr) return;
    out->active   = rdb_boss_read16(ptr + 0x00u);
    out->type     = rdb_boss_read16(ptr + 0x02u);
    out->state    = rdb_boss_read16(ptr + 0x04u);
    out->word08   = rdb_boss_read16(ptr + 0x08u);
    out->map      = rdb_boss_read16(ptr + 0x0Au);
    out->x        = rdb_boss_read16(ptr + 0x0Cu);
    out->y        = rdb_boss_read16(ptr + 0x0Eu);
    out->vx       = rdb_boss_read16(ptr + 0x10u);
    out->vy       = rdb_boss_read16(ptr + 0x12u);
    out->cursor   = rdb_boss_read16(ptr + 0x28u);
    out->callback = rdb_boss_read32(ptr + 0x48u);
    out->link     = rdb_boss_read32(ptr + 0x50u);
}

#include "r2_boss_focus.inc"
#include "r3_graphics_diag.inc"

static void rdb_boss_push_event(RdbBossEvent *e, int preserve_first_write)
{
    e->seq = ++s_boss_diag.seq;
    e->frame = cmd_server_current_frame();
    r2f_frame(e->frame);
    e->epoch = s_boss_diag.timeline_epoch;
    e->pc = g_rdb_boss_diag_pc & 0xFFFFFFu;
    e->func = g_rdb_current_func & 0xFFFFFFu;
    s_boss_diag.events[s_boss_diag.event_write % RDB_BOSS_EVENT_CAP] = *e;
    s_boss_diag.event_write++;
    s_boss_diag.event_total++;
    if (s_boss_diag.event_count < RDB_BOSS_EVENT_CAP)
        s_boss_diag.event_count++;
    else
        s_boss_diag.event_overwritten++;
    if (preserve_first_write) {
        s_boss_diag.write_total++;
        if (s_boss_diag.first_write_count < RDB_BOSS_FIRST_WRITE_CAP)
            s_boss_diag.first_writes[s_boss_diag.first_write_count++] = *e;
        else
            s_boss_diag.first_write_overflow++;
    }
}

void rdb_boss_diag_probe(uint32_t pc)
{
    if (!g_rdb_boss_diag_enabled) return;
    r2f_probe(pc);
    s_boss_diag.probe_total++;
    RdbBossEvent e;
    memset(&e, 0, sizeof(e));
    e.kind = RDB_BOSS_PROBE;
    rdb_boss_snapshot(&e.raw_manager, &e.manager, &e.stage, &e.object);
    if (e.stage != 1) { s_boss_diag.probe_non_r2++; return; }
    if (!e.manager) { s_boss_diag.probe_invalid_manager++; return; }
    s_boss_diag.last_manager = e.manager;
    /* Object callbacks and rendering hooks are useful here only when A0 is
     * the manager-rooted object; manager dispatch entries use their own
     * direct control flow and are retained regardless of A0. */
    if ((pc >= 0x001488u && pc <= 0x001552u) ||
        pc == 0x0017A4u || pc == 0x0019D4u ||
        (pc >= 0x0366A6u && pc <= 0x036990u)) {
        uint32_t a0 = g_cpu.A[0];
        if (rdb_boss_normalize_object(a0) != e.manager) return;
    }
    e.pc = pc & 0xFFFFFFu;
    e.func = g_rdb_current_func & 0xFFFFFFu;
    for (unsigned i = 0; i < 8; i++) { e.d[i] = g_cpu.D[i]; e.a[i] = g_cpu.A[i]; }
    e.sr = g_cpu.SR;
    rdb_boss_push_event(&e, 0);
    s_boss_diag.probe_recorded++;
}

static int rdb_boss_watched_field(uint32_t object, uint32_t addr)
{
    static const struct { uint8_t off, size; } fields[] = {
        {0x00,2},{0x02,2},{0x04,2},{0x08,2},{0x0A,2},{0x0C,2},
        {0x0E,2},{0x10,2},{0x12,2},{0x28,2},{0x48,4},{0x50,4}
    };
    for (unsigned i = 0; i < sizeof(fields)/sizeof(fields[0]); i++) {
        uint32_t lo = object + fields[i].off;
        if (addr >= lo && addr < lo + fields[i].size) return 1;
    }
    return 0;
}

void rdb_boss_diag_write(uint32_t byte_address, uint8_t value)
{
    if (!g_rdb_boss_diag_enabled) return;
    uint32_t addr = byte_address & 0xFFFFFFu;
    r2f_write(addr, value);
    if (addr == 0xFF5EE9u) r2f_root_write();
    RdbBossEvent e;
    memset(&e, 0, sizeof(e));
    if (addr >= 0xFF5EE6u && addr <= 0xFF5EE9u) {
        rdb_boss_snapshot(&e.raw_manager, &e.manager, &e.stage, &e.object);
        if (e.stage != 1) return;
        e.kind = RDB_BOSS_ROOT_WRITE;
        if (e.manager || e.raw_manager == 0)
            s_boss_diag.last_manager = e.manager;
    } else if (s_boss_diag.last_manager &&
               rdb_boss_watched_field(s_boss_diag.last_manager, addr)) {
        /* The manager address is cached by the last selected manager probe
         * or a root-pointer write, keeping the hot bus-tap filter bounded. */
        e.stage = rdb_boss_read8(0xFF37A6u);
        if (e.stage != 1) return;
        e.raw_manager = rdb_boss_read32(0xFF5EE6u);
        e.manager = s_boss_diag.last_manager;
        rdb_boss_snapshot_at(e.manager, &e.object);
        e.kind = RDB_BOSS_FIELD_WRITE;
    } else {
        return;
    }
    e.addr = addr;
    e.value = value;
    for (unsigned i = 0; i < 8; i++) { e.d[i] = g_cpu.D[i]; e.a[i] = g_cpu.A[i]; }
    e.sr = g_cpu.SR;
    rdb_boss_push_event(&e, 1);
}

void rdb_boss_diag_sat_dma(uint32_t vdp_seq, uint32_t src, uint32_t dst,
                           uint32_t len_words, uint8_t code,
                           uint8_t reg5, uint8_t reg11, uint8_t reg13,
                           const uint8_t *vram)
{
    if (!g_rdb_boss_diag_enabled || !vram) return;
    RdbBossSatEvent e;
    memset(&e, 0, sizeof(e));
    rdb_boss_snapshot(&e.raw_manager, &e.manager, &e.stage, &e.object);
    if (e.stage != 1) return;
    s_boss_diag.sat_dma_stage++;
    uint32_t sat_base = ((uint32_t)(reg5 & 0x7Fu) << 9) & 0xFFFFu;
    if ((code & 0x0Fu) != 0x01u || (dst & 0xFFFFu) != sat_base) {
        s_boss_diag.sat_dma_not_active_sat++;
        return;
    }
    if (!e.manager) {
        s_boss_diag.sat_dma_no_manager++;
        return;
    }
    uint32_t bytes = len_words * 2u;
    if (bytes > RDB_BOSS_SAT_BYTES) bytes = RDB_BOSS_SAT_BYTES;
    e.seq = ++s_boss_diag.seq;
    e.frame = cmd_server_current_frame();
    r2f_frame(e.frame);
    e.epoch = s_boss_diag.timeline_epoch;
    e.pc = g_rdb_boss_diag_pc & 0xFFFFFFu;
    e.func = g_rdb_current_func & 0xFFFFFFu;
    e.vdp_seq = vdp_seq;
    e.src = src & 0xFFFFFFu;
    e.dst = dst & 0xFFFFu;
    e.len_words = len_words;
    e.code = code;
    e.reg5 = reg5; e.reg11 = reg11; e.reg13 = reg13;
    e.byte_count = (uint16_t)bytes;
    uint32_t source = src & 0xFFFFFFu;
    if (source >= 0xFF0000u && source + bytes <= 0x1000000u) {
        memcpy(e.staging, &g_ram[source & 0xFFFFu], bytes);
        e.staging_valid = 1;
    }
    for (uint32_t i = 0; i < bytes; i++)
        e.sat[i] = vram[(sat_base + i) & 0xFFFFu];
    r2f_sat(&e);
    s_boss_diag.sat_events[s_boss_diag.sat_write % RDB_BOSS_SAT_RING_CAP] = e;
    s_boss_diag.sat_write++;
    s_boss_diag.sat_total++;
    if (s_boss_diag.sat_count < RDB_BOSS_SAT_RING_CAP)
        s_boss_diag.sat_count++;
    else
        s_boss_diag.sat_overwritten++;
    if (s_boss_diag.first_sat_count < RDB_BOSS_FIRST_SAT_CAP)
        s_boss_diag.first_sat[s_boss_diag.first_sat_count++] = e;
    else
        s_boss_diag.first_sat_overflow++;
}

static void rdb_boss_write_event(FILE *f, const char *label,
                                const RdbBossEvent *e)
{
    fprintf(f, "{\"kind\":\"%s\",\"event_type\":%u,\"seq\":%llu,\"frame\":%u,\"epoch\":%u,\"pc\":\"%06X\",\"func\":\"%06X\","
               "\"addr\":\"%06X\",\"value\":\"%02X\",\"stage\":%u,\"manager_raw\":\"%08X\",\"manager\":\"%06X\","
               "\"object\":{\"active\":\"%04X\",\"type\":\"%04X\",\"state\":\"%04X\",\"word08\":\"%04X\","
               "\"map\":\"%04X\",\"x\":\"%04X\",\"y\":\"%04X\",\"vx\":\"%04X\",\"vy\":\"%04X\","
               "\"cursor\":\"%04X\",\"callback\":\"%08X\",\"link\":\"%08X\"},\"sr\":\"%04X\",\"d\":[",
            label, e->kind, (unsigned long long)e->seq, e->frame, e->epoch, e->pc, e->func,
            e->addr, e->value, e->stage, e->raw_manager, e->manager,
            e->object.active, e->object.type, e->object.state, e->object.word08,
            e->object.map, e->object.x, e->object.y, e->object.vx, e->object.vy,
            e->object.cursor, e->object.callback, e->object.link, e->sr);
    for (unsigned i = 0; i < 8; i++) fprintf(f, "%s\"%08X\"", i ? "," : "", e->d[i]);
    fprintf(f, "],\"a\":[");
    for (unsigned i = 0; i < 8; i++) fprintf(f, "%s\"%08X\"", i ? "," : "", e->a[i]);
    fprintf(f, "]}\n");
}

static void rdb_boss_write_sat(FILE *f, const char *label,
                              const RdbBossSatEvent *e)
{
    fprintf(f, "{\"kind\":\"%s\",\"seq\":%llu,\"frame\":%u,\"epoch\":%u,\"pc\":\"%06X\",\"func\":\"%06X\","
               "\"vdp_seq\":%u,\"src\":\"%06X\",\"dst\":\"%04X\",\"len_words\":%u,\"bytes\":%u,"
               "\"code\":\"%02X\",\"reg5\":\"%02X\",\"reg11\":\"%02X\",\"reg13\":\"%02X\","
               "\"stage\":%u,\"manager_raw\":\"%08X\",\"manager\":\"%06X\",\"state\":\"%04X\",\"staging_valid\":%u,"
               "\"map\":\"%04X\",\"cursor\":\"%04X\",\"staging_hex\":\"",
            label, (unsigned long long)e->seq, e->frame, e->epoch, e->pc, e->func,
            e->vdp_seq, e->src, e->dst, e->len_words, e->byte_count,
            e->code, e->reg5, e->reg11, e->reg13, e->stage,
            e->raw_manager, e->manager, e->object.state, e->staging_valid,
            e->object.map, e->object.cursor);
    for (uint32_t i = 0; i < e->byte_count; i++) fprintf(f, "%02X", e->staging[i]);
    fprintf(f, "\",\"sat_hex\":\"");
    for (uint32_t i = 0; i < e->byte_count; i++) fprintf(f, "%02X", e->sat[i]);
    fprintf(f, "\"}\n");
}

static void rdb_boss_diag_dump_once(void)
{
    if (!g_rdb_boss_diag_enabled || s_boss_diag.dumped) return;
    s_boss_diag.dumped = 1;
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
    snprintf(path, sizeof(path), "R2-boss-trace-%04d%02d%02d-%02d%02d%02d-%d.jsonl",
             tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday,
             tmv.tm_hour, tmv.tm_min, tmv.tm_sec, pid);
    FILE *f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "[R2-BOSS] failed to write %s\n", path); return; }
    fprintf(f, "{\"kind\":\"header\",\"schema\":2,\"env\":\"GENESIS_R2_DIAG=1\","
               "\"event_capacity\":%u,\"first_write_capacity\":%u,\"sat_ring_capacity\":%u,"
               "\"first_sat_capacity\":%u,\"sat_max_bytes\":%u}\n",
            RDB_BOSS_EVENT_CAP, RDB_BOSS_FIRST_WRITE_CAP,
            RDB_BOSS_SAT_RING_CAP, RDB_BOSS_FIRST_SAT_CAP, RDB_BOSS_SAT_BYTES);
    fprintf(f, "{\"kind\":\"focus_header\",\"event_capacity\":%u,\"first_capacity\":%u,\"sat_capacity\":%u,\"stage_capacity\":%u}\n", RDB_BOSS_FOCUS_CAP, RDB_BOSS_FOCUS_FIRST_CAP, RDB_BOSS_FOCUS_SAT_CAP, RDB_BOSS_FOCUS_STAGE_CAP);
    for (uint32_t i = 0; i < s_boss_diag.first_write_count; i++)
        rdb_boss_write_event(f, "first_write", &s_boss_diag.first_writes[i]);
    uint32_t event_start = s_boss_diag.event_count < RDB_BOSS_EVENT_CAP
                         ? 0 : s_boss_diag.event_write % RDB_BOSS_EVENT_CAP;
    for (uint32_t i = 0; i < s_boss_diag.event_count; i++)
        rdb_boss_write_event(f, "event", &s_boss_diag.events[(event_start + i) % RDB_BOSS_EVENT_CAP]);
    for (uint32_t i = 0; i < s_boss_diag.focus_first_count; i++)
        r2f_write_json(f, "focus_first", &s_boss_diag.focus_first[i]);
    uint32_t focus_start = s_boss_diag.focus_count < RDB_BOSS_FOCUS_CAP ? 0 : s_boss_diag.focus_write % RDB_BOSS_FOCUS_CAP;
    for (uint32_t i = 0; i < s_boss_diag.focus_count; i++)
        r2f_write_json(f, "focus_event", &s_boss_diag.focus_events[(focus_start + i) % RDB_BOSS_FOCUS_CAP]);
    for (uint32_t i = 0; i < s_boss_diag.focus_stage_count; i++)
        r2f_write_json(f, "focus_stage_first", &s_boss_diag.focus_stage_events[i]);
    for (uint32_t i = 0; i < s_boss_diag.focus_sat_count; i++)
        rdb_boss_write_sat(f, "focus_sat", &s_boss_diag.focus_sat[i]);
    for (uint32_t i = 0; i < s_boss_diag.first_sat_count; i++)
        rdb_boss_write_sat(f, "first_sat", &s_boss_diag.first_sat[i]);
    uint32_t sat_start = s_boss_diag.sat_count < RDB_BOSS_SAT_RING_CAP
                       ? 0 : s_boss_diag.sat_write % RDB_BOSS_SAT_RING_CAP;
    for (uint32_t i = 0; i < s_boss_diag.sat_count; i++)
        rdb_boss_write_sat(f, "sat", &s_boss_diag.sat_events[(sat_start + i) % RDB_BOSS_SAT_RING_CAP]);
    fprintf(f, "{\"kind\":\"summary\",\"event_total\":%llu,\"event_retained\":%u,\"event_overwritten\":%llu,"
               "\"write_total\":%llu,\"first_writes_retained\":%u,\"first_write_overflow\":%llu,"
               "\"probe_total\":%llu,\"probe_non_r2\":%llu,\"probe_invalid_manager\":%llu,\"probe_recorded\":%llu,"
               "\"sat_dma_stage\":%llu,\"sat_dma_not_active_sat\":%llu,\"sat_dma_no_manager\":%llu,"
               "\"sat_total\":%llu,\"sat_retained\":%u,\"sat_overwritten\":%llu,"
               "\"first_sat_retained\":%u,\"first_sat_overflow\":%llu}\n",
            (unsigned long long)s_boss_diag.event_total, s_boss_diag.event_count,
            (unsigned long long)s_boss_diag.event_overwritten,
            (unsigned long long)s_boss_diag.write_total, s_boss_diag.first_write_count,
            (unsigned long long)s_boss_diag.first_write_overflow,
            (unsigned long long)s_boss_diag.probe_total,
            (unsigned long long)s_boss_diag.probe_non_r2,
            (unsigned long long)s_boss_diag.probe_invalid_manager,
            (unsigned long long)s_boss_diag.probe_recorded,
            (unsigned long long)s_boss_diag.sat_dma_stage,
            (unsigned long long)s_boss_diag.sat_dma_not_active_sat,
            (unsigned long long)s_boss_diag.sat_dma_no_manager,
            (unsigned long long)s_boss_diag.sat_total, s_boss_diag.sat_count,
            (unsigned long long)s_boss_diag.sat_overwritten,
            s_boss_diag.first_sat_count, (unsigned long long)s_boss_diag.first_sat_overflow);
    fprintf(f, "{\"kind\":\"focus_summary\",\"total\":%llu,\"retained\":%u,\"overwritten\":%llu,\"first_retained\":%u,\"first_overflow\":%llu,\"stage_writes\":%llu,\"stage_retained\":%u,\"stage_overflow\":%llu,\"sat_retained\":%u,\"sat_overflow\":%llu,\"anim_probes\":%llu,\"anim_manager_matches\":%llu,\"anim_pool_manager_matches\":%llu,\"frame_regressions\":%llu,\"epoch\":%u,\"epoch_basis\":\"guest_frame_regression\",\"first_frame\":%u,\"last_frame\":%u,\"candidate_confirmed\":%u,\"candidate\":\"%06X\",\"manager\":\"%06X\"}\n",
        (unsigned long long)s_boss_diag.focus_total,s_boss_diag.focus_count,(unsigned long long)s_boss_diag.focus_overwritten,s_boss_diag.focus_first_count,(unsigned long long)s_boss_diag.focus_first_overflow,(unsigned long long)s_boss_diag.focus_stage_write_total,s_boss_diag.focus_stage_count,(unsigned long long)s_boss_diag.focus_stage_write_overflow,s_boss_diag.focus_sat_count,(unsigned long long)s_boss_diag.focus_sat_overflow,(unsigned long long)s_boss_diag.focus_anim_probe_total,(unsigned long long)s_boss_diag.focus_anim_manager_matches,(unsigned long long)s_boss_diag.focus_anim_pool_manager_matches,(unsigned long long)s_boss_diag.frame_regressions,s_boss_diag.timeline_epoch,s_boss_diag.first_frame,s_boss_diag.last_frame,s_boss_diag.focus_candidate_confirmed,s_boss_diag.focus_candidate,s_boss_diag.focus_manager);
    fclose(f);
    fprintf(stderr, "[R2-BOSS] wrote %s (events=%llu overwritten=%llu field-writes=%llu SAT-DMA=%llu)\n",
            path, (unsigned long long)s_boss_diag.event_total,
            (unsigned long long)s_boss_diag.event_overwritten,
            (unsigned long long)s_boss_diag.write_total,
            (unsigned long long)s_boss_diag.sat_total);
}

void rdb_boss_diag_shutdown(void)
{
    rdb_boss_diag_dump_once();
}

static void rdb_boss_diag_init(void)
{
    if (s_boss_diag.initialized) return;
    s_boss_diag.initialized = 1;
    const char *env = getenv("GENESIS_R2_DIAG");
    if (env && strcmp(env, "1") == 0) {
        g_rdb_boss_diag_enabled = 1;
        atexit(rdb_boss_diag_dump_once);
        fprintf(stderr, "[R2-BOSS] focused lifecycle trace enabled (legacy events=%u, focus events=%u, first focus=%u, stage writes=%u, focus SAT=%u)\n",
                RDB_BOSS_EVENT_CAP, RDB_BOSS_FOCUS_CAP,
                RDB_BOSS_FOCUS_FIRST_CAP, RDB_BOSS_FOCUS_STAGE_CAP,
                RDB_BOSS_FOCUS_SAT_CAP);
    }
}

/* Shared hook slot in clownmdemu-core/source/bus-main-m68k.c. It is
 * defined unconditionally there; null when nobody has installed a tap. */
extern void (*g_mem_write_trace_fn)(uint32_t byte_address, uint8_t value, uint32_t target_cycle);

/* ---- Ring + ranges ---- */

#define RDB_LOG_SIZE     (1u << 20)   /* 1,048,576 entries */
#define RDB_MAX_RANGES   8

uint32_t g_rdb_current_func = 0;

typedef struct {
    uint32_t frame;
    uint32_t vint;    /* Vint_runcount at $FFFFFE0C — state-sync key
                       * across native vs oracle. */
    uint32_t adr;
    uint32_t val;     /* byte writes zero-extend into low 8 */
    uint32_t func;
    uint32_t caller;
    uint8_t  width;   /* bus tap fires per byte → width is always 1 today */
} RdbEntry;

static struct {
    int      active;
    int      nranges;
    struct { uint32_t lo, hi; } ranges[RDB_MAX_RANGES];
    uint32_t write_idx;
    uint32_t count;
    uint32_t snap_start;
    uint32_t snap_count;
    int      snap_active;
    int      tap_installed;
    /* Previous callback, so --mem-write-log and rdb can coexist. */
    void (*prev_trace_fn)(uint32_t, uint8_t, uint32_t);
    RdbEntry log[RDB_LOG_SIZE];
} s_rdb = {0};

/* ---- Hot path ---- */

static int rdb_range_hit(uint32_t adr)
{
    if (s_rdb.nranges == 0) return 1;
    for (int i = 0; i < s_rdb.nranges; i++) {
        if (adr >= s_rdb.ranges[i].lo && adr <= s_rdb.ranges[i].hi) return 1;
    }
    return 0;
}

static void rdb_sound_write_trace(uint32_t adr, uint8_t value);

static void rdb_bus_tap(uint32_t byte_address, uint8_t value, uint32_t target_cycle)
{
    /* Forward to previously-installed tracer (e.g. --mem-write-log) first
     * so we don't starve other instrumentation while Tier 1 is armed. */
    if (s_rdb.prev_trace_fn) s_rdb.prev_trace_fn(byte_address, value, target_cycle);

    if (!s_rdb.active) return;
    uint32_t adr = byte_address & 0xFFFFFFu;
    rdb_sound_write_trace(adr, value);
    rdb_boss_diag_write(adr, value);
    if (g_rdb_r3_diag_enabled)
        rdb_r3_diag_write(adr, g_ram[adr & 0xFFFFu], value);
    if (!rdb_range_hit(adr)) return;

    uint32_t idx = s_rdb.write_idx % RDB_LOG_SIZE;
    uint32_t a7  = cmd_server_current_a7();

    s_rdb.log[idx].frame  = cmd_server_current_frame();
    s_rdb.log[idx].vint   = rdb_read_wram32(0xFE0C);
    s_rdb.log[idx].adr    = adr;
    s_rdb.log[idx].val    = value;
    s_rdb.log[idx].width  = 1;
    s_rdb.log[idx].func   = g_rdb_current_func;
    s_rdb.log[idx].caller = cmd_server_stack_read32(a7);

    s_rdb.write_idx++;
    if (s_rdb.count < RDB_LOG_SIZE) s_rdb.count++;
}

/* ---- Bus-tap (de)install ---- */

void rdb_install_bus_tap(void)
{
    if (s_rdb.tap_installed) return;
    s_rdb.prev_trace_fn = g_mem_write_trace_fn;
    g_mem_write_trace_fn = rdb_bus_tap;
    s_rdb.tap_installed = 1;
}

void rdb_uninstall_bus_tap(void)
{
    if (!s_rdb.tap_installed) return;
    /* Only restore if we're still the current callback; if someone else
     * installed on top of us, leave the chain alone. */
    if (g_mem_write_trace_fn == rdb_bus_tap)
        g_mem_write_trace_fn = s_rdb.prev_trace_fn;
    s_rdb.prev_trace_fn = NULL;
    s_rdb.tap_installed = 0;
}

/* ---- Control API ---- */

int rdb_add_range(uint32_t lo, uint32_t hi)
{
    if (s_rdb.nranges >= RDB_MAX_RANGES) return 0;
    if (hi < lo) { uint32_t t = lo; lo = hi; hi = t; }
    s_rdb.ranges[s_rdb.nranges].lo = lo & 0xFFFFFFu;
    s_rdb.ranges[s_rdb.nranges].hi = hi & 0xFFFFFFu;
    s_rdb.nranges++;
    s_rdb.active = 1;
    rdb_install_bus_tap();
    return 1;
}

void rdb_reset(void)
{
    s_rdb.active = 0;
    s_rdb.nranges = 0;
    s_rdb.write_idx = 0;
    s_rdb.count = 0;
    s_rdb.snap_start = 0;
    s_rdb.snap_count = 0;
    s_rdb.snap_active = 0;
    rdb_uninstall_bus_tap();
}

void rdb_autostart(void)
{
    /* Default-on with a single WRAM-wide range ($FF0000-$FFFFFF). The
     * 1M-entry ring is enough for ~5 minutes of typical SMPS+gameplay
     * write traffic before eviction; anything older was already
     * uninteresting by the time a probe runs. Probes that want a
     * narrower view call rdb_reset+rdb_range as before — but the
     * default capture means probes work even on first connect with
     * no prior arming. */
    rdb_boss_diag_init();
    rdb_r3_diag_init();
    if (s_rdb.tap_installed) return;
    rdb_add_range(0xFF0000u, 0xFFFFFFu);
}

int rdb_range_count(void) { return s_rdb.nranges; }

int rdb_range_get(int i, uint32_t *lo_out, uint32_t *hi_out)
{
    if (i < 0 || i >= s_rdb.nranges) return 0;
    if (lo_out) *lo_out = s_rdb.ranges[i].lo;
    if (hi_out) *hi_out = s_rdb.ranges[i].hi;
    return 1;
}

void rdb_snapshot_begin(void)
{
    if (s_rdb.count < RDB_LOG_SIZE)
        s_rdb.snap_start = 0;
    else
        s_rdb.snap_start = s_rdb.write_idx % RDB_LOG_SIZE;
    s_rdb.snap_count  = s_rdb.count;
    s_rdb.snap_active = 1;
}

void rdb_snapshot_end(void)  { s_rdb.snap_active = 0; }

uint32_t rdb_snapshot_count(void)
{
    return s_rdb.snap_active ? s_rdb.snap_count : 0;
}

int rdb_format_entry(uint32_t i, char *buf, size_t buflen)
{
    if (!s_rdb.snap_active || i >= s_rdb.snap_count) return -1;
    uint32_t idx = (s_rdb.snap_start + i) % RDB_LOG_SIZE;
    const RdbEntry *e = &s_rdb.log[idx];
    int n = snprintf(buf, buflen,
        "{\"f\":%u,\"vint\":%u,\"adr\":\"0x%06X\",\"val\":\"0x%02X\",\"w\":%u,"
         "\"func\":\"0x%06X\",\"caller\":\"0x%06X\"}",
        (unsigned)e->frame,
        (unsigned)e->vint,
        (unsigned)e->adr,
        (unsigned)(e->val & 0xFFu),
        (unsigned)e->width,
        (unsigned)(e->func   & 0xFFFFFFu),
        (unsigned)(e->caller & 0xFFFFFFu));
    return (n < 0 || (size_t)n >= buflen) ? -1 : n;
}

/* Keep only the latest sound-table dispatches. This small ring lets the
 * capture script pair the exact A5-relative read address with the existing
 * WRAM writer ring without printing from the game thread. */
#define RDB_SOUND_INDEX_SIZE 256u
typedef struct {
    uint32_t frame;
    uint32_t pc;
    uint32_t a5;
    uint32_t adr;
    uint32_t index_reg;
    uint32_t target;
} RdbSoundIndexEntry;

static struct {
    uint32_t write_idx;
    uint32_t count;
    RdbSoundIndexEntry log[RDB_SOUND_INDEX_SIZE];
} s_sound_index = {0};

/* Independent history for the sound driver's WRAM workspace. Snapshot only
 * writes to the actual A5-relative address when the first invalid dispatch
 * arrives. The snapshot is never overwritten by later valid dispatches. */
#define RDB_SOUND_WRITE_SIZE 4096u
#define RDB_SOUND_PRECEDING_SIZE 32u
typedef struct {
    uint32_t frame, adr, value, func, caller;
} RdbSoundWriteEntry;
static struct {
    uint32_t write_idx, count;
    RdbSoundWriteEntry log[RDB_SOUND_WRITE_SIZE];
} s_sound_writes = {0};
static struct {
    int present;
    RdbSoundIndexEntry event;
    uint32_t count;
    RdbSoundWriteEntry writes[RDB_SOUND_PRECEDING_SIZE];
} s_sound_first_fault = {0};

static void rdb_sound_write_trace(uint32_t adr, uint8_t value)
{
    if (adr < 0xFFF800u || adr > 0xFFFAFFu) return;
    RdbSoundWriteEntry *e =
        &s_sound_writes.log[s_sound_writes.write_idx % RDB_SOUND_WRITE_SIZE];
    e->frame = cmd_server_current_frame();
    e->adr = adr;
    e->value = value;
    e->func = g_rdb_current_func;
    e->caller = cmd_server_stack_read32(cmd_server_current_a7());
    s_sound_writes.write_idx++;
    if (s_sound_writes.count < RDB_SOUND_WRITE_SIZE) s_sound_writes.count++;
}

void rdb_sound_index_trace(uint32_t pc, uint32_t a5, uint32_t index_reg,
                           uint32_t target)
{
    uint32_t idx = s_sound_index.write_idx % RDB_SOUND_INDEX_SIZE;
    RdbSoundIndexEntry *e = &s_sound_index.log[idx];
    e->frame = cmd_server_current_frame();
    e->pc = pc & 0xFFFFFFu;
    e->a5 = a5;
    e->adr = (a5 + 0x1Fu) & 0xFFFFFFu;
    e->index_reg = index_reg;
    e->target = target;
    s_sound_index.write_idx++;
    if (s_sound_index.count < RDB_SOUND_INDEX_SIZE)
        s_sound_index.count++;
    /* Each ROM table has exactly four two-byte executable entries. The
     * complete word matters: upper-byte contamination is invalid too. */
    uint32_t offset = index_reg & 0xFFFFu;
    if (!s_sound_first_fault.present && (offset > 6u || (offset & 1u))) {
        s_sound_first_fault.present = 1;
        s_sound_first_fault.event = *e;
        for (uint32_t n = 0; n < s_sound_writes.count &&
             s_sound_first_fault.count < RDB_SOUND_PRECEDING_SIZE; n++) {
            uint32_t i = (s_sound_writes.write_idx - 1u - n) % RDB_SOUND_WRITE_SIZE;
            if (s_sound_writes.log[i].adr == e->adr)
                s_sound_first_fault.writes[s_sound_first_fault.count++] = s_sound_writes.log[i];
        }
    }
}

uint32_t rdb_sound_index_count(void)
{
    return s_sound_index.count;
}

int rdb_sound_index_format(uint32_t i, char *buf, size_t buflen)
{
    if (i >= s_sound_index.count) return -1;
    uint32_t oldest = s_sound_index.write_idx - s_sound_index.count;
    const RdbSoundIndexEntry *e =
        &s_sound_index.log[(oldest + i) % RDB_SOUND_INDEX_SIZE];
    int n = snprintf(buf, buflen,
        "{\"f\":%u,\"pc\":\"0x%06X\",\"a5\":\"0x%08X\","
        "\"adr\":\"0x%06X\",\"value\":\"0x%02X\","
        "\"d0w\":\"0x%04X\",\"target\":\"0x%08X\"}",
        (unsigned)e->frame, (unsigned)e->pc, (unsigned)e->a5,
        (unsigned)e->adr, (unsigned)((e->index_reg >> 1) & 0xFFu),
        (unsigned)(e->index_reg & 0xFFFFu), (unsigned)e->target);
    return (n < 0 || (size_t)n >= buflen) ? -1 : n;
}

int rdb_sound_first_fault_format(char *buf, size_t buflen)
{
    if (!s_sound_first_fault.present) {
        int n = snprintf(buf, buflen, "{\"present\":false}");
        return (n < 0 || (size_t)n >= buflen) ? -1 : n;
    }
    const RdbSoundIndexEntry *e = &s_sound_first_fault.event;
    int n = snprintf(buf, buflen,
        "{\"present\":true,\"f\":%u,\"pc\":\"0x%06X\",\"a5\":\"0x%08X\","
        "\"adr\":\"0x%06X\",\"value\":\"0x%02X\",\"d0w\":\"0x%04X\","
        "\"target\":\"0x%08X\",\"writer_order\":\"newest_first\",\"preceding_writes\":[",
        e->frame, e->pc, e->a5, e->adr, (e->index_reg >> 1) & 0xFFu,
        e->index_reg & 0xFFFFu, e->target);
    if (n < 0 || (size_t)n >= buflen) return -1;
    size_t pos = (size_t)n;
    for (uint32_t i = 0; i < s_sound_first_fault.count; i++) {
        const RdbSoundWriteEntry *w = &s_sound_first_fault.writes[i];
        n = snprintf(buf + pos, buflen - pos,
            "%s{\"f\":%u,\"adr\":\"0x%06X\",\"val\":\"0x%02X\","
            "\"func\":\"0x%06X\",\"caller\":\"0x%06X\"}",
            i ? "," : "", w->frame, w->adr, w->value, w->func, w->caller);
        if (n < 0 || (size_t)n >= buflen - pos) return -1;
        pos += (size_t)n;
    }
    n = snprintf(buf + pos, buflen - pos, "]}");
    if (n < 0 || (size_t)n >= buflen - pos) return -1;
    return (int)(pos + (size_t)n);
}

/* =========================================================================
 * Tier 2: breakpoints + stepping
 *
 * Execution model: the game fiber runs on the same OS thread as the
 * main loop (Windows Fibers, cooperative). rdb_on_block_slow yields
 * to the main fiber via glue_yield_for_break(); the main loop drains
 * cmd_server until a TCP resume command sets g_rdb_resume_now and
 * SwitchToFiber(s_game_fiber)s back. We return from the yield on the
 * exact same C expression in the exact same function — block-level
 * resume with no state reconstruction needed.
 * ========================================================================= */

#define RDB_MAX_BREAKS 64

enum { STEP_NONE = 0, STEP_ONE_BLOCK, STEP_OVER };

int g_rdb_break_pending = 0;
int g_rdb_resume_now    = 0;

/* Diagnostic counters for smoke-testing the hook path. Visible via
 * rdb_break_list. If slow_count stays 0 while a break is armed, the
 * inline is either not inlined or the compiler elided it. */
uint64_t g_rdb_slow_count = 0;
uint64_t g_rdb_park_count = 0;

static struct {
    int      step_mode;
    /* For STEP_OVER: snapshot of the 68K call-stack depth at the moment
     * the user issued the command. We park again when depth <= snapshot
     * (caller re-entered). Depth is approximated as (initial_ssp - A7)/4
     * — works because 68K code stores 4-byte return addresses. */
    int32_t  step_over_depth;

    uint32_t breaks[RDB_MAX_BREAKS];
    int      break_count;

    int      parked;
    uint32_t parked_block;
    uint32_t last_block;
} s_tier2 = {0};

/* Approximate 68K call-stack depth for step-over. Sonic 1's initial SSP
 * is $FFFE00 (from ROM vectors); depth = (initial_ssp - A7) / 4, where
 * 4 is the size of each pushed return address. An off-by-one level in
 * interrupt context is acceptable — step-over's job is just to run
 * until we return to the calling frame, and spurious early-unpark is
 * user-recoverable via another step-over. */
static int32_t rdb_call_depth(void)
{
    const int32_t initial_ssp = 0xFFFE00;
    int32_t a7 = (int32_t)cmd_server_current_a7();
    return (initial_ssp - a7) / 4;
}

static void rdb_refresh_pending(void)
{
    g_rdb_break_pending = (s_tier2.break_count > 0
                        || s_tier2.step_mode != STEP_NONE);
}

void rdb_on_block_slow(uint32_t block_id)
{
    g_rdb_slow_count++;
    s_tier2.last_block = block_id;

    int park = 0;
    switch (s_tier2.step_mode) {
    case STEP_NONE:
        for (int i = 0; i < s_tier2.break_count; i++) {
            if (s_tier2.breaks[i] == block_id) { park = 1; break; }
        }
        break;
    case STEP_ONE_BLOCK:
        park = 1;
        s_tier2.step_mode = STEP_NONE;
        break;
    case STEP_OVER: {
        int32_t d = rdb_call_depth();
        if (d <= s_tier2.step_over_depth) {
            park = 1;
            s_tier2.step_mode = STEP_NONE;
        }
        break;
    }
    }
    rdb_refresh_pending();
    if (!park) return;

    g_rdb_park_count++;
    s_tier2.parked       = 1;
    s_tier2.parked_block = block_id;

    /* Yield to main fiber. Returns when main loop SwitchToFiber's back
     * — meaning a resume command came in. */
    glue_yield_for_break();

    s_tier2.parked = 0;
}

int  rdb_break_add(uint32_t block_id)
{
    if (s_tier2.break_count >= RDB_MAX_BREAKS) return 0;
    /* Dedupe — adding the same block twice is idempotent. */
    for (int i = 0; i < s_tier2.break_count; i++)
        if (s_tier2.breaks[i] == block_id) return 1;
    s_tier2.breaks[s_tier2.break_count++] = block_id & 0xFFFFFFu;
    rdb_refresh_pending();
    return 1;
}

void rdb_break_clear_all(void)
{
    s_tier2.break_count = 0;
    rdb_refresh_pending();
}

int rdb_break_count(void)            { return s_tier2.break_count; }
uint32_t rdb_break_get(int i)
{
    if (i < 0 || i >= s_tier2.break_count) return 0;
    return s_tier2.breaks[i];
}

void rdb_cmd_step_one(void)
{
    s_tier2.step_mode = STEP_ONE_BLOCK;
    rdb_refresh_pending();
    g_rdb_resume_now = 1;
}

void rdb_cmd_step_over(void)
{
    s_tier2.step_mode = STEP_OVER;
    /* Park when we return to a shallower (or equal) depth than *now*. */
    s_tier2.step_over_depth = rdb_call_depth();
    rdb_refresh_pending();
    g_rdb_resume_now = 1;
}

void rdb_cmd_continue(void)
{
    s_tier2.step_mode = STEP_NONE;
    rdb_refresh_pending();
    /* Tier-4 step_insn is one-shot, cleared in rdb_on_insn_slow when a
     * park fires. By the time continue is legal (we must be parked),
     * step_insn is already 0, so no extra clear needed here. */
    g_rdb_resume_now = 1;
}

int      rdb_is_parked   (void) { return s_tier2.parked; }
uint32_t rdb_parked_block(void) { return s_tier2.parked_block; }

/* =========================================================================
 * Tier 4: per-instruction step / break.
 * Reuses Tier 2's park (glue_yield_for_break + main-loop drain). The
 * only new mechanisms are (1) an insn-level break list keyed by PC,
 * (2) a step-one-insn flag, and (3) a fast-path gate g_rdb_insn_pending.
 * ========================================================================= */

#define RDB_INSN_MAX_BREAKS 128

int g_rdb_insn_pending = 0;

static struct {
    int      step_insn;      /* one-shot: next rdb_on_insn parks */
    uint32_t breaks[RDB_INSN_MAX_BREAKS];
    int      break_count;
    uint32_t parked_pc;
} s_tier4 = {0};

static void rdb_insn_refresh_pending(void)
{
    g_rdb_insn_pending = s_tier4.step_insn || s_tier4.break_count > 0;
}

void rdb_on_insn_slow(uint32_t pc)
{
    int park = 0;
    if (s_tier4.step_insn) {
        park = 1;
        s_tier4.step_insn = 0;
    } else {
        for (int i = 0; i < s_tier4.break_count; i++) {
            if (s_tier4.breaks[i] == pc) { park = 1; break; }
        }
    }
    rdb_insn_refresh_pending();
    if (!park) return;

    s_tier4.parked_pc = pc;
    s_tier2.parked       = 1;   /* reuse Tier 2's parked flag for main.c */
    s_tier2.parked_block = pc;  /* for rdb_get_state */
    glue_yield_for_break();
    s_tier2.parked       = 0;
}

int rdb_insn_break_add(uint32_t pc)
{
    if (s_tier4.break_count >= RDB_INSN_MAX_BREAKS) return 0;
    for (int i = 0; i < s_tier4.break_count; i++)
        if (s_tier4.breaks[i] == pc) return 1;  /* dedupe */
    s_tier4.breaks[s_tier4.break_count++] = pc & 0xFFFFFFu;
    rdb_insn_refresh_pending();
    return 1;
}

void rdb_insn_break_clear_all(void)
{
    s_tier4.break_count = 0;
    rdb_insn_refresh_pending();
}

int rdb_insn_break_count(void) { return s_tier4.break_count; }
uint32_t rdb_insn_break_get(int i)
{
    if (i < 0 || i >= s_tier4.break_count) return 0;
    return s_tier4.breaks[i];
}

void rdb_cmd_step_insn(void)
{
    s_tier4.step_insn = 1;
    rdb_insn_refresh_pending();
    g_rdb_resume_now = 1;
}

uint32_t rdb_parked_pc(void) { return s_tier4.parked_pc; }

/* =========================================================================
 * Stage-A: VBla-fire event ring + Iterate counter.
 *
 * Records each native-side VBla handler fire with the cycle accumulator
 * value at fire time, the native game-frame counter, and the wall-frame
 * counter from cmd_server. Distribution tells us whether native multi-
 * fires per wall frame.
 *
 * Oracle is 1:1 by architecture but we also expose an Iterate counter for
 * sanity. On oracle the fire-ring stays empty (glue.c's native-only code
 * path doesn't execute).
 * ========================================================================= */

#define RDB_FIRE_RING_SIZE  (1u << 16)   /* 65536 entries, ~1MB */

typedef struct {
    uint32_t wall;
    uint32_t acc;
    uint64_t game;
    uint8_t  reason;
} FireEntry;

static struct {
    uint32_t   write_idx;
    uint32_t   count;
    uint32_t   snap_start;
    uint32_t   snap_count;
    int        snap_active;
    FireEntry  log[RDB_FIRE_RING_SIZE];
} s_fires = {0};

static uint64_t s_iterate_count = 0;

void rdb_record_vbla_fire(uint32_t cycle_acc, uint64_t game_frame, int reason)
{
    uint32_t idx = s_fires.write_idx % RDB_FIRE_RING_SIZE;
    FireEntry *e = &s_fires.log[idx];
    e->wall   = cmd_server_current_frame();
    e->acc    = cycle_acc;
    e->game   = game_frame;
    e->reason = (uint8_t)reason;
    s_fires.write_idx++;
    if (s_fires.count < RDB_FIRE_RING_SIZE) s_fires.count++;
}

void rdb_record_iterate(void) { s_iterate_count++; }

void rdb_vbla_snapshot_begin(void)
{
    if (s_fires.count < RDB_FIRE_RING_SIZE)
        s_fires.snap_start = 0;
    else
        s_fires.snap_start = s_fires.write_idx % RDB_FIRE_RING_SIZE;
    s_fires.snap_count  = s_fires.count;
    s_fires.snap_active = 1;
}

void rdb_vbla_snapshot_end(void) { s_fires.snap_active = 0; }

uint32_t rdb_vbla_snapshot_count(void)
{
    return s_fires.snap_active ? s_fires.snap_count : 0;
}

uint64_t rdb_iterate_count(void) { return s_iterate_count; }

/* Stage C accessors. g_native_insn_count lives in runner/glue.c (always
 * defined — incremented by generated C). g_oracle_insn_count lives in
 * runner/oracle_trace.c (oracle-only build). On native, oracle_trace.c
 * is not linked; provide a weak fallback so the accessor still returns
 * 0 there. */
extern uint64_t g_native_insn_count;
static uint64_t g_oracle_insn_count = 0;

uint64_t rdb_native_insn_count(void) { return g_native_insn_count; }
uint64_t rdb_oracle_insn_count(void) { return g_oracle_insn_count; }

int rdb_vbla_format_entry(uint32_t i, char *buf, size_t buflen)
{
    if (!s_fires.snap_active || i >= s_fires.snap_count) return -1;
    uint32_t idx = (s_fires.snap_start + i) % RDB_FIRE_RING_SIZE;
    const FireEntry *e = &s_fires.log[idx];
    int n = snprintf(buf, buflen,
        "{\"wall\":%u,\"acc\":%u,\"game\":%llu,\"reason\":%u}",
        (unsigned)e->wall, (unsigned)e->acc,
        (unsigned long long)e->game, (unsigned)e->reason);
    return (n < 0 || (size_t)n >= buflen) ? -1 : n;
}

#endif /* SONIC_REVERSE_DEBUG */
