#!/bin/sh
# Build the C daemons into src/build, ready for deploy.sh / install.sh.
# Usage: ./src/build.sh [--docker] [output-dir]
set -eu

here=$(cd "$(dirname "$0")" && pwd)
use_docker=0
if [ "${1:-}" = "--docker" ]; then
    use_docker=1
    shift
fi
out=${1:-$here/build}
: "${CC:=gcc}"

mkdir -p "$out"
out=$(cd "$out" && pwd)

if [ "$use_docker" = 1 ]; then
    # Optional: compile the host sources inside the example toolchain image.
    # Both src/ and the output directory are bind-mounted, so the binaries
    # land directly in $out (owned by the invoking user).
    docker build -t swaytablet-build -f "$here/Dockerfile.debian13" "$here"
    docker run --rm --user "$(id -u):$(id -g)" \
        -e "CC=$CC" \
        -v "$here:/src:ro" -v "$out:/out" -w /src \
        swaytablet-build sh -c '
            for bin in powerkeyd sway-tablet-gestures; do
                "$CC" -O2 -march=x86-64-v2 -Wall -Wextra -o "/out/$bin" "$bin.c" \
                    -Wl,-Bstatic -ljansson -Wl,-Bdynamic
            done
        '
else
    for bin in powerkeyd sway-tablet-gestures; do
        "$CC" -O2 -march=x86-64-v2 -Wall -Wextra -o "$out/$bin" "$here/$bin.c" \
            -Wl,-Bstatic -ljansson -Wl,-Bdynamic
    done
fi

for bin in powerkeyd sway-tablet-gestures; do
    echo "built: $out/$bin"
done
