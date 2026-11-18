/*
 * sway-tablet-gestures - manager for lisgd touchscreen gestures.
 *
 * A 1:1 reimplementation of the Python daemon of the same name.  It keeps
 * lisgd alive with the right device, orientation and gesture list, and
 * restarts it whenever the device, output transform, orientation override or
 * gestures.json changes.
 *
 * CLI:
 *   start | stop | toggle | status | gestures-export | gestures-import | _daemon
 *
 * Environment:
 *   OUTPUT_NAME / GESTURE_OUTPUT   sway output to read transform/geometry from
 *   GESTURE_DEVICE / TOUCH_DEVICE  touch device override (must be a touch dev)
 */
#define _GNU_SOURCE

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <pwd.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include <jansson.h>

#define LOGFILE "/tmp/sway-tablet-gestures.log"

/* Config paths, resolved from $HOME in init_paths(). */
static char *CFG;
static char *DISABLED;
static char *PIDFILE;
static char *ORIENT_FILE;
static char *GEST_FILE;

/* Absolute path to this executable (used by `start` to spawn `_daemon`). */
static char *g_self;

/* Set by SIGTERM/SIGINT; the daemon loop exits on the next check. */
static volatile sig_atomic_t g_stop;

/* ---- small utilities -------------------------------------------------- */

static int64_t now_ms(void)
{
    struct timespec ts;

    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void sleep_ms(int ms)
{
    struct timespec ts;

    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (long)(ms % 1000) * 1000000L;
    while (nanosleep(&ts, &ts) < 0 && errno == EINTR && !g_stop)
        ;
}

static void on_signal(int sig)
{
    (void)sig;
    g_stop = 1;
}

static char *join_path(const char *a, const char *b)
{
    char *out = NULL;

    if (asprintf(&out, "%s/%s", a, b) < 0)
        return NULL;
    return out;
}

static void init_paths(void)
{
    const char *home = getenv("HOME");
    struct passwd *pw;

    if (!home || !*home) {
        pw = getpwuid(getuid());
        home = pw ? pw->pw_dir : "/";
    }

    CFG = join_path(home, ".config/swaytablet");
    if (!CFG)
        exit(1);
    DISABLED = join_path(CFG, "gestures-disabled");
    PIDFILE = join_path(CFG, "gestures-manager.pid");
    ORIENT_FILE = join_path(CFG, "gestures-orient.json");
    GEST_FILE = join_path(CFG, "gestures.json");
    if (!DISABLED || !PIDFILE || !ORIENT_FILE || !GEST_FILE)
        exit(1);
}

static void init_self(const char *argv0)
{
    char buf[PATH_MAX];
    ssize_t n;

    n = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
    if (n > 0) {
        buf[n] = '\0';
        g_self = strdup(buf);
    } else if (argv0) {
        g_self = realpath(argv0, NULL);
    }
}

static void log_msg(const char *fmt, ...)
{
    FILE *f;
    time_t t;
    struct tm tm;
    va_list ap;

    f = fopen(LOGFILE, "a");
    if (!f)
        return;

    t = time(NULL);
    localtime_r(&t, &tm);
    fprintf(f, "%02d:%02d:%02d ", tm.tm_hour, tm.tm_min, tm.tm_sec);
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

static char *read_stdin(void)
{
    size_t cap = 4096;
    size_t len = 0;
    char *buf = malloc(cap);

    if (!buf)
        return NULL;

    for (;;) {
        size_t r;

        if (len + 4096 > cap) {
            char *tmp = realloc(buf, cap * 2);

            if (!tmp) {
                free(buf);
                return NULL;
            }
            buf = tmp;
            cap *= 2;
        }
        r = fread(buf + len, 1, cap - len - 1, stdin);
        len += r;
        if (r == 0) {
            if (feof(stdin))
                break;
            if (ferror(stdin)) {
                free(buf);
                return NULL;
            }
        }
    }
    buf[len] = '\0';
    return buf;
}

/* shutil.which(): first PATH entry holding an executable regular file. */
static char *which(const char *name)
{
    const char *path = getenv("PATH");
    char *copy;
    char *save = NULL;
    char *dir;
    char *found = NULL;

    if (!path)
        path = "/usr/local/bin:/usr/bin:/bin";
    copy = strdup(path);
    if (!copy)
        return NULL;

    for (dir = strtok_r(copy, ":", &save); dir;
         dir = strtok_r(NULL, ":", &save)) {
        char *cand;
        struct stat st;

        if (asprintf(&cand, "%s/%s", *dir ? dir : ".", name) < 0)
            continue;
        if (stat(cand, &st) == 0 && S_ISREG(st.st_mode) &&
            access(cand, X_OK) == 0) {
            found = cand;
            break;
        }
        free(cand);
    }
    free(copy);
    return found;
}

/* Run a command and capture stdout. Returns 0 only on exit status 0. */
static int run_capture(char *const argv[], int timeout_ms, char **out)
{
    int pfd[2];
    pid_t pid;
    int status = 0;
    int flags;
    char *buf;
    size_t cap = 4096;
    size_t len = 0;
    int64_t deadline;
    bool eof = false;

    *out = NULL;
    if (pipe(pfd) != 0)
        return -1;

    pid = fork();
    if (pid < 0) {
        close(pfd[0]);
        close(pfd[1]);
        return -1;
    }
    if (pid == 0) {
        int devnull;

        close(pfd[0]);
        dup2(pfd[1], STDOUT_FILENO);
        close(pfd[1]);
        devnull = open("/dev/null", O_WRONLY);
        if (devnull >= 0) {
            dup2(devnull, STDERR_FILENO);
            if (devnull > STDERR_FILENO)
                close(devnull);
        }
        execvp(argv[0], argv);
        _exit(127);
    }

    close(pfd[1]);
    flags = fcntl(pfd[0], F_GETFL, 0);
    if (flags >= 0)
        fcntl(pfd[0], F_SETFL, flags | O_NONBLOCK);

    buf = malloc(cap);
    if (!buf) {
        close(pfd[0]);
        while (waitpid(pid, &status, 0) < 0 && errno == EINTR)
            ;
        return -1;
    }

    deadline = now_ms() + timeout_ms;
    while (!eof) {
        int64_t remaining = deadline - now_ms();
        struct pollfd pfd_poll;
        int pr;

        if (remaining < 0)
            remaining = 0;
        pfd_poll.fd = pfd[0];
        pfd_poll.events = POLLIN;
        pfd_poll.revents = 0;

        pr = poll(&pfd_poll, 1, (int)remaining);
        if (pr < 0) {
            if (errno == EINTR)
                continue;
            break;
        }
        if (pr == 0) {
            kill(pid, SIGKILL);
            break;
        }

        for (;;) {
            ssize_t r;

            if (len + 4096 > cap) {
                char *tmp = realloc(buf, cap * 2);

                if (!tmp) {
                    eof = true;
                    break;
                }
                buf = tmp;
                cap *= 2;
            }
            r = read(pfd[0], buf + len, cap - len - 1);
            if (r > 0) {
                len += (size_t)r;
                continue;
            }
            if (r == 0) {
                eof = true;
                break;
            }
            if (errno == EINTR)
                continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK)
                break;
            eof = true;
            break;
        }
        if (now_ms() > deadline) {
            kill(pid, SIGKILL);
            break;
        }
    }

    close(pfd[0]);
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR)
        ;
    buf[len] = '\0';

    if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
        *out = buf;
        return 0;
    }
    free(buf);
    return -1;
}

