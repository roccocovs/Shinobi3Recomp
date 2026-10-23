#include "state_store.h"
#include "state_container.h"
#include "state_slots.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

static int failures;
#define CHECK(expr, text) do { if (!(expr)) { \
    fprintf(stderr, "FAIL: %s (line %d)\n", text, __LINE__); ++failures; \
} } while (0)

static int make_dir(const char *path)
{
#ifdef _WIN32
    if (CreateDirectoryA(path, NULL)) return 1;
    return GetLastError() == ERROR_ALREADY_EXISTS;
#else
    if (mkdir(path, 0700) == 0) return 1;
    return errno == EEXIST;
#endif
}

static int make_temp_root(char *out, size_t cap)
{
#ifdef _WIN32
    char tmp[MAX_PATH];
    if (!GetTempPathA(sizeof tmp, tmp) || !GetTempFileNameA(tmp, "s3s", 0, out)) return 0;
    DeleteFileA(out);
    return CreateDirectoryA(out, NULL) != 0;
#else
    if (cap < 32) return 0;
    snprintf(out, cap, "/tmp/shinobi-state-test-XXXXXX");
    return mkdtemp(out) != NULL;
#endif
}

static int write_file(const char *path, const void *bytes, size_t size)
{
    FILE *f = fopen(path, "wb");
    if (!f) return 0;
    int ok = fwrite(bytes, 1, size, f) == size;
    if (fclose(f)) ok = 0;
    return ok;
}

static int files_equal(const char *a, const char *b)
{
    FILE *fa = fopen(a, "rb"), *fb = fopen(b, "rb");
    unsigned char x[256], y[256];
    if (!fa || !fb) { if (fa) fclose(fa); if (fb) fclose(fb); return 0; }
    int equal = 0;
    for (;;) {
        size_t nx = fread(x, 1, sizeof x, fa), ny = fread(y, 1, sizeof y, fb);
        if (nx != ny || memcmp(x, y, nx)) break;
        if (nx < sizeof x) { equal = !ferror(fa) && !ferror(fb); break; }
    }
    fclose(fa); fclose(fb); return equal;
}

