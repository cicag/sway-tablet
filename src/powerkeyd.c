/*
 * powerkeyd - power button handler for the sway tablet session.
 *
 * Reads /dev/input/event* directly and implements:
 *   short press (< HOLD_MS) : toggle the output DPMS state
 *   long press  (>= HOLD_MS): open the power menu (powermenu)
 *   screen off for OFF_DELAY_MS: power the machine off
 *
 * Environment overrides:
 *   POWERKEY_OUTPUT   sway output name (auto-detected when unset)
 *   POWERKEY_DEVICE   input device name (auto-detected when unset)
 */
#define _GNU_SOURCE

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <limits.h>
#include <poll.h>
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
#include <linux/input.h>

#ifndef KEY_POWER
#define KEY_POWER 116
#endif

#define HOLD_MS       1200
#define OFF_DELAY_MS  (300 * 1000)

/* Resolved sway output name. */
static char *g_output;
/* POWERKEY_DEVICE override, or NULL. */
static char *g_devname;
/* Directory containing this executable (for powermenu). */
static char g_bin_dir[PATH_MAX];
/* Monotonic deadline for the automatic poweroff, 0 = no timer. */
static int64_t g_off_deadline;
static volatile sig_atomic_t g_stop;

static void log_msg(const char *fmt, ...)
{
    va_list ap;

    fputs("powerkeyd: ", stdout);
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    fputc('\n', stdout);
    fflush(stdout);
}

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

/* ---- environment / paths --------------------------------------------- */

static void setup_env(void)
{
    const char *rt = getenv("XDG_RUNTIME_DIR");
    char path[PATH_MAX];
    char best[PATH_MAX] = "";
    time_t best_mtime = 0;
    DIR *dir;
    struct dirent *ent;

    if (!rt || !*rt) {
        snprintf(path, sizeof(path), "/run/user/%d", (int)getuid());
        setenv("XDG_RUNTIME_DIR", path, 0);
        rt = getenv("XDG_RUNTIME_DIR");
    }
    if (!rt || !*rt)
        return;

    dir = opendir(rt);
    if (!dir)
        return;

    while ((ent = readdir(dir)) != NULL) {
        size_t len = strlen(ent->d_name);
        struct stat st;

        if (strncmp(ent->d_name, "sway-ipc.", 9) != 0)
            continue;
        if (len < 5 || strcmp(ent->d_name + len - 5, ".sock") != 0)
            continue;

        snprintf(path, sizeof(path), "%s/%s", rt, ent->d_name);
        if (stat(path, &st) != 0)
            continue;
        if (st.st_mtime >= best_mtime) {
            best_mtime = st.st_mtime;
            snprintf(best, sizeof(best), "%s", path);
        }
    }
    closedir(dir);

    if (best[0])
        setenv("SWAYSOCK", best, 1);
}

static void setup_bin_dir(void)
{
    ssize_t n;
    char *slash;

    n = readlink("/proc/self/exe", g_bin_dir, sizeof(g_bin_dir) - 1);
    if (n <= 0) {
        snprintf(g_bin_dir, sizeof(g_bin_dir), ".");
        return;
    }
    g_bin_dir[n] = '\0';
    slash = strrchr(g_bin_dir, '/');
    if (slash)
        *slash = '\0';
}

/* ---- process helpers -------------------------------------------------- */

/* Read a small text file and strip trailing whitespace/newlines. */
static char *read_text(const char *path, size_t max)
{
    char *buf;
    ssize_t n;
    int fd;

    fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return NULL;
    buf = malloc(max + 1);
    if (!buf) {
        close(fd);
        return NULL;
    }
    n = read(fd, buf, max);
    close(fd);
    if (n < 0) {
        free(buf);
        return NULL;
    }
    buf[n] = '\0';
    while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r' ||
                     buf[n - 1] == ' ' || buf[n - 1] == '\t'))
        buf[--n] = '\0';
    return buf;
}

/* Run a command, discard its output, and wait for it. */
static void run_cmd(char *const argv[])
{
    pid_t pid;
    int status;

    pid = fork();
    if (pid < 0) {
        log_msg("fork: %s", strerror(errno));
        return;
    }
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

    while (waitpid(pid, &status, 0) < 0 && errno == EINTR)
        ;
}

