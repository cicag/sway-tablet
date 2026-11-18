# Optional C daemons

`powerkeyd` and `sway-tablet-gestures` exist twice:

| Implementation | Location | Installed by default |
|---|---|---|
| Python | `config/home/.local/bin/` | yes |
| C | `src/*.c`, built into `src/build/` | no |

The Python versions are the portable default and work on any machine with
`python3`. The C versions are a 1:1 replacement. Maybe oneday, decided to make this one as default.

Measured on the LP-W841 tablet (PSS):

| Daemon | Python | C |
|---|---|---|
| `powerkeyd` | 9,220 kB | 226 kB |
| `sway-tablet-gestures` | ~9,500 kB | 257 kB |

## Build

`src/build.sh` compiles both daemons into `src/build/`. The directory is
created if it does not exist, so the output is ready to deploy right away:

```sh
mkdir -p src/build                 # optional; build.sh does this too
./src/build.sh                     # -> src/build/powerkeyd
                                   #    src/build/sway-tablet-gestures
./src/build.sh /path/to/output     # custom output directory
```

For a native build you need a C compiler and `libjansson-dev` (plus libc
headers). Use whatever distro, compiler or container you like — for example
Debian with `apt install gcc libc6-dev libjansson-dev`.

`Dockerfile.debian13` is just the environment used for the original tablet; use
it as example. The normal build above does not use Docker
at all. If that image happens to fit your target, you can use it — `build.sh`
bind-mounts `src/` and the output directory into the container, so the binaries
land straight in `build/` (or your custom output directory):

```sh
./src/build.sh --docker                    # same src/build output, Debian 13 container
./src/build.sh --docker /path/to/output    # custom output directory
```

Files:

| File | Role |
|---|---|
| `build.sh` | builds both daemons into `src/build/` |
| `powerkeyd.c` | power-button daemon (short press = screen, long press = dialog) |
| `sway-tablet-gestures.c` | `lisgd` manager (gestures, rotation, device detection) |
| `Dockerfile.debian13` | optional example toolchain image (Debian 13 + `libjansson-dev`); sources and output are bind-mounted |

## Install on a device

### With the installer

`install.sh --c-daemons` reads `src/build/` by default:

```sh
./src/build.sh
./install.sh --c-daemons
./install.sh --c-daemons --c-bin-dir /path/to/output   # custom build dir
```

`install.sh` first deploys the Python scripts as usual, then replaces
`powerkeyd` and `sway-tablet-gestures` in `~/.local/bin` with the ELF binaries.
Both files are checked for the ELF magic before anything is copied, so a
missing or wrong binary aborts the install.

The flag is opt-in: a plain `./install.sh` keeps the Python daemons.
