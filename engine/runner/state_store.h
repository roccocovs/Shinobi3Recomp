#ifndef GENESIS_STATE_STORE_H
#define GENESIS_STATE_STORE_H

#include <stddef.h>

enum { GENESIS_STATE_SLOT_COUNT = 10 };

/* Returns a stable per-user <app-id>/states directory, with a trailing slash. */
int genesis_state_store_init(const char *exe_dir, const char *app_id,
                             char *out, size_t out_cap);

/* Explicit root variant used by portable tests. */
int genesis_state_store_init_at(const char *root, const char *app_id,
                                char *out, size_t out_cap);

int genesis_state_store_resolve(const char *state_dir, const char *name,
                                char *out, size_t out_cap);
int genesis_state_store_slot_path(const char *state_dir, int slot, int thumb,
                                  char *out, size_t out_cap);

/* Import recognized package-local states without deleting or replacing files.
 * Conflicting source slots are copied into the first empty destination slot.
 * Returns 1 on a completed scan, 0 on an invalid directory/argument. */
int genesis_state_store_migrate(const char *package_dir, const char *state_dir,
                                int *copied_count);

#endif
