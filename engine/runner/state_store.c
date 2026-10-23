#include "state_store.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define STATE_SEP '\\'
#else
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#define STATE_SEP '/'
#endif

static int is_sep(char c) { return c == '/' || c == '\\'; }

static int make_one_dir(const char *path)
{
#ifdef _WIN32
    DWORD attr;
    if (CreateDirectoryA(path, NULL)) return 1;
    if (GetLastError() != ERROR_ALREADY_EXISTS) return 0;
    attr = GetFileAttributesA(path);
    return attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY);
#else
    struct stat st;
    if (mkdir(path, 0700) == 0) return 1;
    if (errno != EEXIST || stat(path, &st) != 0) return 0;
    return S_ISDIR(st.st_mode);
#endif
}

static int make_dirs(const char *path)
{
    char tmp[1024];
    size_t n = strlen(path), start = 0;
    if (!n || n >= sizeof tmp) return 0;
    memcpy(tmp, path, n + 1);
#ifdef _WIN32
    if (n >= 3 && tmp[1] == ':') start = 3;
#else
    if (tmp[0] == '/') start = 1;
#endif
    for (size_t i = start; i <= n; ++i) {
        if (i != n && !is_sep(tmp[i])) continue;
        char saved = tmp[i];
        tmp[i] = '\0';
        if (tmp[0] && !make_one_dir(tmp)) return 0;
        tmp[i] = saved;
    }
    return 1;
}

static int path_exists(const char *path)
{
#ifdef _WIN32
    return GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
#else
    struct stat st;
    return stat(path, &st) == 0;
#endif
}

