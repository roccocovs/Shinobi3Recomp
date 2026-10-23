#include "rom_selection.h"

#include <stdio.h>
#include <string.h>

typedef struct FakeRomStore {
    const char *remembered;
    const char *picked;
    const char *valid_path;
    int picker_result;
    int picker_calls;
    int read_calls;
    int write_calls;
} FakeRomStore;

static int fake_validate(void *context, const char *path, char *error, size_t cap)
{
    FakeRomStore *fake = (FakeRomStore *)context;
    if (fake->valid_path && strcmp(path, fake->valid_path) == 0) return 1;
    if (error && cap) snprintf(error, cap, "invalid test ROM: %s", path);
    return 0;
}

static int fake_read(void *context, char *out, size_t cap)
{
    FakeRomStore *fake = (FakeRomStore *)context;
    fake->read_calls++;
    if (!fake->remembered || strlen(fake->remembered) >= cap) return 0;
    strcpy(out, fake->remembered);
    return 1;
}

static int fake_write(void *context, const char *path)
{
    FakeRomStore *fake = (FakeRomStore *)context;
    fake->write_calls++;
    fake->remembered = path;
    return 1;
}

static int fake_pick(void *context, char *out, size_t cap,
                     char *error, size_t error_cap)
{
    FakeRomStore *fake = (FakeRomStore *)context;
    fake->picker_calls++;
    if (fake->picker_result <= 0) {
        if (fake->picker_result < 0 && error && error_cap)
            snprintf(error, error_cap, "mock picker error");
        return fake->picker_result;
    }
    if (!fake->picked || strlen(fake->picked) >= cap) return -1;
    strcpy(out, fake->picked);
    return 1;
}

static int check(int condition, const char *message)
{
    if (condition) return 1;
    fprintf(stderr, "FAIL: %s\n", message);
    return 0;
}

static void reset(FakeRomStore *fake)
{
    memset(fake, 0, sizeof(*fake));
    fake->valid_path = "valid-rom.gen";
    fake->picked = "valid-rom.gen";
    fake->picker_result = 1;
}

int main(void)
{
    FakeRomStore fake;
    ShinobiRomSelectionOps ops;
    char resolved[128], error[256];
    int ok = 1;

    reset(&fake);
    ops = (ShinobiRomSelectionOps){&fake, fake_validate, fake_read,
                                   fake_write, fake_pick};
    ok &= check(shinobi_rom_resolve(NULL, 0, &ops, resolved, sizeof(resolved),
                                    error, sizeof(error)) == SHINOBI_ROM_RESOLVE_OK,
                "first launch should accept a valid picker selection");
    ok &= check(strcmp(resolved, "valid-rom.gen") == 0 && fake.picker_calls == 1 &&
                fake.read_calls == 1 && fake.write_calls == 1,
                "first launch should save selected valid ROM");

    reset(&fake); fake.remembered = "valid-rom.gen";
    ok &= check(shinobi_rom_resolve(NULL, 0, &ops, resolved, sizeof(resolved),
                                    error, sizeof(error)) == SHINOBI_ROM_RESOLVE_OK &&
                fake.picker_calls == 0 && fake.write_calls == 0 &&
                strcmp(resolved, "valid-rom.gen") == 0,
                "valid remembered path should load without a picker");

    reset(&fake); fake.remembered = "valid-rom.gen";
    fake.picked = "alternate-copy.gen"; fake.valid_path = "alternate-copy.gen";
    ok &= check(shinobi_rom_resolve(NULL, 1, &ops, resolved, sizeof(resolved),
                                    error, sizeof(error)) == SHINOBI_ROM_RESOLVE_OK &&
                strcmp(resolved, "alternate-copy.gen") == 0 &&
                fake.picker_calls == 1 && fake.write_calls == 1,
                "forced picker should replace a valid remembered path for ROM changes");

    reset(&fake); fake.remembered = "moved-rom.gen";
    ok &= check(shinobi_rom_resolve(NULL, 0, &ops, resolved, sizeof(resolved),
                                    error, sizeof(error)) == SHINOBI_ROM_RESOLVE_OK &&
                fake.picker_calls == 1 && fake.write_calls == 1,
                "a missing or invalid remembered path should prompt and replace it");

    reset(&fake); fake.picked = "bad-rom.gen";
    ok &= check(shinobi_rom_resolve(NULL, 1, &ops, resolved, sizeof(resolved),
                                    error, sizeof(error)) == SHINOBI_ROM_RESOLVE_INVALID &&
                strstr(error, "bad-rom.gen") != NULL && fake.write_calls == 0,
                "an invalid picker selection must be rejected and not remembered");

    reset(&fake); fake.picker_result = 0;
    ok &= check(shinobi_rom_resolve(NULL, 0, &ops, resolved, sizeof(resolved),
                                    error, sizeof(error)) == SHINOBI_ROM_RESOLVE_CANCELLED,
                "canceling the picker should return a clean cancellation");

    reset(&fake); fake.remembered = "other-valid.gen";
    fake.valid_path = "explicit.gen";
    ok &= check(shinobi_rom_resolve("explicit.gen", 1, &ops, resolved,
                                    sizeof(resolved), error, sizeof(error)) ==
                    SHINOBI_ROM_RESOLVE_OK && strcmp(resolved, "explicit.gen") == 0 &&
                fake.picker_calls == 0 && fake.read_calls == 0,
                "explicit positional path must take precedence over saved path and picker");

    reset(&fake); fake.remembered = "valid-rom.gen";
    ok &= check(shinobi_rom_resolve("wrong.gen", 0, &ops, resolved,
                                    sizeof(resolved), error, sizeof(error)) ==
                    SHINOBI_ROM_RESOLVE_INVALID && fake.picker_calls == 0 &&
                fake.read_calls == 0,
                "an invalid explicit path must fail without falling back silently");

    if (!ok) return 1;
    puts("PASS ROM selection: first run, valid/stale config, invalid selection, cancel, explicit precedence");
    return 0;
}