static char *trim_inplace(char *s)
{
    char *end;

    while (*s && isspace((unsigned char)*s))
        s++;
    end = s + strlen(s);
    while (end > s && isspace((unsigned char)end[-1]))
        *--end = '\0';
    return s;
}

/* ---- process helpers -------------------------------------------------- */

static bool comm_is(pid_t pid, const char *name)
{
    char path[64];
    char buf[64];
    ssize_t n;
    size_t len;
    int fd;

    snprintf(path, sizeof(path), "/proc/%d/comm", (int)pid);
    fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return false;
    n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0)
        return false;
    buf[n] = '\0';
    len = strlen(buf);
    while (len > 0 && (buf[len - 1] == '\n' || buf[len - 1] == '\r' ||
                       buf[len - 1] == ' ' || buf[len - 1] == '\t'))
        buf[--len] = '\0';
    return strcmp(buf, name) == 0;
}

/* pkill -x lisgd */
static void kill_lisgd(void)
{
    DIR *dir;
    struct dirent *ent;
    pid_t self = getpid();

    dir = opendir("/proc");
    if (!dir)
        return;

    while ((ent = readdir(dir)) != NULL) {
        pid_t pid;

        if (!isdigit((unsigned char)ent->d_name[0]))
            continue;
        pid = (pid_t)atoi(ent->d_name);
        if (pid == self)
            continue;
        if (comm_is(pid, "lisgd"))
            kill(pid, SIGTERM);
    }
    closedir(dir);
}

/* pgrep -x lisgd */
static bool lisgd_running(void)
{
    DIR *dir;
    struct dirent *ent;
    bool found = false;

    dir = opendir("/proc");
    if (!dir)
        return false;

    while (!found && (ent = readdir(dir)) != NULL) {
        pid_t pid;

        if (!isdigit((unsigned char)ent->d_name[0]))
            continue;
        pid = (pid_t)atoi(ent->d_name);
        if (comm_is(pid, "lisgd"))
            found = true;
    }
    closedir(dir);
    return found;
}