/* Run a command and capture stdout. Returns 0 on success. */
static int run_capture(char *const argv[], char **out)
{
    char *buf;
    size_t cap = 4096;
    size_t len = 0;
    int pfd[2];
    int status;
    pid_t pid;

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
    buf = malloc(cap);
    if (!buf) {
        close(pfd[0]);
        waitpid(pid, &status, 0);
        return -1;
    }

    for (;;) {
        ssize_t r;

        if (len + 4096 > cap) {
            char *tmp = realloc(buf, cap * 2);

            if (!tmp)
                break;
            buf = tmp;
            cap *= 2;
        }
        r = read(pfd[0], buf + len, cap - len - 1);
        if (r < 0) {
            if (errno == EINTR)
                continue;
            break;
        }
        if (r == 0)
            break;
        len += (size_t)r;
    }
    close(pfd[0]);
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR)
        ;
    buf[len] = '\0';
    *out = buf;

    return (WIFEXITED(status) && WEXITSTATUS(status) == 0) ? 0 : -1;
}

/* Fork twice so the menu survives this daemon and leaves no zombie. */
static int spawn_detached(char *const argv[], const char *path)
{
    pid_t pid;
    int status;

    pid = fork();
    if (pid < 0)
        return -1;
    if (pid == 0) {
        pid_t grandchild = fork();

        if (grandchild < 0)
            _exit(1);
        if (grandchild > 0)
            _exit(0);

        setsid();
        setenv("GDK_BACKEND", "wayland", 1);
        setenv("WAYLAND_DISPLAY", "wayland-1", 0);
        {
            int devnull = open("/dev/null", O_RDWR);

            if (devnull >= 0) {
                dup2(devnull, STDIN_FILENO);
                dup2(devnull, STDOUT_FILENO);
                dup2(devnull, STDERR_FILENO);
                if (devnull > STDERR_FILENO)
                    close(devnull);
            }
        }
        execv(path, argv);
        _exit(127);
    }

    while (waitpid(pid, &status, 0) < 0 && errno == EINTR)
        ;
    return 0;
}

static bool contains_ci(const char *haystack, const char *needle)
{
    size_t nlen = strlen(needle);

    if (nlen == 0)
        return true;
    for (const char *p = haystack; *p; p++) {
        size_t i = 0;

        while (i < nlen && p[i] &&
               tolower((unsigned char)p[i]) ==
                   tolower((unsigned char)needle[i]))
            i++;
        if (i == nlen)
            return true;
    }
    return false;
}

/* Does any /proc/<pid>/cmdline contain path? (pgrep -f equivalent) */
static bool process_running(const char *path)
{
    DIR *dir;
    struct dirent *ent;
    bool found = false;

    dir = opendir("/proc");
    if (!dir)
        return false;

    while (!found && (ent = readdir(dir)) != NULL) {
        char file[PATH_MAX];
        char buf[4096];
        size_t plen = strlen(path);
        ssize_t n;
        int fd;

        if (!isdigit((unsigned char)ent->d_name[0]))
            continue;

        snprintf(file, sizeof(file), "/proc/%s/cmdline", ent->d_name);
        fd = open(file, O_RDONLY | O_CLOEXEC);
        if (fd < 0)
            continue;
        n = read(fd, buf, sizeof(buf));
        close(fd);
        if (n <= 0 || (size_t)n < plen)
            continue;

        for (ssize_t i = 0; i + (ssize_t)plen <= n; i++) {
            if (memcmp(buf + i, path, plen) == 0) {
                found = true;
                break;
            }
        }
    }
    closedir(dir);
    return found;
}

/* ---- sway output / DPMS ---------------------------------------------- */

