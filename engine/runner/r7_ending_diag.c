#include "r7_ending_diag.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define R7_ENDING_SAMPLE_PERIOD 30u
#define R7_ENDING_MISS_UNIQUE 64u

typedef struct R7EndingDiagRecord {
    const char *kind;
    R7EndingDiagSnapshot snapshot;
    uint32_t address, old_value, new_value;
    unsigned width;
    const char *reason;
    R7EndingDiagBusEvent bus[R7_ENDING_DIAG_BUS_MAX];
    size_t bus_count;
    uint64_t bus_total;
} R7EndingDiagRecord;

static int s_enabled;
static int s_initialized;
static int s_active;
static int s_finished;
static int s_reported_error;
static char s_path[1024];
static R7EndingDiagRecord s_records[R7_ENDING_DIAG_RECORD_CAP];
static size_t s_write;
static size_t s_count;
static uint64_t s_last_sample_frame;
static uint32_t s_miss_addresses[R7_ENDING_MISS_UNIQUE];
static size_t s_miss_count;

static void write_record(FILE *f, const R7EndingDiagRecord *r)
{
    const R7EndingDiagSnapshot *s = &r->snapshot;
    fprintf(f,
        "{\"kind\":\"%s\",\"wall_frame\":%llu,\"sound_frame\":%llu,\"native_instructions\":%llu,"
        "\"chunk_yields\":%llu,\"pc\":\"%06X\",\"cpu_pc\":\"%06X\","
        "\"function\":\"%06X\",\"sr\":\"%04X\",\"sp\":\"%08X\","
        "\"returns\":[\"%06X\",\"%06X\",\"%06X\",\"%06X\"],"
        "\"callback\":\"%06X\",\"stage\":\"%02X\",\"act\":\"%02X\","
        "\"ending_state\":\"%04X\",\"previous_state\":\"%04X\","
        "\"ending_flags\":\"%04X\",\"timer\":\"%04X\",\"script_done\":\"%04X\","
        "\"object_pointer\":\"%08X\",\"object_state\":\"%04X\","
        "\"object_tick\":\"%04X\",\"object_frame\":\"%04X\","
        "\"object_xy\":[\"%04X\",\"%04X\"],\"object_vxy\":[\"%04X\",\"%04X\"],"
        "\"master_cycle\":%u,\"audio_cycle\":%u,\"z80_pc\":\"%04X\","
        "\"z80_cycle_debt\":%u,\"z80_iff1\":%u,\"z80_irq_pending\":%u,"
        "\"z80_busreq\":%u,\"z80_reset_off\":%u,\"z80_mailbox_1ffd\":\"%02X\","
        "\"z80_mailbox_busy_seen\":%u,"
        "\"vint_count\":%u,\"vdp_scanline\":%u,\"vdp_status\":[%u,%u],"
        "\"vdp_registers\":[\"%02X\",\"%02X\",\"%02X\"],"
        "\"audio_queue\":%u,\"audio_events\":%llu,\"audio_port_events\":[%llu,%llu,%llu,%llu,%llu]",
        r->kind,
        (unsigned long long)s->wall_frame,
        (unsigned long long)s->sound_frame,
        (unsigned long long)s->native_instructions,
        (unsigned long long)s->chunk_yields,
        s->pc & 0xFFFFFFu, s->cpu_pc & 0xFFFFFFu,
        s->current_function & 0xFFFFFFu, s->sr, s->sp,
        s->returns[0] & 0xFFFFFFu, s->returns[1] & 0xFFFFFFu,
        s->returns[2] & 0xFFFFFFu, s->returns[3] & 0xFFFFFFu,
        s->callback & 0xFFFFFFu, s->stage & 0xFFu, s->act & 0xFFu,
        s->ending_state, s->previous_state, s->ending_flags, s->timer,
        s->script_done, s->object_pointer, s->object_state, s->object_tick,
        s->object_frame, s->object_x, s->object_y, s->object_vx, s->object_vy,
        s->master_cycle, s->audio_cycle, s->z80_pc, s->z80_cycle_debt,
        s->z80_iff1, s->z80_irq_pending, s->z80_busreq, s->z80_reset_off,
        s->z80_mailbox_1ffd, s->z80_mailbox_busy_seen,
        s->vint_count, s->vdp_scanline,
        s->vdp_in_vblank, s->vdp_in_hblank, s->vdp_reg1, s->vdp_reg10,
        s->vdp_reg11, s->audio_queue, (unsigned long long)s->audio_events,
        (unsigned long long)s->audio_port_events[0],
        (unsigned long long)s->audio_port_events[1],
        (unsigned long long)s->audio_port_events[2],
        (unsigned long long)s->audio_port_events[3],
        (unsigned long long)s->audio_port_events[4]);
    fprintf(f, ",\"d\":[");
    for (size_t i = 0; i < 8; i++)
        fprintf(f, "%s\"%08X\"", i ? "," : "", s->d[i]);
    fprintf(f, "],\"a\":[");
    for (size_t i = 0; i < 7; i++)
        fprintf(f, "%s\"%08X\"", i ? "," : "", s->a[i]);
    fputc(']', f);
    if (r->address || r->width)
        fprintf(f, ",\"address\":\"%06X\",\"width\":%u,\"old\":\"%08X\",\"value\":\"%08X\"",
                r->address & 0xFFFFFFu, r->width, r->old_value, r->new_value);
    if (r->reason)
        fprintf(f, ",\"reason\":\"%s\"", r->reason);
    if (r->bus_count) {
        fprintf(f, ",\"bus_total\":%llu,\"bus_tail\":[",
                (unsigned long long)r->bus_total);
        for (size_t i = 0; i < r->bus_count; i++) {
            if (i) fputc(',', f);
            fprintf(f, "{\"address\":\"%06X\",\"pc\":\"%06X\",\"kind\":%u}",
                    r->bus[i].address & 0xFFFFFFu,
                    r->bus[i].pc & 0xFFFFFFu, r->bus[i].kind);
        }
        fputc(']', f);
    }
    fputs("}\n", f);
}