/* Strict pidfile parse: returns -1 for missing or non-numeric content. */
static int read_pidfile(void)
{
    FILE *f;
    char buf[64];
    char *end;
    long value;

    f = fopen(PIDFILE, "r");
    if (!f)
        return -1;
    if (!fgets(buf, sizeof(buf), f)) {
        fclose(f);
        return -1;
    }
    fclose(f);

    errno = 0;
    value = strtol(buf, &end, 10);
    if (errno != 0 || end == buf)
        return -1;
    while (*end && isspace((unsigned char)*end))
        end++;
    if (*end != '\0')
        return -1;
    if (value <= 0 || value > INT_MAX)
        return -1;
    return (int)value;
}

static void kill_manager(bool except_self)
{
    if (access(PIDFILE, F_OK) == 0) {
        int pid = read_pidfile();

        if (pid > 0 && !(except_self && pid == (int)getpid()))
            kill(pid, SIGTERM);
        unlink(PIDFILE);
    }
}

static bool is_disabled(void)
{
    return access(DISABLED, F_OK) == 0;
}

static void mkdir_p(const char *path)
{
    char tmp[PATH_MAX];
    char *p;

    snprintf(tmp, sizeof(tmp), "%s", path);
    for (p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(tmp, 0777);
            *p = '/';
        }
    }
    mkdir(tmp, 0777);
}

/* ---- gesture JSON ----------------------------------------------------- */

static const char *const DIRS[] = {
    "LR", "RL", "DU", "UD", "DLUR", "DRUL", "URDL", "ULDR", NULL
};
static const char *const EDGES[] = {
    "*", "N", "L", "R", "T", "B", "TL", "TR", "BL", "BR", NULL
};
static const char *const DISTS[] = { "*", "S", "M", "L", NULL };
static const char *const MODES[] = { "R", "P", NULL };

static const char *const DIR_NAMES[] = {
    "left\u2192right", "right\u2192left", "down\u2192up", "up\u2192down",
    "bottom-left\u2192top-right", "bottom-right\u2192top-left",
    "top-right\u2192bottom-left", "top-left\u2192bottom-right"
};
static const char *const EDGE_NAMES[] = {
    "anywhere", "anywhere", "left edge", "right edge", "top edge",
    "bottom edge", "top-left corner", "top-right corner",
    "bottom-left corner", "bottom-right corner"
};
static const char *const DIST_NAMES[] = {
    "any distance", "short", "medium", "long"
};

static const char *name_for(const char *key, const char *const *keys,
                            const char *const *names)
{
    int i;

    for (i = 0; keys[i]; i++)
        if (strcmp(key, keys[i]) == 0)
            return names[i];
    return key;
}

static bool str_in(const char *s, const char *const *list)
{
    int i;

    for (i = 0; list[i]; i++)
        if (strcmp(s, list[i]) == 0)
            return true;
    return false;
}

static long fingers_value(const json_t *g, bool *ok)
{
    json_t *f = json_object_get(g, "fingers");

    if (json_is_integer(f)) {
        *ok = true;
        return (long)json_integer_value(f);
    }
    /* Python's isinstance(True, int) is True. */
    if (json_is_boolean(f)) {
        *ok = true;
        return json_is_true(f) ? 1 : 0;
    }
    *ok = false;
    return 0;
}

static bool validate_gesture(const json_t *g)
{
    json_t *v;
    const char *s;
    bool ok;
    long fingers;

    if (!json_is_object(g))
        return false;

    fingers = fingers_value(g, &ok);
    if (!ok || fingers < 1)
        return false;

    v = json_object_get(g, "dir");
    s = json_string_value(v);
    if (!s || !str_in(s, DIRS))
        return false;

    v = json_object_get(g, "edge");
    s = json_string_value(v);
    if (!s || !str_in(s, EDGES))
        return false;

    v = json_object_get(g, "distance");
    s = json_string_value(v);
    if (!s || !str_in(s, DISTS))
        return false;

    v = json_object_get(g, "mode");
    s = json_string_value(v);
    if (!s || !str_in(s, MODES))
        return false;

    v = json_object_get(g, "cmd");
    s = json_string_value(v);
    if (!s)
        return false;
    for (; *s; s++)
        if (!isspace((unsigned char)*s))
            return true;
    return false;
}

static void annotate(json_t *g)
{
    const char *dir;
    const char *edge;
    const char *dist;
    char buf[1024];
    bool ok;
    long fingers;

    if (json_object_get(g, "desc") != NULL)
        return;

    fingers = fingers_value(g, &ok);
    if (!ok)
        fingers = 1;

    dir = json_string_value(json_object_get(g, "dir"));
    edge = json_string_value(json_object_get(g, "edge"));
    dist = json_string_value(json_object_get(g, "distance"));
    if (!dir)
        dir = "";
    if (!edge)
        edge = "";
    if (!dist)
        dist = "";

    snprintf(buf, sizeof(buf), "%ld-finger %s, %s, %s", fingers,
             name_for(dir, DIRS, DIR_NAMES), name_for(edge, EDGES, EDGE_NAMES),
             name_for(dist, DISTS, DIST_NAMES));
    json_object_set_new(g, "desc", json_string(buf));
}

