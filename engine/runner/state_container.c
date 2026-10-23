#include "state_container.h"

#include <limits.h>
#include <stdlib.h>
#include <string.h>

#define STATE_V3_HEADER_SIZE 32u
#define STATE_MAX_PAYLOAD (16u * 1024u * 1024u)

static uint32_t read32le(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t read64le(const uint8_t *p)
{
    return (uint64_t)read32le(p) | ((uint64_t)read32le(p + 4) << 32);
}

static void write32le(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static void write64le(uint8_t *p, uint64_t v)
{
    write32le(p, (uint32_t)v); write32le(p + 4, (uint32_t)(v >> 32));
}

static uint32_t crc32_bytes(const uint8_t *data, size_t size)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

int genesis_state_container_write(FILE *out, const uint8_t *payload,
                                  size_t payload_size, uint32_t rom_crc)
{
    uint8_t header[STATE_V3_HEADER_SIZE] = {0};
    if (!out || !payload || !payload_size || payload_size > STATE_MAX_PAYLOAD)
        return 0;
    memcpy(header, "GROWNS3\0", 8);
    write32le(header + 8, 1u);
    write32le(header + 12, STATE_V3_HEADER_SIZE);
    write64le(header + 16, (uint64_t)payload_size);
    write32le(header + 24, rom_crc);
    write32le(header + 28, crc32_bytes(payload, payload_size));
    return fwrite(header, 1, sizeof header, out) == sizeof header &&
           fwrite(payload, 1, payload_size, out) == payload_size &&
           !ferror(out);
}

enum GenesisStateFileStatus genesis_state_container_read(
    FILE *in, uint32_t expected_rom_crc, size_t expected_legacy_payload_size,
    uint8_t **payload_out, size_t *payload_size_out)
{
    uint8_t magic[8];
    uint8_t *payload = NULL;
    long end;
    enum GenesisStateFileStatus result = GEN_STATE_FILE_IO;
    if (payload_out) *payload_out = NULL;
    if (payload_size_out) *payload_size_out = 0;
    if (!in || !payload_out || !payload_size_out || fseek(in, 0, SEEK_END) ||
        (end = ftell(in)) < 8 || fseek(in, 0, SEEK_SET)) return GEN_STATE_FILE_IO;
    if (fread(magic, 1, sizeof magic, in) != sizeof magic) return GEN_STATE_FILE_IO;

    if (!memcmp(magic, "GROWNS2\0", 8)) {
        size_t payload_size = (size_t)(end - 8);
        if (!expected_legacy_payload_size || payload_size != expected_legacy_payload_size)
            return GEN_STATE_FILE_SIZE;
        payload = (uint8_t *)malloc(payload_size);
        if (!payload) return GEN_STATE_FILE_IO;
        if (fread(payload, 1, payload_size, in) != payload_size || ferror(in)) {
            result = GEN_STATE_FILE_IO; goto done;
        }
        *payload_out = payload; *payload_size_out = payload_size;
        return GEN_STATE_FILE_OK;
    }
    if (memcmp(magic, "GROWNS3\0", 8)) return GEN_STATE_FILE_MAGIC;

    uint8_t header[STATE_V3_HEADER_SIZE];
    memcpy(header, magic, 8);
    if (fread(header + 8, 1, STATE_V3_HEADER_SIZE - 8, in) != STATE_V3_HEADER_SIZE - 8)
        return GEN_STATE_FILE_IO;
    uint32_t version = read32le(header + 8);
    uint32_t header_size = read32le(header + 12);
    uint64_t payload_u64 = read64le(header + 16);
    if (version != 1u || header_size != STATE_V3_HEADER_SIZE)
        return GEN_STATE_FILE_VERSION;
    if (read32le(header + 24) != expected_rom_crc) return GEN_STATE_FILE_ROM;
    if (!payload_u64 || payload_u64 > STATE_MAX_PAYLOAD ||
        payload_u64 > (uint64_t)LONG_MAX ||
        (uint64_t)end != STATE_V3_HEADER_SIZE + payload_u64 ||
        (expected_legacy_payload_size && payload_u64 != expected_legacy_payload_size))
        return GEN_STATE_FILE_SIZE;
    size_t payload_size = (size_t)payload_u64;
    payload = (uint8_t *)malloc(payload_size);
    if (!payload) return GEN_STATE_FILE_IO;
    if (fread(payload, 1, payload_size, in) != payload_size || ferror(in)) {
        result = GEN_STATE_FILE_IO; goto done;
    }
    if (crc32_bytes(payload, payload_size) != read32le(header + 28)) {
        result = GEN_STATE_FILE_CHECKSUM; goto done;
    }
    *payload_out = payload; *payload_size_out = payload_size;
    return GEN_STATE_FILE_OK;
done:
    free(payload);
    return result;
}

const char *genesis_state_container_status_string(enum GenesisStateFileStatus status)
{
    switch (status) {
    case GEN_STATE_FILE_OK: return "valid";
    case GEN_STATE_FILE_IO: return "read or allocation error";
    case GEN_STATE_FILE_MAGIC: return "unsupported save-state format";
    case GEN_STATE_FILE_VERSION: return "unsupported save-state version";
    case GEN_STATE_FILE_ROM: return "save belongs to a different ROM";
    case GEN_STATE_FILE_SIZE: return "incompatible or truncated save-state size";
    case GEN_STATE_FILE_CHECKSUM: return "save-state checksum mismatch";
    default: return "unknown save-state error";
    }
}