static void flush_records(void)
{
    if (!s_enabled || !s_initialized || !s_path[0])
        return;
    FILE *f = fopen(s_path, "wb");
    if (!f) {
        if (!s_reported_error) {
            fprintf(stderr, "[R7-END-DIAG] cannot write %s\n", s_path);
            s_reported_error = 1;
        }
        return;
    }
    fprintf(f, "{\"kind\":\"header\",\"schema\":1,"
               "\"trigger\":\"ending callback $010436\","
               "\"frame_sample_period\":%u,\"record_capacity\":%u,\"bus_tail_capacity\":%u}\n",
            R7_ENDING_SAMPLE_PERIOD, R7_ENDING_DIAG_RECORD_CAP,
            R7_ENDING_DIAG_BUS_MAX);
    size_t oldest = (s_write + R7_ENDING_DIAG_RECORD_CAP - s_count) % R7_ENDING_DIAG_RECORD_CAP;
    for (size_t i = 0; i < s_count; i++)
        write_record(f, &s_records[(oldest + i) % R7_ENDING_DIAG_RECORD_CAP]);
    fclose(f);
}

static void push_record(const char *kind, const R7EndingDiagSnapshot *snapshot,
                        uint32_t address, unsigned width,
                        uint32_t old_value, uint32_t new_value,
                        const char *reason,
                        const R7EndingDiagBusEvent *bus_events,
                        size_t bus_count, uint64_t bus_total)
{
    if (!s_enabled || !s_active || !snapshot)
        return;
    R7EndingDiagRecord *r = &s_records[s_write];
    memset(r, 0, sizeof(*r));
    r->kind = kind;
    r->snapshot = *snapshot;
    r->address = address;
    r->width = width;
    r->old_value = old_value;
    r->new_value = new_value;
    r->reason = reason;
    r->bus_total = bus_total;
    if (bus_count > R7_ENDING_DIAG_BUS_MAX) {
        if (bus_events)
            bus_events += bus_count - R7_ENDING_DIAG_BUS_MAX;
        bus_count = R7_ENDING_DIAG_BUS_MAX;
    }
    if (bus_events && bus_count) {
        memcpy(r->bus, bus_events, bus_count * sizeof(*bus_events));
        r->bus_count = bus_count;
    }
    s_write = (s_write + 1u) % R7_ENDING_DIAG_RECORD_CAP;
    if (s_count < R7_ENDING_DIAG_RECORD_CAP)
        s_count++;
}

void r7_ending_diag_init(const char *default_path)
{
    const char *env = getenv("GENESIS_R7_ENDING_DIAG");
    s_enabled = env && env[0] && strcmp(env, "0") != 0;
    if (!s_enabled)
        return;
    const char *path = getenv("GENESIS_R7_ENDING_DIAG_PATH");
    if (!path || !path[0])
        path = default_path;
    if (path && path[0])
        snprintf(s_path, sizeof(s_path), "%s", path);
    s_initialized = 1;
    s_active = 0;
    s_finished = 0;
    s_write = s_count = 0;
    s_last_sample_frame = 0;
    s_miss_count = 0;
    /* Clear a stale file at startup, before waiting for the ending trigger. */
    flush_records();
    fprintf(stderr, "[R7-END-DIAG] enabled; waiting for $FF002A=$010436; output=%s\n",
            s_path[0] ? s_path : "(unavailable)");
}

