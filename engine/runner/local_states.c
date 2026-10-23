/* Whole-machine local rewind and a visual browser for native_save_N.bin.
 * rbengine owns each snapshot blob; the runner owns presentation metadata. */
#include "local_states.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rb_state.h"
#include "overlay_draw.h"
#include "retcomm_rbengine/snap_ring.h"
#include "state_store.h"
#include "state_slots.h"

int runner_save_state_file(const char *path);
int runner_load_state_file(const char *path);
int runner_state_file_status(const char *path); /* 0 empty, 1 valid, 2 invalid */

#define THUMB_W 128
#define THUMB_H 90
#define PANEL_W 640
#define PANEL_H 448
#define SLOT_COUNT GENESIS_STATE_SLOT_COUNT

typedef struct LocalSnap {
    uint32_t tick;
    uint32_t thumb[THUMB_W * THUMB_H];
} LocalSnap;

static RbeSnapRing *s_ring;
static LocalSnap *s_meta;
static int s_depth, s_interval, s_count, s_head, s_cadence, s_mode, s_selected;
static uint32_t s_tick;
static char s_dir[512];
static uint32_t s_live_thumb[THUMB_W * THUMB_H];
static uint32_t s_panel[PANEL_W * PANEL_H];
static uint32_t s_slot_thumb[SLOT_COUNT][THUMB_W * THUMB_H];
static int s_slot_has_thumb[SLOT_COUNT], s_slot_status[SLOT_COUNT];
static int s_selected_slot = 1;
static char s_status[64];

static int clamp(int n, int lo, int hi) { return n < lo ? lo : n > hi ? hi : n; }

static void refresh_slots(void);

static void path_for_slot(int slot, int thumb, char *out, size_t cap)
{
    if (!genesis_state_store_slot_path(s_dir, slot, thumb, out, cap))
        if (cap) out[0] = '\0';
}

void genesis_local_states_clear(void)
{
    if (s_ring) rbe_snap_ring_clear(s_ring);
    s_count = s_head = s_cadence = 0;
    s_tick = 0;
}

void genesis_local_states_shutdown(void)
{
    if (s_ring) fprintf(stderr, "[rewind] shutdown: %d snapshots retained\n", s_count);
    rbe_snap_ring_destroy(s_ring);
    s_ring = NULL;
    free(s_meta);
    s_meta = NULL;
    s_depth = s_count = s_head = s_mode = 0;
}

void genesis_local_states_configure(const char *save_dir, int enabled,
                                    int depth, int interval)
{
    const char *env;
    genesis_local_states_shutdown();
    snprintf(s_dir, sizeof s_dir, "%s", save_dir ? save_dir : "");
    env = getenv("GENESISRECOMP_REWIND");
    if (env && *env == '0') enabled = 0;
    env = getenv("GENESISRECOMP_REWIND_DEPTH");
    if (env && *env) depth = atoi(env);
    env = getenv("GENESISRECOMP_REWIND_INTERVAL");
    if (env && *env) interval = atoi(env);
    s_depth = clamp(depth, 4, 240);
    s_interval = clamp(interval, 1, 60);
    refresh_slots();
    for (int i = 0; i < SLOT_COUNT; ++i) {
        if (s_slot_status[i] == 0) { s_selected_slot = i + 1; break; }
    }
    fprintf(stderr, "[SAVE] selected slot %d (10 persistent slots)\n", s_selected_slot);
    if (!enabled) return;
    s_ring = rbe_snap_ring_create((uint32_t)s_depth);
    s_meta = (LocalSnap *)calloc((size_t)s_depth, sizeof *s_meta);
    if (!s_ring || !s_meta) {
        fprintf(stderr, "[rewind] allocation failed; disabled\n");
        genesis_local_states_shutdown();
        return;
    }
    fprintf(stderr, "[rewind] %d snapshots, interval %d (%.1f seconds)\n",
            s_depth, s_interval, (double)s_depth * s_interval / 60.0);
}

static LocalSnap *snap_at(int selected)
{
    if (!s_meta || selected < 0 || selected >= s_count) return NULL;
    return &s_meta[(s_head - 1 - selected + s_depth) % s_depth];
}

static void refresh_slots(void)
{
    for (int i = 0; i < SLOT_COUNT; ++i) {
        char path[640];
        FILE *f;
        path_for_slot(i + 1, 0, path, sizeof path);
        f = fopen(path, "rb");
        if (f) fclose(f);
        s_slot_status[i] = runner_state_file_status(path);
        path_for_slot(i + 1, 1, path, sizeof path);
        f = fopen(path, "rb");
        s_slot_has_thumb[i] = 0;
        if (f) {
            char magic[8];
            if (fread(magic, 1, 8, f) == 8 &&
                !memcmp(magic, "GTHUMB1", 8) &&
                fread(s_slot_thumb[i], sizeof(uint32_t), THUMB_W * THUMB_H, f)
                    == THUMB_W * THUMB_H)
                s_slot_has_thumb[i] = 1;
            fclose(f);
        }
    }
}

