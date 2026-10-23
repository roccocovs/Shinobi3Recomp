#!/usr/bin/env python3
"""Static guard for production keyboard/DualSense save-slot wiring."""

import argparse
from pathlib import Path


def need(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, type=Path)
    ap.add_argument("--game-spec", required=True, type=Path)
    ap.add_argument("--main", required=True, type=Path)
    args = ap.parse_args()
    main = args.main.read_text(encoding="utf-8")
    gamepad = (args.engine / "gamepad.c").read_text(encoding="utf-8")
    spec = args.game_spec.read_text(encoding="utf-8")
    need("SDLK_LEFTBRACKET" in main and "SDLK_RIGHTBRACKET" in main and
         "genesis_local_states_cycle_slot" in main,
         "keyboard selected-slot cycling is not wired")
    need("SDLK_F1, SDLK_F10" in main and
         "genesis_state_slot_from_function_key" in main and
         "genesis_state_slot_key_is_save" in main,
         "F1/Shift+F1 selected-slot save/load dispatch is missing")
    need('"states.slot"' in main and "GENESIS_STATE_SLOT_COUNT,1" in main and
         'genesis_local_states_selected_slot();' in main and
         'runner_save_state_file(path):runner_load_state_file(path)' in main,
         "runtime settings do not expose all persistent slots to the own-backend save path")
    need("GP_OVERLAY_L3, GP_OVERLAY_R3" in main and
         "genesis_state_menu_chord_edge" in main,
         "the L3+R3 edge-triggered menu chord is not wired")
    need("SDL_CONTROLLER_BUTTON_LEFTSTICK, GP_OVERLAY_L3" in gamepad and
         "SDL_CONTROLLER_BUTTON_RIGHTSTICK, GP_OVERLAY_R3" in gamepad,
         "SDL controller thumbstick-click mapping changed")
    need('.state_storage_id = "Shinobi3Recomp"' in spec,
         "Shinobi does not select stable per-user save storage")
    need("SDL_CONTROLLER_BUTTON_LEFTSHOULDER" in spec and
         "SDL_CONTROLLER_BUTTON_RIGHTSHOULDER" in spec and
         "SDL_CONTROLLER_BUTTON_A" in spec and "SDL_CONTROLLER_BUTTON_B" in spec,
         "existing six-button profile bindings are missing")
    print("PASS: selected-slot keyboard controls and DualSense L3+R3 route to the save UI")


if __name__ == "__main__":
    main()