static void test_containers(void)
{
    static const uint8_t payload[] = { 0, 1, 2, 3, 0xA5, 0x5A, 0xFF };
    uint8_t *decoded = NULL;
    size_t decoded_size = 0;
    FILE *f = tmpfile();
    CHECK(f != NULL, "create temporary container stream");
    if (!f) return;
    CHECK(genesis_state_container_write(f, payload, sizeof payload, 0x5381506Fu),
          "write versioned state container");
    fflush(f); rewind(f);
    CHECK(genesis_state_container_read(f, 0x5381506Fu, sizeof payload,
                                       &decoded, &decoded_size) == GEN_STATE_FILE_OK,
          "read valid versioned state");
    CHECK(decoded_size == sizeof payload && !memcmp(decoded, payload, sizeof payload),
          "versioned state preserves payload bytes");
    free(decoded); decoded = NULL; rewind(f);
    CHECK(genesis_state_container_read(f, 0x12345678u, sizeof payload,
                                       &decoded, &decoded_size) == GEN_STATE_FILE_ROM,
          "reject state for a different ROM");
    free(decoded); decoded = NULL; fclose(f);

    f = tmpfile();
    CHECK(f != NULL, "create checksum test stream");
    if (f) {
        CHECK(genesis_state_container_write(f, payload, sizeof payload, 0x5381506Fu),
              "write checksum test state");
        fflush(f);
        CHECK(!fseek(f, -1, SEEK_END), "seek to state payload tail");
        int last = fgetc(f);
        CHECK(last != EOF && !fseek(f, -1, SEEK_CUR) && fputc(last ^ 0x80, f) != EOF,
              "corrupt payload byte for checksum test");
        fflush(f); rewind(f);
        CHECK(genesis_state_container_read(f, 0x5381506Fu, sizeof payload,
                                           &decoded, &decoded_size) == GEN_STATE_FILE_CHECKSUM,
              "reject corrupted versioned payload");
        free(decoded); decoded = NULL; fclose(f);
    }

    f = tmpfile();
    CHECK(f != NULL, "create payload-size test stream");
    if (f) {
        CHECK(genesis_state_container_write(f, payload, sizeof payload, 0x5381506Fu),
              "write payload-size test state");
        fflush(f); rewind(f);
        CHECK(genesis_state_container_read(f, 0x5381506Fu, sizeof payload - 1,
                                           &decoded, &decoded_size) == GEN_STATE_FILE_SIZE,
              "reject incompatible versioned payload size before applying it");
        free(decoded); decoded = NULL; fclose(f);
    }

    f = tmpfile();
    CHECK(f != NULL, "create temporary legacy stream");
    if (!f) return;
    CHECK(fwrite("GROWNS2\0", 1, 8, f) == 8 &&
          fwrite(payload, 1, sizeof payload, f) == sizeof payload,
          "write legacy GROWNS2 state");
    fflush(f); rewind(f);
    CHECK(genesis_state_container_read(f, 0x5381506Fu, sizeof payload,
                                       &decoded, &decoded_size) == GEN_STATE_FILE_OK,
          "load legacy GROWNS2 state");
    CHECK(decoded_size == sizeof payload && !memcmp(decoded, payload, sizeof payload),
          "legacy state remains byte-identical");
    free(decoded); decoded = NULL; rewind(f);
    CHECK(genesis_state_container_read(f, 0x5381506Fu, sizeof payload - 1,
                                       &decoded, &decoded_size) == GEN_STATE_FILE_SIZE,
          "reject legacy layout mismatch before applying state");
    free(decoded); fclose(f);

    f = tmpfile();
    CHECK(f != NULL, "create unknown-version stream");
    if (!f) return;
    uint8_t future[32] = {0}; memcpy(future, "GROWNS3\0", 8);
    future[8] = 2; future[12] = 32;
    CHECK(fwrite(future, 1, sizeof future, f) == sizeof future,
          "write unknown GROWNS3 version");
    fflush(f); rewind(f);
    CHECK(genesis_state_container_read(f, 0x5381506Fu, 0,
                                       &decoded, &decoded_size) == GEN_STATE_FILE_VERSION,
          "report unsupported future state version explicitly");
    fclose(f);
}

