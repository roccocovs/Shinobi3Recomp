#ifndef SHINOBI_ROM_SELECTION_H
#define SHINOBI_ROM_SELECTION_H

#include <stddef.h>

typedef struct ShinobiRomSelectionOps {
    void *context;
    int (*validate)(void *context, const char *path, char *error, size_t error_size);
    int (*read_remembered)(void *context, char *path, size_t path_size);
    int (*write_remembered)(void *context, const char *path);
    /* Return 1 for a selected path, 0 for user cancellation, -1 for dialog error. */
    int (*select_path)(void *context, char *path, size_t path_size,
                       char *error, size_t error_size);
} ShinobiRomSelectionOps;

enum {
    SHINOBI_ROM_RESOLVE_ERROR = -1,
    SHINOBI_ROM_RESOLVE_INVALID = -2,
    SHINOBI_ROM_RESOLVE_CANCELLED = 0,
    SHINOBI_ROM_RESOLVE_OK = 1
};

/* Explicit paths always take precedence and are never replaced by a remembered
 * path. With no explicit path, a valid remembered path is reused unless the
 * caller requests the picker. Newly selected valid paths are persisted. */
int shinobi_rom_resolve(const char *explicit_path, int force_picker,
                        const ShinobiRomSelectionOps *ops,
                        char *resolved_path, size_t resolved_size,
                        char *error, size_t error_size);

#endif
