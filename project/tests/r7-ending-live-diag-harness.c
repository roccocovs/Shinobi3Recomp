#include "r7_ending_diag.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void need(int condition, const char *message)
{
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", message);
        exit(1);
    }
}

static R7EndingDiagSnapshot sample(uint64_t frame)
{
    R7EndingDiagSnapshot s;
    memset(&s, 0, sizeof(s));
    s.wall_frame = frame;
    s.sound_frame = frame + 1000u;
    s.native_instructions = frame * 10u;
    s.chunk_yields = frame / 2u;
    s.pc = 0x010436u + (uint32_t)(frame & 0xFu) * 2u;
    s.cpu_pc = s.pc + 2u;
    s.sp = 0xFFFF00u;
    s.callback = 0x010436u;
    s.ending_state = 8;
    s.timer = (uint16_t)frame;
    s.audio_cycle = (uint32_t)(frame * 127u);
    s.audio_events = frame * 3u;
    s.audio_port_events[0] = frame;
    s.audio_port_events[1] = frame + 1u;
    s.audio_port_events[2] = frame + 2u;
    s.audio_port_events[3] = frame + 3u;
    s.audio_port_events[4] = frame + 4u;
    s.z80_busreq = 1;
    s.z80_reset_off = 1;
    s.z80_mailbox_1ffd = 0x80u;
    s.z80_mailbox_busy_seen = 1;
    for (unsigned i = 0; i < 8; i++) s.d[i] = 0xD0000000u + i;
    for (unsigned i = 0; i < 7; i++) s.a[i] = 0xA0000000u + i;
    return s;
}

int main(int argc, char **argv)
{
    need(argc == 3, "usage: harness <mode> <output-path>");
    const char *mode = argv[1];
    const char *path = argv[2];
    r7_ending_diag_init(path);

    if (strcmp(mode, "disabled") == 0) {
        need(!r7_ending_diag_is_enabled(), "disabled mode unexpectedly enabled recorder");
        R7EndingDiagSnapshot s = sample(4);
        s.callback = 0x001234u;
        r7_ending_diag_frame(&s);
        r7_ending_diag_shutdown();
        return 0;
    }
    need(r7_ending_diag_is_enabled(), "enabled mode did not enable recorder");

    if (strcmp(mode, "capacity") == 0) {
        for (uint64_t frame = 0; frame < 300u * 30u; frame += 30u) {
            R7EndingDiagSnapshot s = sample(frame);
            r7_ending_diag_frame(&s);
        }
        r7_ending_diag_shutdown();
        return 0;
    }

    R7EndingDiagSnapshot s = sample(1);
    s.callback = 0x000123u;
    R7EndingDiagSnapshot before = s;
    r7_ending_diag_frame(&s);
    need(memcmp(&s, &before, sizeof(s)) == 0,
         "inactive stage gate modified guest snapshot");

    s = sample(2);
    before = s;
    r7_ending_diag_frame(&s);
    need(memcmp(&s, &before, sizeof(s)) == 0,
         "ending activation modified guest snapshot");
    r7_ending_diag_ram_write(&s, 0xFF0034u, 2, 8, 0x000Cu);
    r7_ending_diag_dispatch_miss(&s, 0x01FBBCu);
    r7_ending_diag_dispatch_miss(&s, 0x01FBBCu);

    R7EndingDiagBusEvent events[R7_ENDING_DIAG_BUS_MAX + 16u];
    for (size_t i = 0; i < sizeof(events) / sizeof(events[0]); i++) {
        events[i].address = 0xFF0000u + (uint32_t)i;
        events[i].pc = 0x010000u + (uint32_t)(i * 2u);
        events[i].kind = (uint8_t)(i % 6u);
    }
    R7EndingDiagSnapshot frozen = sample(32);
    before = frozen;
    r7_ending_diag_watchdog(&frozen, "fixture watchdog", events,
                            sizeof(events) / sizeof(events[0]),
                            sizeof(events) / sizeof(events[0]));
    need(memcmp(&frozen, &before, sizeof(frozen)) == 0,
         "watchdog capture modified guest snapshot");
    r7_ending_diag_shutdown();
    return 0;
}