static void test_slots_and_migration(void)
{
    char root[1024] = {0}, package_a[1200], package_b[1200];
    char states[1200], states_again[1200], src[1400], dst[1400], path[1400];
    char original[1400];
    int copied = -1;
    CHECK(make_temp_root(root, sizeof root), "create isolated temp root");
    if (!root[0]) return;
#ifdef _WIN32
    const char *sep = "\\";
#else
    const char *sep = "/";
#endif
    snprintf(package_a, sizeof package_a, "%s%spackage-a", root, sep);
    snprintf(package_b, sizeof package_b, "%s%spackage-b", root, sep);
    CHECK(make_dir(package_a) && make_dir(package_b), "create simulated package folders");
    CHECK(genesis_state_store_init_at(root, "Shinobi3Recomp", states, sizeof states),
          "create persistent app-data state directory");
    CHECK(genesis_state_store_init_at(root, "Shinobi3Recomp", states_again, sizeof states_again),
          "reopen persistent app-data state directory from another package");
    CHECK(!strcmp(states, states_again), "persistent path does not depend on package directory");

    static const uint8_t legacy[] = { 'G','R','O','W','N','S','2',0, 9,8,7,6,5 };
    snprintf(src, sizeof src, "%s%snative_save_1.bin", package_a, sep);
    CHECK(write_file(src, legacy, sizeof legacy), "create package-local legacy checkpoint");
    snprintf(original, sizeof original, "%s%snative_save_1.bin", package_b, sep);
    CHECK(write_file(original, legacy, sizeof legacy), "retain a separate checkpoint reference");
    CHECK(genesis_state_store_migrate(package_a, states, &copied) && copied == 1,
          "import legacy checkpoint to persistent slot");
    CHECK(genesis_state_store_slot_path(states, 1, 0, dst, sizeof dst) && files_equal(src, dst),
          "import preserves exact checkpoint bytes");
    CHECK(files_equal(src, dst), "migration leaves original package save untouched");
    copied = -1;
    CHECK(genesis_state_store_migrate(package_a, states, &copied) && copied == 0,
          "migration is idempotent and does not duplicate the checkpoint");

    static const uint8_t collision[] = { 'G','R','O','W','N','S','2',0, 1,2,3 };
    CHECK(write_file(src, collision, sizeof collision), "replace only the test package copy");
    copied = -1;
    CHECK(genesis_state_store_migrate(package_a, states, &copied) && copied == 1,
          "import conflicting package save into a separate empty slot");
    /* Slot 1 keeps the old bytes; the differing checkpoint lands in slot 2. */
    CHECK(genesis_state_store_slot_path(states, 2, 0, dst, sizeof dst),
          "resolve conflict-import destination");
    CHECK(files_equal(src, dst), "conflicting checkpoint imported without overwriting slot 1");
    CHECK(genesis_state_store_slot_path(states, 1, 0, dst, sizeof dst),
          "resolve protected original destination");
    CHECK(files_equal(dst, original), "existing persistent slot 1 was not overwritten");
    copied = -1;
    CHECK(genesis_state_store_migrate(package_a, states, &copied) && copied == 0,
          "conflict migration does not duplicate imported state on restart");

    for (int slot = 1; slot <= GENESIS_STATE_SLOT_COUNT; ++slot) {
        uint8_t bytes[12] = { 'G','R','O','W','N','S','2',0,0,0,0,0 };
        bytes[8] = (uint8_t)slot;
        CHECK(genesis_state_store_slot_path(states, slot, 0, path, sizeof path),
              "resolve every valid save slot");
        /* Do not overwrite the migration samples used above. Other slots are
         * populated independently to verify the ten-slot namespace. */
        if (slot > 2) {
            CHECK(write_file(path, bytes, sizeof bytes), "write independent save slot");
            FILE *f = fopen(path, "rb");
            uint8_t readback[sizeof bytes] = {0};
            CHECK(f && fread(readback, 1, sizeof readback, f) == sizeof readback,
                  "read independent slot data");
            if (f) fclose(f);
            CHECK(readback[8] == (uint8_t)slot,
                  "a save slot does not overwrite neighboring slot data");
        }
    }
    CHECK(!genesis_state_store_slot_path(states, 0, 0, path, sizeof path) &&
          !genesis_state_store_slot_path(states, 11, 0, path, sizeof path),
          "reject out-of-range slots");

    CHECK(genesis_state_slot_cycle(1, -1) == 10 &&
          genesis_state_slot_cycle(10, 1) == 1,
          "selected-slot keyboard cycling wraps across ten slots");
    CHECK(genesis_state_slot_move_grid(1, 1, 0) == 2 &&
          genesis_state_slot_move_grid(2, 0, 1) == 4 &&
          genesis_state_slot_move_grid(10, 0, 1) == 10,
          "menu arrow navigation respects the two-column slot grid");
    CHECK(genesis_state_slot_from_function_key(100, 100, 109, 6) == 6 &&
          genesis_state_slot_from_function_key(101, 100, 109, 6) == 2 &&
          genesis_state_slot_from_function_key(109, 100, 109, 6) == 10,
          "F1 selected-slot and F2-F10 direct-slot dispatch");
    CHECK(genesis_state_slot_key_is_save(1) && !genesis_state_slot_key_is_save(0),
          "Shift selects save and plain function key selects load");
    CHECK(genesis_state_menu_chord_edge(0, 0x300, 0x100, 0x200) &&
          genesis_state_menu_chord_edge(0x100, 0x300, 0x100, 0x200) &&
          !genesis_state_menu_chord_edge(0x300, 0x300, 0x100, 0x200) &&
          !genesis_state_menu_chord_edge(0x300, 0x100, 0x100, 0x200),
          "L3+R3 chord opens once on the rising edge");
}

int main(void)
{
    test_containers();
    test_slots_and_migration();
    if (failures) {
        fprintf(stderr, "%d state-store assertion(s) failed\n", failures);
        return 1;
    }
    puts("PASS: 10-slot storage, selection, legacy import, versioning, CRC, and chord regressions");
    return 0;
}