static void add_gesture(json_t *arr, int fingers, const char *dir,
                        const char *edge, const char *distance,
                        const char *mode, const char *cmd)
{
    json_t *g = json_object();

    if (!g)
        return;
    json_object_set_new(g, "fingers", json_integer(fingers));
    json_object_set_new(g, "dir", json_string(dir));
    json_object_set_new(g, "edge", json_string(edge));
    json_object_set_new(g, "distance", json_string(distance));
    json_object_set_new(g, "mode", json_string(mode));
    json_object_set_new(g, "cmd", json_string(cmd));
    annotate(g);
    json_array_append_new(arr, g);
}

static json_t *make_defaults(void)
{
    json_t *arr = json_array();

    if (!arr)
        return NULL;
    add_gesture(arr, 3, "LR", "*", "*", "R", "swaymsg workspace number 1");
    add_gesture(arr, 3, "RL", "*", "*", "R", "swaymsg workspace number 2");
    add_gesture(arr, 3, "UD", "*", "*", "R", "swaymsg kill");
    add_gesture(arr, 3, "DU", "*", "*", "R", "swaymsg fullscreen toggle");
    return arr;
}

/* Read gestures.json, writing defaults on first run / invalid JSON. */
static json_t *load_gestures(void)
{
    json_error_t err;
    json_t *root;
    json_t *result;
    size_t i;
    json_t *value;

    root = json_load_file(GEST_FILE, 0, &err);
    if (root && json_is_array(root)) {
        result = json_array();
        if (!result) {
            json_decref(root);
            return json_array();
        }
        json_array_foreach(root, i, value) {
            if (validate_gesture(value)) {
                annotate(value);
                json_array_append(result, value);
            }
        }
        json_decref(root);
        return result;
    }
    if (root)
        json_decref(root);

    result = make_defaults();
    if (!result)
        return json_array();
    json_dump_file(result, GEST_FILE, JSON_INDENT(2) | JSON_ENSURE_ASCII);
    return result;
}

/* Validate + annotate + write gestures.json. */
static void save_gestures(json_t *gestures)
{
    json_t *clean = json_array();
    size_t i;
    json_t *value;

    if (!clean)
        return;

    json_array_foreach(gestures, i, value) {
        json_t *copy;

        if (!validate_gesture(value))
            continue;
        copy = json_deep_copy(value);
        if (!copy)
            continue;
        annotate(copy);
        json_array_append_new(clean, copy);
    }

    json_dump_file(clean, GEST_FILE, JSON_INDENT(2) | JSON_ENSURE_ASCII);
    json_decref(clean);
}

/* ---- sway / device detection ----------------------------------------- */

static const char *output_name(void)
{
    const char *name = getenv("OUTPUT_NAME");

    if (name && *name)
        return name;
    name = getenv("GESTURE_OUTPUT");
    if (name && *name)
        return name;
    return "";
}

static char *sway_output_transform(void)
{
    char *out = NULL;
    char *argv[] = { "swaymsg", "-t", "get_outputs", NULL };
    json_t *root = NULL;
    const char *name;
    char *result = NULL;
    int pass;
    size_t i;
    json_t *o;

    if (run_capture(argv, 5000, &out) == 0) {
        json_error_t err;

        root = json_loads(out, 0, &err);
    }
    free(out);
    if (!root)
        return strdup("normal");

    name = output_name();
    for (pass = 0; pass < 2 && !result; pass++) {
        json_array_foreach(root, i, o) {
            json_t *headless_json;
            const char *on;
            const char *transform;

            if (pass == 0 && *name) {
                on = json_string_value(json_object_get(o, "name"));
                if (!on || strcmp(on, name) != 0)
                    continue;
            }

            headless_json = json_object_get(o, "headless");
            if (headless_json && json_is_true(headless_json))
                continue;
            on = json_string_value(json_object_get(o, "name"));
            if (!on || !*on)
                continue;

            transform = json_string_value(json_object_get(o, "transform"));
            if (!transform || !*transform)
                transform = "normal";
            result = strdup(transform);
            break;
        }
    }

    json_decref(root);
    return result ? result : strdup("normal");
}

