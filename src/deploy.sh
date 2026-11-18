#!/bin/sh
# Install the prebuilt C daemons into a user's ~/.local/bin.
#
#   ./src/deploy.sh [--bin-dir DIR] [--home DIR] [--host USER@HOST]
#                   [--restart] [--dry-run]
#
# Binaries are produced by src/build.sh (default /tmp/sway-tablet-bin).
# Without --host they are installed on this machine; with --host they are
# copied over ssh. --restart stops the running daemons and starts the new
# ones in the current (or remote) Wayland session.
set -eu

BIN_DIR=/tmp/sway-tablet-bin
HOME_DIR=
HOST=
RESTART=0
DRY_RUN=0
DAEMONS="powerkeyd sway-tablet-gestures"

while [ $# -gt 0 ]; do
    case "$1" in
        --bin-dir) BIN_DIR=$2; shift 2 ;;
        --home)    HOME_DIR=$2; shift 2 ;;
        --host)    HOST=$2; shift 2 ;;
        --restart) RESTART=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

check_bin() {
    f=$1
    if [ ! -f "$f" ]; then
        echo "deploy.sh: missing $f (build it with src/build.sh)" >&2
        exit 1
    fi
    if [ "$(od -An -N4 -tx1 "$f" | tr -d ' \n')" != "7f454c46" ]; then
        echo "deploy.sh: $f is not an ELF binary" >&2
        exit 1
    fi
}

# Pick the session socket to restart into, so a daemon started from a plain
# tty/ssh shell still talks to the running sway instance.
session_env() {
    uid=$(id -u)
    rt=${XDG_RUNTIME_DIR:-/run/user/$uid}
    [ -d "$rt" ] || rt=/run/user/$uid
    wd=${WAYLAND_DISPLAY:-}
    if [ -z "$wd" ]; then
        for s in "$rt"/wayland-*; do
            case "$s" in *.lock) continue ;; esac
            [ -S "$s" ] || continue
            wd=${s##*/}
            break
        done
    fi
    [ -n "$wd" ] || wd=wayland-1
}

if [ -z "$HOST" ]; then
    # ---- local install ---------------------------------------------------
    : "${HOME_DIR:=$HOME}"
    [ -d "$HOME_DIR" ] || { echo "deploy.sh: no such home: $HOME_DIR" >&2; exit 1; }

    for b in $DAEMONS; do
        check_bin "$BIN_DIR/$b"
    done

    if [ "$DRY_RUN" = 1 ]; then
        for b in $DAEMONS; do
            echo "  install -m755 $BIN_DIR/$b $HOME_DIR/.local/bin/$b"
        done
    else
        mkdir -p "$HOME_DIR/.local/bin"
        for b in $DAEMONS; do
            # remove first: overwriting a running binary fails with ETXTBSY
            rm -f "$HOME_DIR/.local/bin/$b"
            install -m755 "$BIN_DIR/$b" "$HOME_DIR/.local/bin/$b"
            echo "installed: $HOME_DIR/.local/bin/$b"
        done
    fi

    if [ "$RESTART" = 1 ]; then
        if [ "$DRY_RUN" = 1 ]; then
            echo "  restart powerkeyd + sway-tablet-gestures"
        else
            session_env
            echo "restarting daemons (XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=$wd)"
            pkill -x powerkeyd 2>/dev/null || true
            # comm is truncated to 15 chars, so match the full argv[0] instead
            pkill -f "^$HOME_DIR/.local/bin/sway-tablet-gestures" 2>/dev/null || true
            # let the old daemon clean up lisgd before starting a new one
            i=0
            while [ "$i" -lt 20 ] && \
                    pgrep -f "^$HOME_DIR/.local/bin/sway-tablet-gestures" \
                    >/dev/null 2>&1; do
                sleep 0.1
                i=$((i + 1))
            done
            if [ -x "$HOME_DIR/.local/bin/powerkeyd" ]; then
                if command -v setsid >/dev/null 2>&1; then
                    XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=$wd \
                        setsid "$HOME_DIR/.local/bin/powerkeyd" \
                        >>/tmp/powerkeyd.log 2>&1 </dev/null &
                else
                    XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=$wd \
                        nohup "$HOME_DIR/.local/bin/powerkeyd" \
                        >>/tmp/powerkeyd.log 2>&1 </dev/null &
                fi
            fi
            if [ -x "$HOME_DIR/.local/bin/sway-tablet-gestures" ]; then
                XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=$wd \
                    "$HOME_DIR/.local/bin/sway-tablet-gestures" start \
                    >/dev/null 2>&1 || true
            fi
        fi
    fi
    exit 0
fi

# ---- remote install ------------------------------------------------------
for b in $DAEMONS; do
    check_bin "$BIN_DIR/$b"
done

remote_home=${HOME_DIR:-$(ssh "$HOST" 'printf %s "$HOME"')}
remote_bin=$remote_home/.local/bin

if [ "$DRY_RUN" = 1 ]; then
    echo "  ssh $HOST mkdir -p $remote_bin"
    for b in $DAEMONS; do
        echo "  scp $BIN_DIR/$b $HOST:$remote_bin/$b"
    done
    if [ "$RESTART" = 1 ]; then
        echo "  ssh $HOST restart powerkeyd + sway-tablet-gestures"
    fi
    exit 0
fi

ssh "$HOST" "mkdir -p '$remote_bin'"
for b in $DAEMONS; do
    # scp writes through the existing inode; remove first so a running binary
    # can be replaced without ETXTBSY.
    ssh "$HOST" "rm -f '$remote_bin/$b'"
    scp -q "$BIN_DIR/$b" "$HOST:$remote_bin/$b"
    ssh "$HOST" "chmod 755 '$remote_bin/$b'"
    echo "installed: $HOST:$remote_bin/$b"
done

if [ "$RESTART" = 1 ]; then
    ssh "$HOST" "sh -s -- '$remote_bin'" <<'EOF'
bin=$1
uid=$(id -u)
rt=${XDG_RUNTIME_DIR:-/run/user/$uid}
[ -d "$rt" ] || rt=/run/user/$uid
wd=${WAYLAND_DISPLAY:-}
if [ -z "$wd" ]; then
    for s in "$rt"/wayland-*; do
        case "$s" in *.lock) continue ;; esac
        [ -S "$s" ] || continue
        wd=${s##*/}
        break
    done
fi
[ -n "$wd" ] || wd=wayland-1
echo "restarting daemons (XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=$wd)"
pkill -x powerkeyd 2>/dev/null || true
# comm is truncated to 15 chars, so match the full argv[0] instead
pkill -f "^$bin/sway-tablet-gestures" 2>/dev/null || true
# let the old daemon clean up lisgd before starting a new one
i=0
while [ "$i" -lt 20 ] && pgrep -f "^$bin/sway-tablet-gestures" >/dev/null 2>&1; do
    sleep 0.1
    i=$((i + 1))
done
if [ -x "$bin/powerkeyd" ]; then
    if command -v setsid >/dev/null 2>&1; then
        XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=$wd \
            setsid "$bin/powerkeyd" >>/tmp/powerkeyd.log 2>&1 </dev/null &
    else
        XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=$wd \
            nohup "$bin/powerkeyd" >>/tmp/powerkeyd.log 2>&1 </dev/null &
    fi
fi
if [ -x "$bin/sway-tablet-gestures" ]; then
    XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=$wd \
        "$bin/sway-tablet-gestures" start >/dev/null 2>&1 || true
fi
EOF
fi
