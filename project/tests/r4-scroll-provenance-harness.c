#include "genesis_runtime.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <direct.h>
#include <process.h>
#define test_mkdir(path) _mkdir(path)
#define test_chdir(path) _chdir(path)
#define test_getpid() _getpid()
#else
#include <unistd.h>
#define test_mkdir(path) mkdir(path, 0700)
#define test_chdir(path) chdir(path)
#define test_getpid() getpid()
#endif

M68KState g_cpu;
uint8_t g_rom[0x400000];
uint8_t g_ram[0x10000];
uint64_t g_frame_count;
int g_split_sp_popped;
static int s_rte;
int *g_rte_pending_ptr = &s_rte;

void r4_scroll_trace_test_reset(void);
const char *r4_scroll_trace_test_path(void);

static int fail(const char *message)
{
    fprintf(stderr, "FAIL: %s\n", message);
    return 1;
}

static void put16(uint32_t address, uint16_t value)
{
    uint32_t o = address & 0xFFFFu;
    g_ram[o] = (uint8_t)(value >> 8);
    g_ram[(o + 1u) & 0xFFFFu] = (uint8_t)value;
}

static void setup_active(uint16_t state, uint16_t scroll)
{
    memset(g_ram, 0, sizeof(g_ram));
    memset(&g_cpu, 0, sizeof(g_cpu));
    g_frame_count = 0;
    g_split_sp_popped = 0;
    s_rte = 0;
    put16(0xFF4182u, 0x8000u);
    put16(0xFF4186u, state);
    put16(0x00FFF480u, scroll);
}

static int test_dual_phase_and_history(const char *root)
{
    char dir[512], trace[1024];
    snprintf(dir, sizeof(dir), "%s\\history", root);
    if (test_mkdir(dir) != 0 || test_chdir(dir) != 0) return fail("create history test directory");
    r4_scroll_trace_test_reset();
    setup_active(0x0024u, 0x0100u);
    for (unsigned i = 0; i < 350; ++i) {
        g_frame_count = i;
        r4_scroll_trace_frame_end();
    }

    g_frame_count = 350;
    r4_scroll_trace_memory_write(0xFF4186u, 2, 0x0024u, 0x0028u, 0x02E106u);
    put16(0xFF4186u, 0x0028u);
    const char *trace_name = r4_scroll_trace_test_path();
    if (!trace_name || !trace_name[0]) return fail("automatic state-$28 trigger did not create JSONL");
    snprintf(trace, sizeof(trace), "%s", trace_name);

    g_cpu.A[0] = 0x00FF4182u; g_cpu.A[7] = 0x00FFFB00u;
    g_cpu.D[0] = 0xFFFF7F00u;
    M68KState cpu_before = g_cpu;
    uint8_t ram_before[sizeof(g_ram)]; memcpy(ram_before, g_ram, sizeof(g_ram));
    uint64_t frame_before = g_frame_count;
    int rte_before = g_rte_pending, split_before = g_split_sp_popped;
    r4_scroll_trace_instruction(0x02EE38u, g_cpu.A[0]);
    r4_scroll_trace_instruction(0x02EF28u, g_cpu.A[0]);
    r4_scroll_trace_instruction(0x02EF36u, g_cpu.A[0]);
    r4_scroll_trace_continuation(0x02EE38u, 0x02E1A8u);
    r4_scroll_trace_vsram_write(0x02B84u, 0, 0x0100u, 0x037Fu, 0x10u, 0, 0);
    if (memcmp(&g_cpu, &cpu_before, sizeof(g_cpu)) ||
        memcmp(g_ram, ram_before, sizeof(g_ram)) || g_frame_count != frame_before ||
        g_rte_pending != rte_before || g_split_sp_popped != split_before)
        return fail("trace callbacks mutated guest state");

    g_frame_count = 351;
    r4_scroll_trace_memory_write(0x00FFF480u, 2, 0x0100u, 0xFF7Fu, 0x02EF36u);
    put16(0x00FFF480u, 0xFF7Fu);
    r4_scroll_trace_memory_write(0xFF4186u, 2, 0x0028u, 0x0024u, 0x02E200u);
    put16(0xFF4186u, 0x0024u);
    r4_scroll_trace_frame_end();

    g_frame_count = 500;
    put16(0x00FFF480u, 0x0100u);
    r4_scroll_trace_memory_write(0xFF4186u, 2, 0x0024u, 0x0038u, 0x02E600u);
    put16(0xFF4186u, 0x0038u);
    g_frame_count = 501;
    r4_scroll_trace_memory_write(0x00FFF480u, 2, 0x0100u, 0xFFD5u, 0x02EF36u);
    put16(0x00FFF480u, 0xFFD5u);
    r4_scroll_trace_memory_write(0xFF4186u, 2, 0x0038u, 0x003Cu, 0x02E6C8u);
    put16(0xFF4186u, 0x003Cu);
    for (unsigned i = 0; i < 31; ++i) {
        g_frame_count = 502u + i;
        r4_scroll_trace_frame_end();
    }

    FILE *f = fopen(trace, "rb");
    if (!f) return fail("open emitted trace");
    char line[1024];
    uint64_t seq = 0, min_frame = UINT64_MAX, max_frame = 0;
    unsigned pre_frames = 0, saw28 = 0, saw38 = 0, saw_restore1 = 0, saw_restore2 = 0;
    unsigned char seen_pre[350] = {0};
    int cap_ok = 0;
    while (fgets(line, sizeof(line), f)) {
        char *sp = strstr(line, "\"seq\":");
        if (sp) {
            uint64_t next = strtoull(sp + 6, NULL, 10);
            if (next <= seq) { fclose(f); return fail("event sequence is not strictly increasing"); }
            seq = next;
        }
        if (strstr(line, "\"event\":\"frame\"")) {
            char *fp = strstr(line, "\"guest_frame\":");
            if (fp) {
                uint64_t frame = strtoull(fp + 14, NULL, 10);
                if (frame < 350 && frame >= 50) {
                    seen_pre[frame] = 1;
                    if (frame < min_frame) min_frame = frame;
                    if (frame > max_frame) max_frame = frame;
                }
            }
        }
        if (strstr(line, "\"event\":\"manager_state\"") && strstr(line, "\"state\":\"0028\"")) saw28 = 1;
        if (strstr(line, "\"event\":\"manager_state\"") && strstr(line, "\"state\":\"0038\"")) saw38 = 1;
        if (strstr(line, "\"event\":\"boss_scroll_calculation\"")) saw_restore1 = 1;
        if (strstr(line, "\"event\":\"vsram_write\"")) saw_restore2 = 1;
        if (strstr(line, "\"event\":\"capture_end\"")) cap_ok = 1;
    }
    fclose(f);
    for (unsigned i = 50; i < 350; ++i) pre_frames += seen_pre[i] != 0;
    if (pre_frames != 300 || min_frame != 50 || max_frame != 349)
        return fail("rolling lead-in does not retain exactly the latest 300 frames");
    if (!saw28 || !saw38 || !saw_restore1 || !saw_restore2 || !cap_ok)
        return fail("trace did not capture both missing/restored phase routes");
    return 0;
}