/* Logical (post-rotation) screen size of the selected output. */
static bool output_geometry(int *gw, int *gh)
{
    char *out = NULL;
    char *argv[] = { "swaymsg", "-t", "get_outputs", NULL };
    json_t *root = NULL;
    const char *name;
    bool found = false;
    size_t i;
    json_t *o;

    if (run_capture(argv, 5000, &out) != 0) {
        free(out);
        return false;
    }
    {
        json_error_t err;

        root = json_loads(out, 0, &err);
    }
    free(out);
    if (!root)
        return false;

    name = output_name();
    json_array_foreach(root, i, o) {
        json_t *mode;
        json_t *w;
        json_t *h;

        if (*name) {
            const char *on = json_string_value(json_object_get(o, "name"));

            if (!on || strcmp(on, name) != 0)
                continue;
        }

        mode = json_object_get(o, "current_mode");
        if (!json_is_object(mode))
            continue;
        w = json_object_get(mode, "width");
        h = json_object_get(mode, "height");
        if (json_is_integer(w) && json_is_integer(h)) {
            long ww = (long)json_integer_value(w);
            long hh = (long)json_integer_value(h);

            if (ww && hh) {
                *gw = (int)ww;
                *gh = (int)hh;
                found = true;
                break;
            }
        }
    }

    json_decref(root);
    return found;
}

static bool is_touch_device(const char *dev)
{
    char *out = NULL;
    char *argv[] = { "libinput", "list-devices", NULL };
    char *cur = "";
    char *save = NULL;
    char *line;
    bool found = false;

    if (!dev || !*dev)
        return false;
    if (run_capture(argv, 8000, &out) != 0) {
        free(out);
        return false;
    }

    for (line = strtok_r(out, "\n", &save); line;
         line = strtok_r(NULL, "\n", &save)) {
        if (strncmp(line, "Kernel:", 7) == 0)
            cur = trim_inplace(line + 7);
        if (strcmp(cur, dev) == 0 && strstr(line, "Capabilities:") &&
            strstr(line, "touch")) {
            found = true;
            break;
        }
    }
    free(out);
    return found;
}

static char *detect_device(void)
{
    const char *dev;
    char *out = NULL;
    char *argv[] = { "libinput", "list-devices", NULL };
    char *result = NULL;
    char *cur = "";
    char *save = NULL;
    char *line;

    if (access("/dev/touchscreen-silead", F_OK) == 0)
        return strdup("/dev/touchscreen-silead");

    dev = getenv("GESTURE_DEVICE");
    if (!dev || !*dev)
        dev = getenv("TOUCH_DEVICE");
    if (!dev)
        dev = "";

    if (*dev && is_touch_device(dev))
        return strdup(dev);

    if (run_capture(argv, 8000, &out) == 0) {
        for (line = strtok_r(out, "\n", &save); line;
             line = strtok_r(NULL, "\n", &save)) {
            if (strncmp(line, "Kernel:", 7) == 0)
                cur = trim_inplace(line + 7);
            if (strstr(line, "Capabilities:") && strstr(line, "touch") &&
                *cur) {
                result = strdup(cur);
                break;
            }
        }
    }
    free(out);
    return result ? result : strdup("");
}

/* ---- orientation / lisgd command ------------------------------------- */

static int transform_to_o(const char *transform)
{
    json_error_t err;
    json_t *root;

    if (!transform)
        return 0;

    root = json_load_file(ORIENT_FILE, 0, &err);
    if (root) {
        if (json_is_object(root)) {
            json_t *v = json_object_get(root, transform);

            if (json_is_integer(v)) {
                long n = (long)json_integer_value(v);

                if (n >= 0 && n <= 3) {
                    json_decref(root);
                    return (int)n;
                }
            } else if (json_is_boolean(v)) {
                json_decref(root);
                return json_is_true(v) ? 1 : 0;
            }
        }
        json_decref(root);
    }

    if (strcmp(transform, "normal") == 0 ||
        strcmp(transform, "flipped") == 0)
        return 0;
    if (strcmp(transform, "90") == 0 ||
        strcmp(transform, "flipped-90") == 0)
        return 1;
    if (strcmp(transform, "180") == 0 ||
        strcmp(transform, "flipped-180") == 0)
        return 2;
    if (strcmp(transform, "270") == 0 ||
        strcmp(transform, "flipped-270") == 0)
        return 3;
    return 0;
}

/* Python repr() for the log line; covers the strings lisgd receives. */
static char *py_repr(const char *s)
{
    bool has_single = strchr(s, '\'') != NULL;
    bool has_double = strchr(s, '"') != NULL;
    char quote = (has_single && !has_double) ? '"' : '\'';
    size_t n = strlen(s);
    char *buf = malloc(n * 4 + 3);
    size_t len = 0;
    size_t i;

    if (!buf)
        return strdup("''");

    buf[len++] = quote;
    for (i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];

        if (c == (unsigned char)quote || c == '\\') {
            buf[len++] = '\\';
            buf[len++] = (char)c;
        } else if (c == '\n') {
            buf[len++] = '\\';
            buf[len++] = 'n';
        } else if (c == '\r') {
            buf[len++] = '\\';
            buf[len++] = 'r';
        } else if (c == '\t') {
            buf[len++] = '\\';
            buf[len++] = 't';
        } else {
            buf[len++] = (char)c;
        }
    }
    buf[len++] = quote;
    buf[len] = '\0';
    return buf;
}

