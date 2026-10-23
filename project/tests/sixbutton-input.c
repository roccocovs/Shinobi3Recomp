#include "input_script.h"
#include "genesis_runtime.h"
#include "crash_report.h"

#include <stdio.h>
#include <stdlib.h>

M68KState g_cpu;

void crash_report_dump_persistent(const char *reason, const M68KState *cpu,
                                  uint32_t address, int is_write,
                                  uint64_t frame)
{
    (void)cpu;
    (void)address;
    (void)is_write;
    (void)frame;
    fprintf(stderr, "%s\n", reason);
    exit(1);
}

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

int main(int argc, char **argv)
{
    CHECK(argc == 2 && input_script_load(argv[1]));

    input_script_tick(0, NULL, NULL, NULL, NULL, NULL);
    CHECK(input_script_player_mask(0) == 0x300u); /* X + Y */
    CHECK(input_script_player_mask(1) == 0x400u); /* Z */

    input_script_tick(1, NULL, NULL, NULL, NULL, NULL);
    CHECK(input_script_player_mask(0) == 0x200u); /* X released, Y held */
    CHECK(input_script_player_mask(1) == 0x400u);

    input_script_tick(2, NULL, NULL, NULL, NULL, NULL);
    CHECK(input_script_player_mask(0) == 0u); /* timed Y release */
    CHECK(input_script_player_mask(1) == 0u); /* explicit Z release */

    input_script_tick(3, NULL, NULL, NULL, NULL, NULL);
    CHECK(input_script_player_mask(1) == 0u); /* timed Z release */
    CHECK(!input_script_player_mask(-1));
    CHECK(!input_script_player_mask(4));

    puts("Six-button scripted inputs preserve X/Y/Z extension bits and timers.");
    return 0;
}