int r7_ending_diag_is_enabled(void)
{
    return s_enabled;
}

void r7_ending_diag_ram_write(const R7EndingDiagSnapshot *snapshot,
                              uint32_t address, unsigned width,
                              uint32_t old_value, uint32_t new_value)
{
    if (!s_enabled || !snapshot || s_finished)
        return;
    address &= 0xFFFFFFu;
    if (!s_active && snapshot->callback == 0x010436u) {
        s_active = 1;
        s_last_sample_frame = snapshot->wall_frame;
        push_record("ending_start", snapshot, address, width,
                    old_value, new_value, NULL, NULL, 0, 0);
        flush_records();
    } else if (!s_active && address == 0xFF002Au &&
               (new_value & 0xFFFFFFu) == 0x010436u) {
        s_active = 1;
        s_last_sample_frame = snapshot->wall_frame;
        push_record("ending_start", snapshot, address, width,
                    old_value, new_value, NULL, NULL, 0, 0);
        flush_records();
    }
    if (!s_active)
        return;

    if (address == 0xFF002Au && old_value != new_value) {
        push_record((new_value & 0xFFFFFFu) == 0x000069A8u
                        ? "ending_callback_exit" : "callback_change",
                    snapshot, address, width, old_value, new_value,
                    NULL, NULL, 0, 0);
        flush_records();
        if ((new_value & 0xFFFFFFu) == 0x000069A8u)
            s_finished = 1;
        return;
    }

    int interesting = 0;
    if (address == 0xFF0032u || address == 0xFF0034u ||
        address == 0xFF0036u || address == 0xFF00F8u ||
        address == 0xFF00FAu)
        interesting = old_value != new_value;
    else if (address == 0xFF00F6u)
        interesting = old_value == 0 || new_value == 0;
    if (interesting) {
        push_record("ram_transition", snapshot, address, width,
                    old_value, new_value, NULL, NULL, 0, 0);
        flush_records();
    }
}

void r7_ending_diag_dispatch_miss(const R7EndingDiagSnapshot *snapshot,
                                  uint32_t target)
{
    target &= 0xFFFFFFu;
    for (size_t i = 0; i < s_miss_count; i++)
        if (s_miss_addresses[i] == target)
            return;
    if (s_miss_count >= R7_ENDING_MISS_UNIQUE)
        return;
    s_miss_addresses[s_miss_count++] = target;
    push_record("dispatch_miss", snapshot, target, 0, 0, 0,
                NULL, NULL, 0, 0);
}

void r7_ending_diag_frame(const R7EndingDiagSnapshot *snapshot)
{
    if (!s_enabled || !snapshot || s_finished)
        return;
    if (!s_active && snapshot->callback == 0x010436u) {
        s_active = 1;
        s_last_sample_frame = snapshot->wall_frame;
        push_record("ending_start", snapshot, 0, 0, 0, 0, NULL, NULL, 0, 0);
        flush_records();
    }
    if (!s_active)
        return;
    if (snapshot->callback == 0x000069A8u) {
        push_record("ending_callback_exit", snapshot, 0, 0, 0, 0, NULL, NULL, 0, 0);
        flush_records();
        s_finished = 1;
        return;
    }
    if (snapshot->wall_frame - s_last_sample_frame >= R7_ENDING_SAMPLE_PERIOD) {
        push_record("frame", snapshot, 0, 0, 0, 0, NULL, NULL, 0, 0);
        s_last_sample_frame = snapshot->wall_frame;
        flush_records();
    }
}

void r7_ending_diag_watchdog(const R7EndingDiagSnapshot *snapshot,
                             const char *reason,
                             const R7EndingDiagBusEvent *bus_events,
                             size_t bus_count, uint64_t bus_total)
{
    if (!s_enabled || !snapshot)
        return;
    if (!s_active && snapshot->callback == 0x010436u) {
        s_active = 1;
        push_record("ending_start", snapshot, 0, 0, 0, 0, NULL, NULL, 0, 0);
    }
    push_record("watchdog", snapshot, 0, 0, 0, 0,
                reason ? reason : "runtime watchdog",
                bus_events, bus_count, bus_total);
    flush_records();
}

void r7_ending_diag_shutdown(void)
{
    if (s_enabled)
        flush_records();
}