static char *argv_repr(char *const argv[], int argc)
{
    size_t cap = 16;
    size_t len = 0;
    char *buf;
    int i;

    for (i = 0; i < argc; i++)
        cap += strlen(argv[i]) * 4 + 8;
    buf = malloc(cap);
    if (!buf)
        return strdup("[]");

    buf[len++] = '[';
    for (i = 0; i < argc; i++) {
        char *r;
        size_t rl;

        if (i > 0) {
            buf[len++] = ',';
            buf[len++] = ' ';
        }
        r = py_repr(argv[i]);
        rl = strlen(r);
        memcpy(buf + len, r, rl);
        len += rl;
        free(r);
    }
    buf[len++] = ']';
    buf[len] = '\0';
    return buf;
}

static void free_argv(char **argv, int argc)
{
    int i;

    if (!argv)
        return;
    for (i = 0; i < argc; i++)
        free(argv[i]);
    free(argv);
}

static char **build_lisgd_argv(const char *dev, const char *transform,
                               json_t *gestures, int *argc_out)
{
    int o = transform_to_o(transform);
    int gw = 0;
    int gh = 0;
    bool has_geo = output_geometry(&gw, &gh);
    size_t n = json_array_size(gestures);
    int total = 5 + (int)n * 2 + (has_geo ? 4 : 0) + 1;
    char **argv = calloc((size_t)total, sizeof(char *));
    char num[32];
    char geo[64];
    char *repr;
    int k = 0;
    size_t i;
    json_t *g;

    if (!argv)
        return NULL;

    argv[k++] = strdup("lisgd");
    argv[k++] = strdup("-d");
    argv[k++] = strdup(dev);
    argv[k++] = strdup("-o");
    snprintf(num, sizeof(num), "%d", o);
    argv[k++] = strdup(num);

    json_array_foreach(gestures, i, g) {
        const char *dir = json_string_value(json_object_get(g, "dir"));
        const char *edge = json_string_value(json_object_get(g, "edge"));
        const char *dist =
            json_string_value(json_object_get(g, "distance"));
        const char *mode = json_string_value(json_object_get(g, "mode"));
        const char *cmd = json_string_value(json_object_get(g, "cmd"));
        char *spec;
        size_t slen;
        bool ok;
        long fingers = fingers_value(g, &ok);

        if (!dir)
            dir = "";
        if (!edge)
            edge = "";
        if (!dist)
            dist = "";
        if (!mode)
            mode = "";
        if (!cmd)
            cmd = "";

        slen = strlen(dir) + strlen(edge) + strlen(dist) + strlen(mode) +
               strlen(cmd) + 64;
        spec = malloc(slen);
        if (!spec)
            break;
        snprintf(spec, slen, "%ld,%s,%s,%s,%s,%s", fingers, dir, edge,
                 dist, mode, cmd);
        argv[k++] = strdup("-g");
        argv[k++] = spec;
    }

    if (has_geo) {
        snprintf(num, sizeof(num), "%d", gw);
        argv[k++] = strdup("-w");
        argv[k++] = strdup(num);
        snprintf(num, sizeof(num), "%d", gh);
        argv[k++] = strdup("-h");
        argv[k++] = strdup(num);
    }
    argv[k] = NULL;
    *argc_out = k;

    if (has_geo)
        snprintf(geo, sizeof(geo), "(%d, %d)", gw, gh);
    else
        snprintf(geo, sizeof(geo), "None");

    repr = argv_repr(argv, k);
    log_msg("transform=%s -o=%d geo=%s n_gestures=%d cmd=%s",
            transform, o, geo, (int)n, repr ? repr : "[]");
    free(repr);
    return argv;
}

/* ---- daemon ----------------------------------------------------------- */

static int child_running(pid_t pid)
{
    int status;
    pid_t r;

    if (pid <= 0)
        return 0;
    r = waitpid(pid, &status, WNOHANG);
    return r == 0;
}

/* Reap any exited children (old lisgd instances) so restarts leave no zombies. */
static void reap_children(void)
{
    while (waitpid(-1, NULL, WNOHANG) > 0)
        ;
}

static pid_t spawn_lisgd(char *const argv[])
{
    pid_t pid = fork();

    if (pid < 0)
        return -1;
    if (pid == 0) {
        int devnull = open("/dev/null", O_RDWR);

        if (devnull >= 0) {
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            if (devnull > STDERR_FILENO)
                close(devnull);
        }
        execvp(argv[0], argv);
        _exit(127);
    }
    return pid;
}

