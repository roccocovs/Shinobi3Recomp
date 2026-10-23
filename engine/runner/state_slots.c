#include "state_slots.h"

static int clamp_int(int v, int lo, int hi)
{ return v < lo ? lo : v > hi ? hi : v; }

int genesis_state_slot_cycle(int current, int delta)
{
    if (current < 1 || current > GENESIS_STATE_SLOT_COUNT) current = 1;
    int index = (current - 1 + delta) % GENESIS_STATE_SLOT_COUNT;
    if (index < 0) index += GENESIS_STATE_SLOT_COUNT;
    return index + 1;
}

int genesis_state_slot_move_grid(int current, int dx, int dy)
{
    if (current < 1 || current > GENESIS_STATE_SLOT_COUNT) current = 1;
    int index = current - 1;
    int col = index % 2, row = index / 2;
    col = clamp_int(col + dx, 0, 1);
    row = clamp_int(row + dy, 0, 4);
    return row * 2 + col + 1;
}

int genesis_state_slot_from_function_key(int key, int f1_key, int f10_key,
                                         int selected_slot)
{
    if (key == f1_key)
        return selected_slot >= 1 && selected_slot <= GENESIS_STATE_SLOT_COUNT
            ? selected_slot : 1;
    if (key > f1_key && key <= f10_key) {
        int slot = key - f1_key + 1;
        return slot <= GENESIS_STATE_SLOT_COUNT ? slot : 0;
    }
    return 0;
}

int genesis_state_slot_key_is_save(int shift_down)
{ return shift_down != 0; }

int genesis_state_menu_chord_edge(uint32_t previous, uint32_t current,
                                  uint32_t l3_mask, uint32_t r3_mask)
{
    uint32_t chord = l3_mask | r3_mask;
    return (current & chord) == chord && (previous & chord) != chord;
}
