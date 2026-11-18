# Optional C daemons

`powerkeyd` and `sway-tablet-gestures` exist twice:

| Implementation | Location | Installed by default |
|---|---|---|
| Python | `config/home/.local/bin/` | yes |
| C | `src/*.c`, built into `/tmp` | no |

The Python versions are the portable default and work on any machine with
`python3`. The C versions are a 1:1 replacement for low-memory devices: they
do the same jobs with a fraction of the resident memory.

Measured on the LP-W841 tablet (PSS):

| Daemon | Python | C |
|---|---|---|
| `powerkeyd` | 9,220 kB | 226 kB |
| `sway-tablet-gestures` | ~9,500 kB | 257 kB |

Both C binaries are self-contained apart from libc: `jansson` is linked
statically, so the target does not need extra libraries.

## Build

The build runs inside Debian 13 (the tablet's release) so the binaries match
the target's glibc. `src/build.sh` uses Docker, but the result is a plain ELF
binary — Docker is only needed on the build machine.

```sh
./src/build.sh                    # -> /tmp/sway-tablet-bin/
./src/build.sh /path/to/output    # custom output directory
```

Binaries are deliberately written outside the repo. `config/` stays a pure
copy of deployable files, and `src/` never contains build output.

Files:

| File | Role |
|---|---|
| `Dockerfile.debian13` | Debian 13 toolchain with `libjansson-dev` |
| `build.sh` | builds both daemons and extracts them to `/tmp` |
| `powerkeyd.c` | power-button daemon (short press = screen, long press = dialog) |
| `sway-tablet-gestures.c` | `lisgd` manager (gestures, rotation, device detection) |

## Install on a device

### With the installer

```sh
./src/build.sh
./install.sh --c-daemons
./install.sh --c-daemons --c-bin-dir /tmp/sway-tablet-bin
```

`install.sh` first deploys the Python scripts as usual, then replaces
`powerkeyd` and `sway-tablet-gestures` in `~/.local/bin` with the ELF binaries.
Both files are checked for the ELF magic before anything is copied, so a
missing or wrong binary aborts the install.

The flag is opt-in: a plain `./install.sh` keeps the Python daemons.

### With the deploy helper

`src/deploy.sh` installs only the two binaries, locally or over ssh:

```sh
# local user
./src/deploy.sh --restart

# another local home
./src/deploy.sh --home /home/alice --restart

# remote device
./src/deploy.sh --host mii@192.168.1.35 --restart

# dry run
./src/deploy.sh --host mii@192.168.1.35 --dry-run
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--bin-dir DIR` | `/tmp/sway-tablet-bin` | where `build.sh` put the binaries |
| `--home DIR` | `$HOME` (local or remote) | target home directory |
| `--host USER@HOST` | — | copy over ssh instead of installing locally |
| `--restart` | off | stop the old daemons and start the new ones |
| `--dry-run` | off | print the commands without running them |

`--restart` finds the session socket itself (`XDG_RUNTIME_DIR`, the first
`wayland-*` socket) so it also works from a plain ssh shell. If the
`~/.config/swaytablet/gestures-disabled` marker exists, `sway-tablet-gestures
start` stays disabled, exactly like the autostart path.

## After a plain install

`install.sh` always writes the Python scripts first. Re-running it without
`--c-daemons` reverts the daemons to Python; run `src/deploy.sh --restart`
(or `install.sh --c-daemons`) afterwards to switch back to C.

## Verify

```sh
file ~/.local/bin/powerkeyd ~/.local/bin/sway-tablet-gestures
sha256sum ~/.local/bin/powerkeyd ~/.local/bin/sway-tablet-gestures
~/.local/bin/sway-tablet-gestures status
pgrep -ax powerkeyd
pgrep -ax sway-tablet-gestures
```

`powerkeyd` logs to `/tmp/powerkeyd.log` and needs read access to
`/dev/input/event*` (see the Permissions section in the main README).
