#include "rom_parser.h"

#include <stdint.h>

int main(void)
{
    uint8_t bytes[] = {0xD0, 0xA1, 0xB2, 0xC3, 0x11};
    GenesisRom rom = {
        .rom_data = bytes,
        .rom_size = sizeof(bytes),
    };

    if (rom_read32(&rom, 0) != 0xD0A1B2C3u)
        return 1;
    if (rom_read32(&rom, 1) != 0xA1B2C311u)
        return 2;
    if (rom_read32(&rom, 2) != 0xFFFFFFFFu)
        return 3;
    return 0;
}