void genesis_local_states_slot_saved(int slot)
{
    if (slot < 1 || slot > SLOT_COUNT) return;
    char path[640];
    path_for_slot(slot, 1, path, sizeof path);
    FILE *f = fopen(path, "wb");
    if (f) {
        (void)fwrite("GTHUMB1", 1, 8, f);
        (void)fwrite(s_live_thumb, sizeof(uint32_t), THUMB_W * THUMB_H, f);
        fclose(f);
    }
    refresh_slots();
}

void genesis_local_states_note_frame(const uint32_t *pixels, int stride,
                                     int width, int height)
{
    if (!pixels || stride < width || width <= 0 || height <= 0 || s_mode)
        return;
    for (int y = 0; y < THUMB_H; ++y)
        for (int x = 0; x < THUMB_W; ++x)
            s_live_thumb[y * THUMB_W + x] =
                pixels[(size_t)(y * height / THUMB_H) * (size_t)stride +
                       x * width / THUMB_W] | 0xFF000000u;
    if (!s_ring || ++s_cadence < s_interval) return;
    s_cadence = 0;
    size_t cap = genesis_rb_bound();
    uint8_t *blob = (uint8_t *)malloc(cap);
    if (!blob) return;
    size_t n = genesis_rb_save(blob, cap);
    if (!n || !rbe_snap_ring_store(s_ring, ++s_tick, blob, n)) {
        free(blob);
        return;
    }
    if (!s_count)
        fprintf(stderr, "[rewind] snapshot size %zu bytes; full ring about %.1f MiB\n",
                n, (double)n * s_depth / (1024.0 * 1024.0));
    LocalSnap *snap = &s_meta[s_head];
    snap->tick = s_tick;
    memcpy(snap->thumb, s_live_thumb, sizeof snap->thumb);
    s_head = (s_head + 1) % s_depth;
    if (s_count < s_depth) ++s_count;
}

int genesis_local_states_open_rewind(void)
{
    if (!s_ring || s_count < 2 || s_mode) return 0;
    s_selected = 0;
    s_mode = 1;
    return 1;
}

int genesis_local_states_open_menu(void)
{
    if (s_mode) return 0;
    refresh_slots();
    s_selected = s_selected_slot - 1;
    s_status[0] = 0;
    s_mode = 2;
    return 1;
}

int genesis_local_states_is_open(void) { return s_mode; }
int genesis_local_states_selected_slot(void) { return s_selected_slot; }

void genesis_local_states_move_menu(int dx, int dy)
{
    if (s_mode != 2) return;
    s_selected_slot = genesis_state_slot_move_grid(s_selected_slot, dx, dy);
    s_selected = s_selected_slot - 1;
}

int genesis_local_states_cycle_slot(int delta)
{
    s_selected_slot = genesis_state_slot_cycle(s_selected_slot, delta);
    if (s_mode == 2) s_selected = s_selected_slot - 1;
    fprintf(stderr, "[SAVE] selected slot %d\n", s_selected_slot);
    return s_selected_slot;
}

void genesis_local_states_select_slot(int slot)
{
    if (slot < 1 || slot > SLOT_COUNT) return;
    s_selected_slot = slot;
    if (s_mode == 2) s_selected = slot - 1;
    fprintf(stderr, "[SAVE] selected slot %d\n", s_selected_slot);
}

void genesis_local_states_move(int direction)
{
    if (!s_mode) return;
    int max = s_mode == 1 ? s_count : SLOT_COUNT;
    int delta = s_mode == 1 ? -direction : direction;
    s_selected = clamp(s_selected + delta, 0, max - 1);
}

void genesis_local_states_cancel(void) { s_mode = 0; s_selected = 0; }

int genesis_local_states_accept(void)
{
    if (s_mode == 1) {
        LocalSnap *snap = snap_at(s_selected);
        if (!snap) return 0;
        size_t len = 0;
        const uint8_t *blob = rbe_snap_ring_peek(s_ring, snap->tick, &len);
        if (!blob || !genesis_rb_load(blob, len)) return 0;
        rbe_snap_ring_drop_after(s_ring, snap->tick);
        s_tick = snap->tick;
        s_head = (s_head - s_selected + s_depth) % s_depth;
        s_count -= s_selected;
        s_cadence = 0;
        genesis_local_states_cancel();
        return 1;
    }
    if (s_mode == 2 && s_slot_status[s_selected] == 1) {
        char path[640];
        path_for_slot(s_selected + 1, 0, path, sizeof path);
        if (runner_load_state_file(path)) {
            genesis_local_states_cancel();
            return 1;
        }
        snprintf(s_status, sizeof s_status, "LOAD FAILED");
    } else if (s_mode == 2 && s_slot_status[s_selected] == 2) {
        snprintf(s_status, sizeof s_status, "SAVE IS INVALID OR INCOMPATIBLE");
    }
    return 0;
}

