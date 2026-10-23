/* Tests the production trace implementation, without starting the game. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static uint32_t test_frame;
uint32_t g_rdb_current_func;
static uint32_t cmd_server_current_frame(void) { return test_frame; }
static uint32_t cmd_server_current_a7(void) { return 0xFFFFB8u; }
static uint32_t cmd_server_stack_read32(uint32_t adr) {
    if (adr != 0xFFFFB8u) abort();
    return 0x069BCAu;
}
#include "sound-trace-under-test.inc"

static void check(int condition, const char *message) {
    if (!condition) { fprintf(stderr, "%s\n", message); exit(1); }
}

int main(void) {
    char output[8192];
    for (uint32_t i = 0; i < 4; i++)
        rdb_sound_index_trace(0x069BB0u, 0xFFF870u, i * 2u, 0x069BB4u + i * 2u);
    check(!s_sound_first_fault.present, "Valid four-entry indices flagged invalid");
    test_frame = 100;
    g_rdb_current_func = 0x069800;
    rdb_sound_write_trace(0xFFF88Fu, 0);
    rdb_sound_write_trace(0xFFF8BFu, 2); /* Different channel, must not match. */
    test_frame = 101;
    g_rdb_current_func = 0x069976;
    rdb_sound_write_trace(0xFFF88Fu, 0xD2);
    test_frame = 102;
    rdb_sound_index_trace(0x069BB0u, 0xFFF870u, 0x1A4u, 0x069D58u);
    check(s_sound_first_fault.present && s_sound_first_fault.count == 2,
          "First invalid read did not preserve matching preceding writes");
    for (uint32_t i = 0; i < 1024; i++) {
        test_frame++;
        rdb_sound_write_trace(0xFFF88Fu, 0);
        rdb_sound_index_trace(0x069BCAu, 0xFFF870u, 0, 0x069BCEu);
    }
    rdb_sound_index_trace(0x069BCAu, 0xFFF870u, 0x1A4u, 0x069D72u);
    check(s_sound_first_fault.event.frame == 102 &&
          s_sound_first_fault.event.pc == 0x069BB0u,
          "Later reads overwrote the first fault");
    check(s_sound_first_fault.writes[0].value == 0xD2 &&
          s_sound_first_fault.writes[0].func == 0x069976,
          "Later writes overwrote pinned writer evidence");
    check(rdb_sound_index_count() == 256, "Dispatch ring did not stay bounded");
    check(rdb_sound_first_fault_format(output, sizeof output) > 0 &&
          strstr(output, "\"value\":\"0xD2\"") &&
          strstr(output, "\"writer_order\":\"newest_first\""),
          "Pinned fault JSON missing read value or write order");
    check(rdb_sound_first_fault_format(output, 8) == -1,
          "Undersized JSON buffer not rejected");
    memset(&s_sound_first_fault, 0, sizeof s_sound_first_fault);
    rdb_sound_index_trace(0x069BCAu, 0xFFF870u, 0x100u, 0x069CCEu);
    check(s_sound_first_fault.present, "Word contamination with low byte zero was missed");
    puts("PASS: bounded retention, writer matching, first fault preservation, word contamination, buffer bounds");
    return 0;
}
