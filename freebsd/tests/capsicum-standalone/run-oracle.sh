#!/bin/sh
# Build and run the Capsicum oracle as an ordinary user, saving the JSON
# result under freebsd/results/. The file name carries the kernel release
# and date only; no hostname or user name is recorded.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
results="$here/../../results"

if [ "$(id -u)" -eq 0 ]; then
	echo "run-oracle.sh: run this as an ordinary user, not root" >&2
	exit 1
fi
if [ "$(uname -s)" != "FreeBSD" ]; then
	echo "run-oracle.sh: this oracle only runs on FreeBSD" >&2
	exit 1
fi

make -C "$here" >/dev/null
mkdir -p "$results"
release=$(uname -r | tr -c 'A-Za-z0-9.\n-' '_')
out="$results/oracle-$release-$(date -u +%Y%m%d).json"

rc=0
"$here/cap-oracle" > "$out" || rc=$?
echo "wrote $out" >&2
exit "$rc"