static char *detect_output(void)
{
    char *out = NULL;
    char *argv[] = { "swaymsg", "-t", "get_outputs", NULL };
    json_error_t err;
    json_t *root;
    char *name = NULL;
    size_t i;
    json_t *value;

    if (run_capture(argv, &out) != 0) {
        free(out);
        return NULL;
    }

    root = json_loads(out, 0, &err);
    free(out);
    if (!root || !json_is_array(root)) {
        json_decref(root);
        return NULL;
    }

    json_array_foreach(root, i, value) {
        const char *nm = json_string_value(json_object_get(value, "name"));
        json_t *headless = json_object_get(value, "headless");

        if (nm && !(headless && json_is_true(headless))) {
            name = strdup(nm);
            break;
        }
    }
    json_decref(root);
    return name;
}

/* Returns true when the screen is on. Errors are treated as "on". */
static bool dpms_on(void)
{
    char *out = NULL;
    char *argv[] = { "swaymsg", "-t", "get_outputs", NULL };
    json_error_t err;
    json_t *root;
    bool on = true;
    size_t i;
    json_t *value;

    if (run_capture(argv, &out) != 0) {
        free(out);
        return true;
    }

    root = json_loads(out, 0, &err);
    free(out);
    if (!root || !json_is_array(root)) {
        json_decref(root);
        return true;
    }

    json_array_foreach(root, i, value) {
        const char *nm = json_string_value(json_object_get(value, "name"));

        if (nm && g_output && strcmp(nm, g_output) == 0) {
            json_t *dpms = json_object_get(value, "dpms");

            on = dpms ? json_is_true(dpms) : true;
            break;
        }
    }
    json_decref(root);
    return on;
}

static void sway_dpms(bool on)
{
    char *argv[] = { "swaymsg", "output", g_output,
                     "dpms", on ? "on" : "off", NULL };

    run_cmd(argv);
}

/* ---- input device ----------------------------------------------------- */

static char *find_device(void)
{
    glob_t matches;
    char *found = NULL;

    if (glob("/sys/class/input/event*/device/name", 0, NULL, &matches) != 0)
        return NULL;

    for (size_t i = 0; i < matches.gl_pathc && !found; i++) {
        const char *p;
        const char *slash;
        char dev[64];
        char *name;
        int len;
        bool match;

        name = read_text(matches.gl_pathv[i], 256);
        if (!name)
            continue;

        p = strstr(matches.gl_pathv[i], "/input/");
        if (!p) {
            free(name);
            continue;
        }
        p += 7; /* skip "/input/" */
        slash = strchr(p, '/');
        if (!slash) {
            free(name);
            continue;
        }
        len = (int)(slash - p);
        if (len <= 0 || len >= (int)sizeof(dev)) {
            free(name);
            continue;
        }
        snprintf(dev, sizeof(dev), "/dev/input/%.*s", len, p);

        if (g_devname)
            match = strcmp(name, g_devname) == 0;
        else
            match = contains_ci(name, "power") || contains_ci(name, "pek");

        if (match)
            found = strdup(dev);
        free(name);
    }

    globfree(&matches);
    return found;
}

static int open_device_retry(void)
{
    for (int i = 0; i < 50 && !g_stop; i++) {
        char *dev = find_device();

        if (dev) {
            int fd = open(dev, O_RDONLY | O_CLOEXEC);

            if (fd >= 0) {
                log_msg("reading %s", dev);
                free(dev);
                return fd;
            }
            log_msg("open %s: %s", dev, strerror(errno));
            free(dev);
        }
        sleep_ms(200);
    }
    return -1;
}

/* ---- actions ---------------------------------------------------------- */

static void schedule_poweroff(void)
{
    g_off_deadline = now_ms() + OFF_DELAY_MS;
    log_msg("screen off, poweroff in %d s", OFF_DELAY_MS / 1000);
}

static void cancel_poweroff(void)
{
    if (g_off_deadline) {
        g_off_deadline = 0;
        log_msg("poweroff cancelled");
    }
}

static void do_poweroff(void)
{
    char *argv[] = { "systemctl", "poweroff", NULL };

    g_off_deadline = 0;
    if (dpms_on())
        return;

    log_msg("powering off (screen still off)");
    run_cmd(argv);
}

static void short_action(void)
{
    if (dpms_on()) {
        sway_dpms(false);
        schedule_poweroff();
    } else {
        cancel_poweroff();
        sway_dpms(true);
    }
}

