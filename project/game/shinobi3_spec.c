#include "game_spec.h"
#include "input_map.h"
#include "genesis_runtime.h"

#include <SDL2/SDL.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int shinobi3_six_button_controller_enabled(void)
{
    const char *value = getenv("GENESIS_SHINOBI_EXPERT_CONTROLS");
    /* Shinobi III's action controls use the six-button handshake. Make that
       controller the game-specific default; retain an explicit opt-out for
       comparing behavior with a three-button pad. */
    return !value || (strcmp(value, "0") != 0 && strcmp(value, "false") != 0 &&
                      strcmp(value, "off") != 0);
}

static void shinobi3_bind_pad_button(GenesisButton button, SDL_GameControllerButton pad_button)
{
    GamepadBind *binding = &g_input_map.p[0].pad[button];
    binding->kind = GP_BIND_BUTTON;
    binding->code = pad_button;
    binding->axis_dir = 0;
}

static void shinobi3_unbind_pad_button(GenesisButton button)
{
    GamepadBind *binding = &g_input_map.p[0].pad[button];
    binding->kind = GP_BIND_NONE;
    binding->code = 0;
    binding->axis_dir = 0;
}

static void shinobi3_call_entry(void)
{
    recomp_call_addr(0x000320u);
}

static void shinobi3_call_vblank(void)
{
    recomp_call_addr(0x000522u);
    if (shinobi3_six_button_controller_enabled()) {
        /* The ROM clears this flag during startup and only restores it after
           its two-controller unlock check. This build exposes the six-button
           actions directly, so keep the mode flag aligned with the pad type. */
        m68k_write8(0x00FF000Au, 0x41u);
    }
}

static void shinobi3_call_hblank(void)
{
    /* The ROM's level-4 vector is $FF0004, a JMP absolute-long veneer.
       Reset installs its opcode and $FF0006 operand; stage setup replaces
       the operand with the raster handler. Dispatch that live destination
       natively, preserving the runner's interrupt save/restore contract. */
    recomp_call_addr(m68k_read32(0x00FF0006u) & 0x00FFFFFFu);
}

static void shinobi3_apply_input_mode(void)
{
    if (!shinobi3_six_button_controller_enabled())
        return;
    PlayerInput *p1 = &g_input_map.p[0];
    p1->pad_type = PAD_6BUTTON;

    /* Restore gameplay movement and Start too: the launcher may have reloaded
       stale per-button settings after this game profile was first applied. */
    shinobi3_bind_pad_button(GB_UP, SDL_CONTROLLER_BUTTON_DPAD_UP);
    shinobi3_bind_pad_button(GB_DOWN, SDL_CONTROLLER_BUTTON_DPAD_DOWN);
    shinobi3_bind_pad_button(GB_LEFT, SDL_CONTROLLER_BUTTON_DPAD_LEFT);
    shinobi3_bind_pad_button(GB_RIGHT, SDL_CONTROLLER_BUTTON_DPAD_RIGHT);
    shinobi3_bind_pad_button(GB_START, SDL_CONTROLLER_BUTTON_START);

    /* Shinobi III's six-button layout separates the attack actions. Use the
       preferred DualSense layout: Square shuriken, Cross jump, Circle ninjitsu,
       L1 block, and R1 melee. Bind only one shuriken input to prevent duplicate
       attack bits from a single Square press. */
    shinobi3_bind_pad_button(GB_A, SDL_CONTROLLER_BUTTON_LEFTSHOULDER);
    shinobi3_bind_pad_button(GB_B, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER);
    shinobi3_bind_pad_button(GB_C, SDL_CONTROLLER_BUTTON_A);
    shinobi3_bind_pad_button(GB_X, SDL_CONTROLLER_BUTTON_B);
    shinobi3_bind_pad_button(GB_Y, SDL_CONTROLLER_BUTTON_X);
    shinobi3_unbind_pad_button(GB_Z);
}

static void shinobi3_load_settings(const char *settings_path)
{
    (void)settings_path;
    /* The upstream runner has already loaded defaults/settings at this point. */
    shinobi3_apply_input_mode();
    fprintf(stderr, "[input] Shinobi six-button profile %s\n",
            shinobi3_six_button_controller_enabled() ? "enabled" : "disabled");
}

static void shinobi3_on_post_reset(void)
{
    shinobi3_apply_input_mode();
}

static void shinobi3_on_state_loaded(void)
{
    shinobi3_apply_input_mode();
}

const GameSpec g_game_spec = {
    .display_name = "Shinobi III: Return of the Ninja Master",
    .short_name = "Shinobi3",
    .state_storage_id = "Shinobi3Recomp",
    .load_settings = shinobi3_load_settings,
    .expected_rom_size = 0x100000u,
    .expected_rom_crc32 = 0x5381506Fu,
    /* The complete native-first route was verified with the interpreter floor off. */
    .tier3_floor_default = 0,
    .call_entry_point = shinobi3_call_entry,
    .call_vblank = shinobi3_call_vblank,
    .call_hblank = shinobi3_call_hblank,
    .on_post_reset = shinobi3_on_post_reset,
    .on_state_loaded = shinobi3_on_state_loaded,
    /* $000512 polls for VBlank before dispatching the restored game callback. */
    .resume_main_loop_pc = 0x000512u,
};
