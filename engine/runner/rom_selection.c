#include "rom_selection.h"

#include <stdio.h>
#include <string.h>

static int copy_path(char *out, size_t cap, const char *path,
                     char *error, size_t error_cap)
{
    size_t n;
    if (!out || cap == 0 || !path || !path[0]) {
        if (error && error_cap) snprintf(error, error_cap, "No ROM path was supplied.");
        return SHINOBI_ROM_RESOLVE_ERROR;
    }
    n = strlen(path);
    if (n >= cap) {
        if (error && error_cap) snprintf(error, error_cap, "The selected ROM path is too long.");
        return SHINOBI_ROM_RESOLVE_ERROR;
    }
    memcpy(out, path, n + 1);
    return SHINOBI_ROM_RESOLVE_OK;
}

int shinobi_rom_resolve(const char *explicit_path, int force_picker,
                        const ShinobiRomSelectionOps *ops,
                        char *resolved_path, size_t resolved_size,
                        char *error, size_t error_size)
{
    char candidate[4096] = "";
    int selected;

    if (error && error_size) error[0] = '\0';
    if (!ops || !ops->validate || !ops->select_path ||
        !resolved_path || resolved_size == 0) {
        if (error && error_size) snprintf(error, error_size, "ROM selection is not configured.");
        return SHINOBI_ROM_RESOLVE_ERROR;
    }

    if (explicit_path && explicit_path[0]) {
        if (!ops->validate(ops->context, explicit_path, error, error_size))
            return SHINOBI_ROM_RESOLVE_INVALID;
        return copy_path(resolved_path, resolved_size, explicit_path, error, error_size);
    }

    if (!force_picker && ops->read_remembered &&
        ops->read_remembered(ops->context, candidate, sizeof(candidate)) &&
        candidate[0] && ops->validate(ops->context, candidate, NULL, 0))
        return copy_path(resolved_path, resolved_size, candidate, error, error_size);

    candidate[0] = '\0';
    selected = ops->select_path(ops->context, candidate, sizeof(candidate),
                                error, error_size);
    if (selected == 0)
        return SHINOBI_ROM_RESOLVE_CANCELLED;
    if (selected < 0)
        return SHINOBI_ROM_RESOLVE_ERROR;
    if (!ops->validate(ops->context, candidate, error, error_size))
        return SHINOBI_ROM_RESOLVE_INVALID;

    if (ops->write_remembered && !ops->write_remembered(ops->context, candidate) &&
        error && error_size)
        snprintf(error, error_size, "The ROM is valid, but its location could not be saved for next time.");
    return copy_path(resolved_path, resolved_size, candidate, NULL, 0);
}
