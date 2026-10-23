#ifndef SHINOBI_ROM_SHA256_H
#define SHINOBI_ROM_SHA256_H

#include <stddef.h>
#include <stdint.h>

int shinobi_sha256(const uint8_t *data, size_t size, uint8_t digest[32]);
int shinobi_rom_validate_sha256(const char *path, char *error, size_t error_size);

#endif