static void write_pidfile(void)
{
    FILE *f = fopen(PIDFILE, "w");

    if (f) {
        fprintf(f, "%d", (int)getpid());
        fclose(f);
    }
}

static void cleanup_daemon(pid_t child)
{
    char buf[64];
    FILE *f;

    kill_lisgd();
    if (child > 0) {
        if (kill(child, 0) == 0)
            kill(child, SIGTERM);
        while (waitpid(child, NULL, 0) < 0 && errno == EINTR)
            ;
    }
    reap_children();

    f = fopen(PIDFILE, "r");
    if (f) {
        if (fgets(buf, sizeof(buf), f) && atoi(buf) == (int)getpid())
            unlink(PIDFILE);
        fclose(f);
    }
}

static int daemon_run(void)
{
    char *dev;
    char *lisgd;
    pid_t child = 0;
    char *last_sig = NULL;
    char *last_dev = NULL;
    bool have_orient = false;
    bool have_gest = false;
    struct timespec last_orient = { 0, 0 };
    struct timespec last_gest = { 0, 0 };

    mkdir_p(CFG);
    write_pidfile();
    log_msg("manager start pid=%d", (int)getpid());

    dev = detect_device();
    lisgd = which("lisgd");
    if (!dev || !*dev || access(dev, F_OK) != 0 || !lisgd) {
        log_msg("cannot start: dev=%s lisgd=%s", dev ? dev : "",
                lisgd ? lisgd : "None");
        free(dev);
        free(lisgd);
        unlink(PIDFILE);
        return 1;
    }
    free(lisgd);

    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);
    signal(SIGPIPE, SIG_IGN);

    while (!g_stop) {
        char *cdev;
        char *transform;
        json_t *gestures;
        char **argv;
        char *sig;
        struct stat st;
        struct timespec orient = { 0, 0 };
        struct timespec gest = { 0, 0 };
        bool has_orient = false;
        bool has_gest = false;
        bool need_restart;
        int argc = 0;

        if (is_disabled()) {
            kill_lisgd();
            reap_children();
            child = 0;
            free(last_sig);
            last_sig = NULL;
            sleep_ms(2000);
            continue;
        }

        cdev = detect_device();
        if (!cdev || !*cdev || access(cdev, F_OK) != 0) {
            free(cdev);
            kill_lisgd();
            reap_children();
            child = 0;
            free(last_sig);
            last_sig = NULL;
            sleep_ms(2000);
            continue;
        }

        if (stat(ORIENT_FILE, &st) == 0) {
            has_orient = true;
            orient = st.st_mtim;
        }
        if (stat(GEST_FILE, &st) == 0) {
            has_gest = true;
            gest = st.st_mtim;
        }

        transform = sway_output_transform();
        gestures = load_gestures();
        argv = build_lisgd_argv(cdev, transform, gestures, &argc);
        sig = argv ? argv_repr(argv, argc) : strdup("[]");

        need_restart = (child == 0);
        if (!need_restart && !child_running(child)) {
            child = 0;
            need_restart = true;
        }
        if (!need_restart && strcmp(sig, last_sig ? last_sig : "") != 0)
            need_restart = true;
        if (!need_restart &&
            strcmp(cdev, last_dev ? last_dev : "") != 0)
            need_restart = true;
        if (!need_restart &&
            (has_orient != have_orient ||
             (has_orient &&
              (orient.tv_sec != last_orient.tv_sec ||
               orient.tv_nsec != last_orient.tv_nsec))))
            need_restart = true;
        if (!need_restart &&
            (has_gest != have_gest ||
             (has_gest && (gest.tv_sec != last_gest.tv_sec ||
                           gest.tv_nsec != last_gest.tv_nsec))))
            need_restart = true;

        if (need_restart && argv) {
            kill_lisgd();
            sleep_ms(100);
            reap_children();
            child = spawn_lisgd(argv);
            if (child > 0) {
                free(last_sig);
                last_sig = strdup(sig);
                free(last_dev);
                last_dev = strdup(cdev);
                have_orient = has_orient;
                last_orient = orient;
                have_gest = has_gest;
                last_gest = gest;
            } else {
                log_msg("lisgd start failed: %s", strerror(errno));
                child = 0;
                free(last_sig);
                last_sig = NULL;
            }
        }

        free_argv(argv, argc);
        free(sig);
        free(transform);
        json_decref(gestures);
        free(cdev);
        reap_children();
        sleep_ms(2000);
    }

    cleanup_daemon(child);
    free(dev);
    free(last_sig);
    free(last_dev);
    return 0;
}

/* ---- CLI -------------------------------------------------------------- */

