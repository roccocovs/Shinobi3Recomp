#include "rom_sha256.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#endif

#define SHINOBI_ROM_BYTES 1048576u
#define SHINOBI_ROM_SHA256 "e0c50ed80fa1b75325344c2260a26841936d077e2ae1689c2522e3cc484739e3"

int shinobi_sha256(const uint8_t *data, size_t size, uint8_t digest[32])
{
#ifdef _WIN32
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    PUCHAR object = NULL;
    ULONG object_size = 0, digest_size = 0, result_size = 0;
    NTSTATUS status;
    int ok = 0;
    if ((!data && size) || !digest || size > 0xFFFFFFFFu) return 0;
    status = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM,
                                         NULL, 0);
    if (status < 0) goto done;
    status = BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                               (PUCHAR)&object_size, sizeof(object_size),
                               &result_size, 0);
    if (status < 0 || object_size == 0) goto done;
    status = BCryptGetProperty(algorithm, BCRYPT_HASH_LENGTH,
                               (PUCHAR)&digest_size, sizeof(digest_size),
                               &result_size, 0);
    if (status < 0 || digest_size != 32) goto done;
    object = (PUCHAR)malloc(object_size);
    if (!object) goto done;
    status = BCryptCreateHash(algorithm, &hash, object, object_size,
                              NULL, 0, 0);
    if (status < 0) goto done;
    if (size) {
        status = BCryptHashData(hash, (PUCHAR)data, (ULONG)size, 0);
        if (status < 0) goto done;
    }
    status = BCryptFinishHash(hash, digest, 32, 0);
    if (status >= 0) ok = 1;
done:
    if (hash) BCryptDestroyHash(hash);
    if (object) free(object);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    return ok;
#else
    (void)data; (void)size; (void)digest;
    return 0;
#endif
}

static void hex_digest(const uint8_t digest[32], char out[65])
{
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < 32; ++i) {
        out[i * 2] = hex[digest[i] >> 4];
        out[i * 2 + 1] = hex[digest[i] & 15];
    }
    out[64] = '\0';
}

int shinobi_rom_validate_sha256(const char *path, char *error, size_t error_size)
{
    FILE *file;
    long length;
    uint8_t *bytes = NULL;
    uint8_t digest[32];
    char actual[65];
    int valid = 0;

    if (error && error_size) error[0] = '\0';
    if (!path || !path[0]) {
        if (error && error_size) snprintf(error, error_size, "No ROM file was selected.");
        return 0;
    }
    file = fopen(path, "rb");
    if (!file) {
        if (error && error_size) snprintf(error, error_size, "The ROM file could not be opened.");
        return 0;
    }
    if (fseek(file, 0, SEEK_END) != 0 || (length = ftell(file)) < 0 ||
        fseek(file, 0, SEEK_SET) != 0) {
        if (error && error_size) snprintf(error, error_size, "The ROM file could not be read.");
        goto done;
    }
    if ((unsigned long)length != SHINOBI_ROM_BYTES) {
        if (error && error_size)
            snprintf(error, error_size, "This ROM has %ld bytes; the supported image must be exactly 1 MiB.", length);
        goto done;
    }
    bytes = (uint8_t *)malloc(SHINOBI_ROM_BYTES);
    if (!bytes) {
        if (error && error_size) snprintf(error, error_size, "Not enough memory to validate the ROM.");
        goto done;
    }
    if (fread(bytes, 1, SHINOBI_ROM_BYTES, file) != SHINOBI_ROM_BYTES) {
        if (error && error_size) snprintf(error, error_size, "The ROM file could not be read completely.");
        goto done;
    }
    if (!shinobi_sha256(bytes, SHINOBI_ROM_BYTES, digest)) {
        if (error && error_size) snprintf(error, error_size, "Windows could not calculate the ROM checksum.");
        goto done;
    }
    hex_digest(digest, actual);
    if (strcmp(actual, SHINOBI_ROM_SHA256) != 0) {
        if (error && error_size)
            snprintf(error, error_size,
                     "This is not the supported ROM image.\nExpected SHA-256: %s\nFound: %s",
                     SHINOBI_ROM_SHA256, actual);
        goto done;
    }
    valid = 1;
done:
    free(bytes);
    fclose(file);
    return valid;
}
