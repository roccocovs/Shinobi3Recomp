#ifndef GENESIS_STATE_SLOTS_H
#define GENESIS_STATE_SLOTS_H

#include <stdint.h>

#include "state_store.h"

int genesis_state_slot_cycle(int current, int delta);
int genesis_state_slot_move_grid(int current, int dx, int dy);
int genesis_state_slot_from_function_key(int key, int f1_key, int f10_key,
                                         int selected_slot);
int genesis_state_slot_key_is_save(int shift_down);
int genesis_state_menu_chord_edge(uint32_t previous, uint32_t current,
                                  uint32_t l3_mask, uint32_t r3_mask);

#endif