static int test_hard_cap(const char *root)
{
    char dir[512], trace[1024];
    snprintf(dir, sizeof(dir), "%s\\cap", root);
    if (test_mkdir(dir) != 0 || test_chdir(dir) != 0) return fail("create cap test directory");
    r4_scroll_trace_test_reset();
    setup_active(0x0028u, 0x0100u);
    r4_scroll_trace_frame_end();
    const char *trace_name = r4_scroll_trace_test_path();
    if (!trace_name || !trace_name[0]) return fail("cap test trigger did not create JSONL");
    snprintf(trace, sizeof(trace), "%s", trace_name);
    for (unsigned i = 0; i < 50000; ++i)
        r4_scroll_trace_memory_write(0x00FFF480u, 2, (uint16_t)i,
                                     (uint16_t)(i + 1u), 0x0023D0u);
    FILE *f = fopen(trace, "rb");
    if (!f) return fail("open cap test trace");
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return fail("seek cap test trace"); }
    long size = ftell(f);
    rewind(f);
    char line[128]; int saw_cap = 0;
    while (fgets(line, sizeof(line), f)) if (strstr(line, "hard_cap_reached")) saw_cap = 1;
    fclose(f);
    if (size < 0 || (unsigned long)size > 4u * 1024u * 1024u || !saw_cap)
        return fail("hard 4 MiB limit was not enforced");
    return 0;
}

int main(void)
{
    char root[256];
    snprintf(root, sizeof(root), "r4-scroll-test-%d", (int)test_getpid());
    if (test_mkdir(root) != 0 || test_dual_phase_and_history(root)) return 1;
    if (test_chdir("..") != 0 || test_chdir("..") != 0 || test_hard_cap(root)) return 1;
    puts("PASS: dual Round-4 phases, 300-frame lead-in, automatic trigger, guest-state preservation, and 4 MiB cap");
    return 0;
}