static int cmd_start(void)
{
    char *lisgd;
    char *self;
    pid_t pid;

    if (is_disabled())
        return 0;

    lisgd = which("lisgd");
    if (!lisgd)
        return 0;
    free(lisgd);

    if (access(PIDFILE, F_OK) == 0) {
        int running = read_pidfile();

        if (running > 0 && kill(running, 0) == 0)
            return 0;
        unlink(PIDFILE);
    }

    self = g_self ? strdup(g_self) : NULL;
    if (!self)
        return 1;

    pid = fork();
    if (pid < 0) {
        free(self);
        return 1;
    }
    if (pid == 0) {
        int devnull;

        setsid();
        devnull = open("/dev/null", O_RDWR);
        if (devnull >= 0) {
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            if (devnull > STDERR_FILENO)
                close(devnull);
        }
        {
            char *args[] = { self, "_daemon", NULL };

            execv(self, args);
        }
        _exit(127);
    }

    free(self);
    return 0;
}

static int cmd_stop(void)
{
    kill_manager(false);
    kill_lisgd();
    return 0;
}

static int cmd_status(void)
{
    char *transform;
    char *dev;
    json_t *gestures;
    size_t i;
    json_t *g;

    printf("%s\n", lisgd_running() ? "running" : "stopped");
    printf("%s\n", is_disabled() ? "disabled" : "enabled");

    transform = sway_output_transform();
    printf("transform=%s -o=%d\n", transform, transform_to_o(transform));

    dev = detect_device();
    printf("device=%s\n", dev);
    printf("gestures:\n");

    gestures = load_gestures();
    json_array_foreach(gestures, i, g) {
        const char *dir = json_string_value(json_object_get(g, "dir"));
        const char *edge = json_string_value(json_object_get(g, "edge"));
        const char *dist =
            json_string_value(json_object_get(g, "distance"));
        const char *mode = json_string_value(json_object_get(g, "mode"));
        const char *cmd = json_string_value(json_object_get(g, "cmd"));
        bool ok;
        long fingers = fingers_value(g, &ok);

        printf("  %ld,%s,%s,%s,%s -> %s\n", fingers, dir ? dir : "",
               edge ? edge : "", dist ? dist : "", mode ? mode : "",
               cmd ? cmd : "");
    }

    json_decref(gestures);
    free(transform);
    free(dev);
    return 0;
}

static int cmd_gestures_export(void)
{
    json_t *gestures = load_gestures();
    char *text = json_dumps(gestures, JSON_INDENT(2) | JSON_ENSURE_ASCII);

    if (text) {
        printf("%s\n", text);
        free(text);
    }
    json_decref(gestures);
    return 0;
}

static int cmd_gestures_import(void)
{
    char *buf = read_stdin();
    json_error_t err;
    json_t *data;
    bool all_valid = true;
    size_t i;
    json_t *value;

    if (!buf) {
        log_msg("gestures import failed: cannot read stdin");
        return 1;
    }

    data = json_loads(buf, 0, &err);
    free(buf);
    if (!data) {
        log_msg("gestures import failed: %s", err.text);
        return 1;
    }

    if (!json_is_array(data)) {
        log_msg("gestures import rejected: malformed entry");
        json_decref(data);
        return 1;
    }
    json_array_foreach(data, i, value) {
        if (!validate_gesture(value)) {
            all_valid = false;
            break;
        }
    }
    if (!all_valid) {
        log_msg("gestures import rejected: malformed entry");
        json_decref(data);
        return 1;
    }

    save_gestures(data);
    json_decref(data);
    return 0;
}

static int cmd_toggle(void)
{
    mkdir_p(CFG);

    if (is_disabled()) {
        unlink(DISABLED);
        return cmd_start();
    }

    {
        FILE *f = fopen(DISABLED, "w");

        if (f) {
            fputs("disabled\n", f);
            fclose(f);
        }
    }
    return cmd_stop();
}

int main(int argc, char **argv)
{
    const char *cmd;

    init_paths();
    init_self(argc > 0 ? argv[0] : NULL);

    cmd = argc > 1 ? argv[1] : "start";

    if (strcmp(cmd, "start") == 0)
        return cmd_start();
    if (strcmp(cmd, "stop") == 0)
        return cmd_stop();
    if (strcmp(cmd, "status") == 0)
        return cmd_status();
    if (strcmp(cmd, "toggle") == 0)
        return cmd_toggle();
    if (strcmp(cmd, "gestures-export") == 0)
        return cmd_gestures_export();
    if (strcmp(cmd, "gestures-import") == 0)
        return cmd_gestures_import();
    if (strcmp(cmd, "_daemon") == 0)
        return daemon_run();

    fprintf(stderr,
            "usage: %s {start|stop|toggle|status|gestures-export|"
            "gestures-import}\n",
            argv[0]);
    return 1;
}
