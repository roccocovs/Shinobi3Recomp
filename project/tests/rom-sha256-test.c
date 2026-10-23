#include "rom_sha256.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

static int check(int condition, const char *message)
{
    if (condition) return 1;
    fprintf(stderr, "FAIL: %s\n", message);
    return 0;
}

int main(int argc, char **argv)
{
    static const unsigned char abc[] = {'a', 'b', 'c'};
    static const unsigned char abc_sha256[32] = {
        0xBA,0x78,0x16,0xBF,0x8F,0x01,0xCF,0xEA,0x41,0x41,0x40,0xDE,0x5D,0xAE,0x22,0x23,
        0xB0,0x03,0x61,0xA3,0x96,0x17,0x7A,0x9C,0xB4,0x10,0xFF,0x61,0xF2,0x00,0x15,0xAD
    };
    uint8_t digest[32];
    int ok = 1;
    char error[256];
    char bad_path[MAX_PATH];
    FILE *source, *bad;
    uint8_t *bytes = NULL;
    long size;

    ok &= check(shinobi_sha256(abc, sizeof(abc), digest) &&
                memcmp(digest, abc_sha256, sizeof(digest)) == 0,
                "SHA-256 known vector must match");
    ok &= check(argc == 2 && shinobi_rom_validate_sha256(argv[1], error, sizeof(error)),
                "the documented supported ROM must validate");
    if (argc != 2) return 1;

    source = fopen(argv[1], "rb");
    if (!source || fseek(source, 0, SEEK_END) != 0 ||
        (size = ftell(source)) != 1048576 || fseek(source, 0, SEEK_SET) != 0) {
        if (source) fclose(source);
        fprintf(stderr, "FAIL: could not read test ROM fixture\n");
        return 1;
    }
    bytes = (uint8_t *)malloc((size_t)size);
    if (!bytes || fread(bytes, 1, (size_t)size, source) != (size_t)size) {
        free(bytes); fclose(source);
        fprintf(stderr, "FAIL: could not copy test ROM fixture\n");
        return 1;
    }
    fclose(source);
    bytes[0x100] ^= 1u;
    if (!GetTempPathA(MAX_PATH, bad_path) ||
        !GetTempFileNameA(bad_path, "s3r", 0, bad_path)) {
        free(bytes);
        fprintf(stderr, "FAIL: could not create temporary invalid ROM path\n");
        return 1;
    }
    bad = fopen(bad_path, "wb");
    if (!bad || fwrite(bytes, 1, (size_t)size, bad) != (size_t)size) {
        if (bad) fclose(bad);
        DeleteFileA(bad_path); free(bytes);
        fprintf(stderr, "FAIL: could not write temporary invalid ROM\n");
        return 1;
    }
    fclose(bad); free(bytes);
    ok &= check(!shinobi_rom_validate_sha256(bad_path, error, sizeof(error)) &&
                strstr(error, "not the supported ROM") != NULL,
                "same-size altered ROM must be rejected by SHA-256");
    DeleteFileA(bad_path);

    ok &= check(!shinobi_rom_validate_sha256(bad_path, error, sizeof(error)) &&
                strstr(error, "could not be opened") != NULL,
                "a missing ROM path must produce a clear open error");
    if (!GetTempPathA(MAX_PATH, bad_path) ||
        !GetTempFileNameA(bad_path, "s3r", 0, bad_path)) {
        fprintf(stderr, "FAIL: could not create temporary short ROM path\n");
        return 1;
    }
    bad = fopen(bad_path, "wb");
    if (!bad || fwrite("not a ROM", 1, 9, bad) != 9) {
        if (bad) fclose(bad);
        DeleteFileA(bad_path);
        fprintf(stderr, "FAIL: could not write temporary short ROM\n");
        return 1;
    }
    fclose(bad);
    ok &= check(!shinobi_rom_validate_sha256(bad_path, error, sizeof(error)) &&
                strstr(error, "exactly 1 MiB") != NULL,
                "a wrong-size ROM must be rejected before hashing");
    DeleteFileA(bad_path);

    if (!ok) return 1;
    puts("PASS ROM SHA-256: known vector, exact supported image, modified same-size rejection");
    return 0;
}