static int valid_app_id(const char *id)
{
    if (!id || !*id) return 0;
    for (const unsigned char *p = (const unsigned char *)id; *p; ++p)
        if (!( (*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
               (*p >= '0' && *p <= '9') || *p == '-' || *p == '_' ))
            return 0;
    return 1;
}

static int append_path(char *out, size_t cap, const char *base, const char *tail)
{
    size_t n;
    if (!out || !cap || !base || !tail) return 0;
    n = strlen(base);
    if (n && is_sep(base[n - 1]))
        return snprintf(out, cap, "%s%s", base, tail) < (int)cap;
    return snprintf(out, cap, "%s%c%s", base, STATE_SEP, tail) < (int)cap;
}

int genesis_state_store_init_at(const char *root, const char *app_id,
                                char *out, size_t out_cap)
{
    char app[1024];
    if (!root || !*root || !valid_app_id(app_id) || !out || out_cap < 2)
        return 0;
    if (!append_path(app, sizeof app, root, app_id)) return 0;
    if (!make_dirs(app) || !append_path(out, out_cap, app, "states") ||
        !make_dirs(out)) return 0;
    size_t n = strlen(out);
    if (n + 1 >= out_cap) return 0;
    if (!n || !is_sep(out[n - 1])) { out[n] = STATE_SEP; out[n + 1] = '\0'; }
    return 1;
}

int genesis_state_store_init(const char *exe_dir, const char *app_id,
                             char *out, size_t out_cap)
{
    const char *root = NULL;
#ifdef _WIN32
    root = getenv("LOCALAPPDATA");
    if (!root || !*root) root = getenv("APPDATA");
#else
    root = getenv("XDG_DATA_HOME");
    if (!root || !*root) {
        const char *home = getenv("HOME");
        static char home_data[1024];
        if (home && *home && snprintf(home_data, sizeof home_data,
                                      "%s/.local/share", home) < (int)sizeof home_data)
            root = home_data;
    }
#endif
    if (root && *root && genesis_state_store_init_at(root, app_id, out, out_cap))
        return 1;
    /* Last-resort portability path. The caller logs this fallback because it
     * is not shared between packages. Normal Windows installs use LOCALAPPDATA. */
    if (exe_dir && *exe_dir && genesis_state_store_init_at(exe_dir, app_id, out, out_cap))
        return 2;
    return 0;
}

int genesis_state_store_resolve(const char *state_dir, const char *name,
                                char *out, size_t out_cap)
{
    if (!name || !*name || !out || !out_cap) return 0;
    return append_path(out, out_cap, state_dir, name);
}

int genesis_state_store_slot_path(const char *state_dir, int slot, int thumb,
                                  char *out, size_t out_cap)
{
    char name[48];
    if (slot < 1 || slot > GENESIS_STATE_SLOT_COUNT) return 0;
    snprintf(name, sizeof name, "native_save_%d.bin%s", slot,
             thumb ? ".thumb" : "");
    return genesis_state_store_resolve(state_dir, name, out, out_cap);
}

static int file_magic_supported(const char *path)
{
    static const char *const magics[] = { "GROWNS2\0", "GROWNS3\0", "GRHOST2\0" };
    char magic[8];
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    int ok = fread(magic, 1, sizeof magic, f) == sizeof magic;
    fclose(f);
    if (!ok) return 0;
    for (size_t i = 0; i < sizeof magics / sizeof magics[0]; ++i)
        if (!memcmp(magic, magics[i], sizeof magic)) return 1;
    return 0;
}

static int files_equal(const char *a, const char *b)
{
    FILE *fa = fopen(a, "rb"), *fb = fopen(b, "rb");
    unsigned char ba[4096], bb[4096];
    int equal = 0;
    if (!fa || !fb) goto done;
    for (;;) {
        size_t na = fread(ba, 1, sizeof ba, fa), nb = fread(bb, 1, sizeof bb, fb);
        if (na != nb || memcmp(ba, bb, na)) break;
        if (na < sizeof ba) { equal = !ferror(fa) && !ferror(fb); break; }
    }
done:
    if (fa) fclose(fa);
    if (fb) fclose(fb);
    return equal;
}

static int copy_new_file(const char *src, const char *dst)
{
    char tmp[1200];
#ifdef _WIN32
    unsigned long pid = GetCurrentProcessId();
#else
    unsigned long pid = (unsigned long)getpid();
#endif
    snprintf(tmp, sizeof tmp, "%s.import.%lu.tmp", dst, pid);
    FILE *in = fopen(src, "rb"), *out = NULL;
    unsigned char buf[8192];
    int ok = 0;
    if (!in) return 0;
    out = fopen(tmp, "wb");
    if (!out) { fclose(in); return 0; }
    for (;;) {
        size_t n = fread(buf, 1, sizeof buf, in);
        if (n && fwrite(buf, 1, n, out) != n) goto done;
        if (n < sizeof buf) {
            if (ferror(in)) goto done;
            break;
        }
    }
    if (fflush(out) || ferror(out)) goto done;
    if (fclose(out)) { out = NULL; goto done; }
    out = NULL;
#ifdef _WIN32
    ok = MoveFileExA(tmp, dst, MOVEFILE_WRITE_THROUGH) != 0;
#else
    ok = link(tmp, dst) == 0;
    (void)unlink(tmp);
#endif
done:
    if (out) fclose(out);
    fclose(in);
    if (!ok) remove(tmp);
    return ok;
}

int genesis_state_store_migrate(const char *package_dir, const char *state_dir,
                                int *copied_count)
{
    int copied = 0;
    if (copied_count) *copied_count = 0;
    if (!package_dir || !state_dir || !*package_dir || !*state_dir) return 0;
    for (int source_slot = 1; source_slot <= GENESIS_STATE_SLOT_COUNT; ++source_slot) {
        char src[1200], dst[1200], other[1200];
        if (!genesis_state_store_slot_path(package_dir, source_slot, 0,
                                           src, sizeof src) || !file_magic_supported(src))
            continue;
        /* Idempotence: if this exact legacy file was already imported under a
         * different slot after a name conflict, do not duplicate it again. */
        int duplicate = 0;
        for (int slot = 1; slot <= GENESIS_STATE_SLOT_COUNT; ++slot) {
            if (genesis_state_store_slot_path(state_dir, slot, 0, other, sizeof other) &&
                files_equal(src, other)) { duplicate = 1; break; }
        }
        if (duplicate) continue;

        int destination_slot = 0;
        if (genesis_state_store_slot_path(state_dir, source_slot, 0, dst, sizeof dst) &&
            !path_exists(dst)) {
            destination_slot = source_slot;
        } else {
            for (int slot = 1; slot <= GENESIS_STATE_SLOT_COUNT; ++slot) {
                if (genesis_state_store_slot_path(state_dir, slot, 0, other, sizeof other) &&
                    !path_exists(other)) { destination_slot = slot; break; }
            }
        }
        if (!destination_slot || !genesis_state_store_slot_path(state_dir,
                destination_slot, 0, dst, sizeof dst)) continue;
        if (copy_new_file(src, dst)) {
            ++copied;
            fprintf(stderr, "[SAVE] imported package-local slot %d as persistent slot %d; source retained\n",
                    source_slot, destination_slot);
        }
    }
    if (copied_count) *copied_count = copied;
    return 1;
}