int genesis_local_states_save(void)
{
    if (s_mode != 2) return 0;
    char path[640];
    path_for_slot(s_selected + 1, 0, path, sizeof path);
    if (!runner_save_state_file(path)) {
        snprintf(s_status, sizeof s_status, "SAVE FAILED");
        return 0;
    }
    genesis_local_states_slot_saved(s_selected + 1);
    snprintf(s_status, sizeof s_status, "SLOT %d SAVED", s_selected + 1);
    return 1;
}

static void rect(int x, int y, int w, int h, uint32_t c)
{ gen_ovl_fill_rect(s_panel, PANEL_W, PANEL_H, x, y, w, h, c); }
static void border(int x, int y, int w, int h, uint32_t c)
{ gen_ovl_stroke_rect(s_panel, PANEL_W, PANEL_H, x, y, w, h, c); }
static void label(int x, int y, const char *s, uint32_t c, int scale)
{ gen_ovl_draw_text(s_panel, PANEL_W, PANEL_H, x, y, s, c, scale); }
static void thumb(int x, int y, int w, int h, const uint32_t *src)
{
    for (int yy = 0; yy < h; ++yy)
        for (int xx = 0; xx < w; ++xx)
            s_panel[(y + yy) * PANEL_W + x + xx] =
                src[(yy * THUMB_H / h) * THUMB_W + xx * THUMB_W / w];
}

int genesis_local_states_overlay(const uint32_t **pixels, int *width, int *height)
{
    if (!s_mode) return 0;
    memset(s_panel, 0, sizeof s_panel);
    const uint32_t gold = 0xFFF6C66Bu, white = 0xFFF2F1EAu;
    if (s_mode == 2) {
        rect(0, 0, PANEL_W, PANEL_H, 0xFF101A31u);
        rect(0, 0, PANEL_W, 9, 0xFFB66937u);
        label(22, 20, "SAVE STATES", gold, 2);
        label(23, 44, "L3+R3 OPEN | DPAD/ARROWS SELECT | A/ENTER LOAD | X/S SAVE", white, 1);
        for (int i = 0; i < SLOT_COUNT; ++i) {
            int col = i % 2, row = i / 2;
            int x = 17 + col * 305, y = 78 + row * 69;
            rect(x, y, 294, 63, 0xFF23324Cu);
            border(x, y, 294, 63, i == s_selected ? gold : 0xFF556481u);
            if (s_slot_status[i] == 1 && s_slot_has_thumb[i])
                thumb(x + 5, y + 5, 82, 53, s_slot_thumb[i]);
            else {
                rect(x + 5, y + 5, 82, 53, 0xFF17243Cu);
                label(x + 17, y + 27, s_slot_status[i] == 1 ? "SAVED" :
                      s_slot_status[i] == 2 ? "INVALID" : "EMPTY", white, 1);
            }
            char name[20];
            snprintf(name, sizeof name, "SLOT %d", i + 1);
            label(x + 95, y + 10, name, gold, 1);
            label(x + 95, y + 29, s_slot_status[i] == 1 ? "VALID - LOAD" :
                  s_slot_status[i] == 2 ? "INCOMPATIBLE" : "EMPTY - SAVE", white, 1);
            if (i == s_selected) label(x + 95, y + 47, "SELECTED", gold, 1);
        }
        if (s_status[0]) label(22, 424, s_status, gold, 1);
    } else {
        rect(0, 276, PANEL_W, 172, 0xEC101A31u);
        rect(0, 276, PANEL_W, 3, gold);
        label(20, 288, "REWIND", gold, 2);
        char info[64];
        snprintf(info, sizeof info, "%.1F SECONDS BACK  |  LEFT OLDER  RIGHT NEWER",
                 (double)s_selected * s_interval / 60.0);
        label(20, 313, info, white, 1);
        int shown = s_count < 4 ? s_count : 4;
        for (int i = 0; i < shown; ++i) {
            int index = clamp(s_selected + (shown - 1 - i), 0, s_count - 1);
            LocalSnap *snap = snap_at(index);
            int x = 20 + i * 153;
            if (snap) thumb(x, 334, 141, 99, snap->thumb);
            border(x, 334, 141, 99, index == s_selected ? gold : 0xFF7483A0u);
        }
        label(20, 436, "L2 OPEN  |  A/ENTER RESTORE  B/ESC CANCEL", white, 1);
    }
    *pixels = s_panel;
    *width = PANEL_W;
    *height = PANEL_H;
    return 1;
}