static void long_action(void)
{
    char menu[PATH_MAX + 16];
    char *argv[2];

    cancel_poweroff();
    if (!dpms_on())
        sway_dpms(true);

    snprintf(menu, sizeof(menu), "%s/powermenu", g_bin_dir);
    if (process_running(menu))
        return;

    argv[0] = menu;
    argv[1] = NULL;
    if (spawn_detached(argv, menu) == 0)
        log_msg("powermenu opened");
}

/* ---- daemon ----------------------------------------------------------- */

static int init_common(void)
{
    const char *value;

    setup_env();
    setup_bin_dir();

    value = getenv("POWERKEY_OUTPUT");
    if (value && *value)
        g_output = strdup(value);
    value = getenv("POWERKEY_DEVICE");
    if (value && *value)
        g_devname = strdup(value);

    if (!g_output) {
        for (int i = 0; i < 20 && !g_stop; i++) {
            g_output = detect_output();
            if (g_output)
                break;
            if (i == 0)
                log_msg("waiting for sway output...");
            sleep_ms(500);
        }
    }
    if (!g_output) {
        log_msg("no usable sway output");
        return -1;
    }
    return 0;
}

static int run_daemon(void)
{
    struct input_event events[64];
    size_t pending = 0;
    int64_t press_ms = 0;
    int fd;

    if (init_common() != 0)
        return 1;

    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);
    signal(SIGPIPE, SIG_IGN);

    fd = open_device_retry();
    if (fd < 0) {
        log_msg("device %s not found",
                g_devname ? g_devname : "(power key)");
        return 1;
    }

    while (!g_stop) {
        struct pollfd pfd;
        int timeout = -1;
        int ready;

        if (g_off_deadline) {
            int64_t remaining = g_off_deadline - now_ms();

            timeout = remaining > 0 ? (int)remaining : 0;
        }

        pfd.fd = fd;
        pfd.events = POLLIN;
        pfd.revents = 0;

        ready = poll(&pfd, 1, timeout);
        if (ready < 0) {
            if (errno != EINTR) {
                log_msg("poll: %s", strerror(errno));
                break;
            }
        } else if (ready > 0 &&
                   (pfd.revents & (POLLIN | POLLHUP | POLLERR))) {
            ssize_t r = read(fd, (char *)events + pending,
                             sizeof(events) - pending);

            if (r > 0) {
                size_t count;
                size_t rest;

                pending += (size_t)r;
                count = pending / sizeof(struct input_event);

                for (size_t i = 0; i < count; i++) {
                    struct input_event *ev = &events[i];

                    if (ev->type != EV_KEY || ev->code != KEY_POWER)
                        continue;
                    if (ev->value == 1) {
                        press_ms = now_ms();
                    } else if (ev->value == 0 && press_ms) {
                        int64_t duration = now_ms() - press_ms;

                        press_ms = 0;
                        if (duration >= HOLD_MS)
                            long_action();
                        else
                            short_action();
                    }
                }

                rest = pending % sizeof(struct input_event);
                if (count > 0 && rest > 0)
                    memmove(events, &events[count], rest);
                pending = rest;
            } else if (r == 0 ||
                       (errno != EINTR && errno != EAGAIN)) {
                log_msg("input device lost, reopening");
                close(fd);
                pending = 0;
                press_ms = 0;
                fd = open_device_retry();
                if (fd < 0)
                    break;
            }
        }

        if (g_off_deadline && now_ms() >= g_off_deadline)
            do_poweroff();
    }

    close(fd);
    return 0;
}

/* ---- entry point ------------------------------------------------------ */

int main(int argc, char **argv)
{
    const char *arg = argc > 1 ? argv[1] : "";

    if (strcmp(arg, "--test-short") == 0) {
        if (init_common() != 0)
            return 1;
        short_action();
        return 0;
    }
    if (strcmp(arg, "--test-sleep") == 0) {
        if (init_common() != 0)
            return 1;
        sway_dpms(false);
        schedule_poweroff();
        sleep_ms(60000);
        return 0;
    }
    if (strcmp(arg, "--test-long") == 0) {
        if (init_common() != 0)
            return 1;
        long_action();
        return 0;
    }
    return run_daemon();
}
