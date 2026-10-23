#include "game_spec.h"
#include "genesis_runtime.h"
#include "input_map.h"

#define SDL_MAIN_HANDLED
#include <SDL2/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

InputMap g_input_map;

static uint8_t s_action_mode;
static uint32_t s_expected_entry = 0x000522u;
static uint32_t s_hblank_entry;

static void fail(const char *message)
{
    fprintf(stderr, "controller profile test failed: %s\n", message);
    exit(1);
}

static void expect_binding(GenesisButton button, SDL_GameControllerButton expected)
{
    const GamepadBind *binding = &g_input_map.p[0].pad[button];
    if (binding->kind != GP_BIND_BUTTON || binding->code != expected || binding->axis_dir != 0)
        fail("button mapping does not match the requested DualSense layout");
}

void recomp_call_addr(uint32_t addr)
{
    if (addr != s_expected_entry)
        fail("interrupt callback called the wrong ROM address");
    /* Model the ROM's startup reset of the action mode before the adapter reapplies it. */
    s_action_mode = 0;
}

void m68k_write8(uint32_t addr, uint8_t value)
{
    if (addr != 0x00FF000Au)
        fail("adapter wrote outside the controller-mode flag");
    s_action_mode = value;
}

uint32_t m68k_read32(uint32_t addr)
{
    if (addr == 0x00FF0006u)
        return s_hblank_entry;
    fail("unexpected 68000 longword read");
    return 0;
}

int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    _putenv_s("GENESIS_SHINOBI_EXPERT_CONTROLS", "");
    memset(&g_input_map, 0, sizeof(g_input_map));

    g_game_spec.load_settings(NULL);
    if (g_input_map.p[0].pad_type != PAD_6BUTTON)
        fail("six-button controller mode is not enabled by default");

    expect_binding(GB_Y, SDL_CONTROLLER_BUTTON_X); /* Square: shuriken */
    expect_binding(GB_C, SDL_CONTROLLER_BUTTON_A); /* Cross: jump */
    expect_binding(GB_X, SDL_CONTROLLER_BUTTON_B); /* Circle: ninjitsu */
    expect_binding(GB_A, SDL_CONTROLLER_BUTTON_LEFTSHOULDER); /* L1: block */
    expect_binding(GB_B, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER); /* R1: melee */
    if (g_input_map.p[0].pad[GB_Z].kind != GP_BIND_NONE)
        fail("unused duplicate shuriken input remains bound");

    g_input_map.p[0].pad_type = PAD_3BUTTON;
    g_input_map.p[0].pad[GB_C].code = SDL_CONTROLLER_BUTTON_X;
    g_game_spec.on_post_reset();
    if (g_input_map.p[0].pad_type != PAD_6BUTTON)
        fail("controller mode was not restored after a game reset");
    expect_binding(GB_C, SDL_CONTROLLER_BUTTON_A);

    g_input_map.p[0].pad_type = PAD_3BUTTON;
    g_input_map.p[0].pad[GB_C].code = SDL_CONTROLLER_BUTTON_X;
    g_game_spec.on_state_loaded();
    if (g_input_map.p[0].pad_type != PAD_6BUTTON)
        fail("controller mode was not restored after a state load");
    expect_binding(GB_C, SDL_CONTROLLER_BUTTON_A);

    /* Model the launcher's post-selection reload, which may replace every
       binding and the controller type before the game starts. */
    g_input_map.p[0].device = INPUT_DEV_GAMEPAD;
    g_input_map.p[0].pad_type = PAD_3BUTTON;
    g_input_map.p[0].pad[GB_RIGHT].code = SDL_CONTROLLER_BUTTON_BACK;
    g_input_map.p[0].pad[GB_START].code = SDL_CONTROLLER_BUTTON_BACK;
    g_input_map.p[0].pad[GB_Y].code = SDL_CONTROLLER_BUTTON_Y;
    g_input_map.p[0].pad[GB_C].code = SDL_CONTROLLER_BUTTON_X;
    g_game_spec.load_settings(NULL);
    if (g_input_map.p[0].pad_type != PAD_6BUTTON)
        fail("launcher settings reload did not restore six-button mode");
    if (g_input_map.p[0].device != INPUT_DEV_GAMEPAD)
        fail("game-specific controls changed the launcher device choice");
    expect_binding(GB_UP, SDL_CONTROLLER_BUTTON_DPAD_UP);
    expect_binding(GB_DOWN, SDL_CONTROLLER_BUTTON_DPAD_DOWN);
    expect_binding(GB_LEFT, SDL_CONTROLLER_BUTTON_DPAD_LEFT);
    expect_binding(GB_RIGHT, SDL_CONTROLLER_BUTTON_DPAD_RIGHT);
    expect_binding(GB_START, SDL_CONTROLLER_BUTTON_START);
    expect_binding(GB_Y, SDL_CONTROLLER_BUTTON_X);
    expect_binding(GB_C, SDL_CONTROLLER_BUTTON_A);
    expect_binding(GB_X, SDL_CONTROLLER_BUTTON_B);
    expect_binding(GB_A, SDL_CONTROLLER_BUTTON_LEFTSHOULDER);
    expect_binding(GB_B, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER);
    g_game_spec.call_vblank();
    if (s_action_mode != 0x41u)
        fail("VBlank callback did not restore the six-button action mode");

    if (!g_game_spec.call_hblank)
        fail("the ROM horizontal-interrupt callback is missing");
    s_hblank_entry = s_expected_entry = 0x0005B4u;
    g_game_spec.call_hblank();
    s_hblank_entry = s_expected_entry = 0x00249Au;
    g_game_spec.call_hblank();

    /* HBlank probes above replace the shared address expectation. Restore the
       VBlank vector before checking that six-button mode is reapplied there. */
    s_expected_entry = 0x000522u;
    g_game_spec.call_vblank();
    if (s_action_mode != 0x41u)
        fail("VBlank callback did not restore the six-button action mode after HBlank");

    puts("Controller profile and horizontal-interrupt routing passed.");
    return 0;
}
