#ifndef GENESIS_STATE_CONTAINER_H
#define GENESIS_STATE_CONTAINER_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

enum GenesisStateFileStatus {
    GEN_STATE_FILE_OK = 0,
    GEN_STATE_FILE_IO,
    GEN_STATE_FILE_MAGIC,
    GEN_STATE_FILE_VERSION,
    GEN_STATE_FILE_ROM,
    GEN_STATE_FILE_SIZE,
    GEN_STATE_FILE_CHECKSUM
};

int genesis_state_container_write(FILE *out, const uint8_t *payload,
                                  size_t payload_size, uint32_t rom_crc);
enum GenesisStateFileStatus genesis_state_container_read(
    FILE *in, uint32_t expected_rom_crc, size_t expected_legacy_payload_size,
    uint8_t **payload_out, size_t *payload_size_out);
const char *genesis_state_container_status_string(enum GenesisStateFileStatus status);

#endif
