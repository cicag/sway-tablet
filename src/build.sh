#!/bin/sh
# Build the C daemons inside Debian 13 and extract the binaries outside the
# repo (never into config/home/.local/bin).
# Usage: ./src/build.sh [output-dir]
set -eu

here=$(cd "$(dirname "$0")" && pwd)
out=${1:-/tmp/sway-tablet-bin}

mkdir -p "$out"

docker build -t swaytablet-build -f "$here/Dockerfile.debian13" "$here"
cid=$(docker create swaytablet-build)
trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT

for bin in powerkeyd sway-tablet-gestures; do
    docker cp "$cid:/build/$bin" "$out/$bin"
    chmod +x "$out/$bin"
    echo "built: $out/$bin"
done
