#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
#
# Phase 0 baseline collection (spec section 15, plan/09 Phase 0 items 1 to 4).
#
# Records the machine, kernel and package facts, and, if a stock Chromium
# (www/chromium) is running, a per-process snapshot: process type,
# capability-mode flag from the kernel, descriptor counts by type, socket
# and directory descriptors, rights, rlimits, and the NAMES (never values)
# of inherited environment variables.
#
# Writes Markdown to freebsd/results/baseline-<release>-<date>.md.
# The home directory, user name and host name are redacted.
#
# Usage: start chromium, open one ordinary web page in one tab, then run
#   sh freebsd/tools/baseline-collect.sh
# as the same (non-root) user.

set -u

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
results="$repo/freebsd/results"

if [ "$(uname -s)" != "FreeBSD" ]; then
	echo "baseline-collect.sh: run this on FreeBSD" >&2
	exit 1
fi
if [ "$(id -u)" -eq 0 ]; then
	echo "baseline-collect.sh: run as the user who runs the browser, not root" >&2
	exit 1
fi

mkdir -p "$results"
release=$(uname -r | tr -c 'A-Za-z0-9.\n-' '_')
out="$results/baseline-$release-$(date -u +%Y%m%d).md"

user=$(id -un)
host=$(hostname)
host_short=$(hostname -s 2>/dev/null || echo "$host")

redact() {
	# The home directory first, then the bare names as whole words
	# (FreeBSD sed word boundaries), so a short user name cannot mangle
	# unrelated text.
	sed -e "s#${HOME}#~#g" \
	    -e "s#[[:<:]]${user}[[:>:]]#<user>#g" \
	    -e "s#[[:<:]]${host}[[:>:]]#<host>#g" \
	    -e "s#[[:<:]]${host_short}[[:>:]]#<host>#g"
}

section() {
	printf '\n## %s\n\n' "$1"
}

code() {
	printf '```text\n'
	"$@" 2>&1 | redact
	printf '```\n'
}

sysctl_or_na() {
	for n in "$@"; do
		v=$(sysctl -n "$n" 2>/dev/null) || v="n/a"
		printf '%s: %s\n' "$n" "$v"
	done
}

collect_machine() {
	section "Machine and kernel"
	code freebsd-version -kru
	code uname -mrs
	# kern.version up to the first colon: release and source revision only.
	printf '```text\nkern.version: %s\n```\n' \
	    "$(sysctl -n kern.version | head -1 | cut -d: -f1)"
	code sysctl_or_na kern.osreldate hw.machine_arch hw.ncpu hw.physmem \
	    security.bsd.allow_ptrace_in_cap_mode security.bsd.see_other_uids \
	    security.bsd.see_other_gids security.bsd.unprivileged_proc_debug \
	    kern.trap_enotcap kern.elf64.allow_wx kern.elf64.aslr.enable \
	    kern.elf64.aslr.pie_enable kern.ipc.shm_allow_removed \
	    kern.racct.enable
	section "Graphics and display"
	code sh -c 'pciconf -lv 2>/dev/null | grep -B1 -A4 "class *= display" || echo "pciconf: no display devices listed"'
	code sh -c 'kldstat | awk "NR>1 {print \$5}" | grep -Ei "nvidia|drm|i915|amdgpu|radeon|linux" || echo "no graphics or linux modules loaded"'
	code sh -c 'echo "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset}"; [ -n "${WAYLAND_DISPLAY:-}" ] && echo "WAYLAND_DISPLAY set" || echo "WAYLAND_DISPLAY unset"; [ -n "${DISPLAY:-}" ] && echo "DISPLAY set" || echo "DISPLAY unset"'
	section "Filesystems relevant to the sandbox"
	code sh -c 'mount -t fdescfs 2>/dev/null; mount | grep -c fdescfs | sed "s/^/fdescfs mounts: /"'
}

collect_packages() {
	section "Packages"
	code sh -c 'pkg info -x "^(chromium|ungoogled-chromium|nvidia-driver|nvidia-drm|linux-nvidia|mesa-dri|mesa-libs|wayland|sndio|pulseaudio|pipewire)" 2>/dev/null || echo "none of the tracked packages installed"'
	if pkg info -e chromium 2>/dev/null; then
		code pkg info -D chromium
	fi
	section "Source revisions"
	code git -C "$repo" rev-parse HEAD
	code git -C "$repo" submodule status
	if [ -d /usr/ports/.git ]; then
		# /usr/ports usually belongs to root; reading its HEAD is safe.
		code git -c safe.directory=/usr/ports -C /usr/ports rev-parse HEAD
		code make -C /usr/ports/www/chromium -V PORTVERSION -V PORTREVISION
	else
		printf 'No git checkout at /usr/ports.\n'
	fi
}

proc_type() {
	# --type=renderer, --type=gpu-process, --type=utility plus sub-type
	args=$(procstat -c "$1" 2>/dev/null | tail -n +2)
	t=$(printf '%s\n' "$args" | tr ' ' '\n' | sed -n 's/^--type=//p' | head -1)
	s=$(printf '%s\n' "$args" | tr ' ' '\n' | sed -n 's/^--utility-sub-type=//p' | head -1)
	[ -z "$t" ] && t=browser
	[ -n "$s" ] && t="$t ($s)"
	printf '%s' "$t"
}

collect_processes() {
	section "Running Chromium processes"
	# The package installs /usr/local/share/chromium/chrome; match on the
	# path and, as a fallback, on the process name.
	pids=$( { pgrep -U "$(id -u)" -f 'chromium/chrome'
	    pgrep -U "$(id -u)" -x chrome; } 2>/dev/null | sort -un)
	if [ -z "$pids" ]; then
		printf 'No chromium process found for this user. Start chromium, '
		printf 'open one page, and run this script again to record the '
		printf 'per-process baseline.\n'
		return
	fi

	printf '| pid | type | cred flags (C = capability mode) | fds | vnode | socket | pipe | shm | other | RLIMIT_DATA |\n'
	printf '|---|---|---|---|---|---|---|---|---|---|\n'
	for p in $pids; do
		t=$(proc_type "$p")
		# procstat -s columns: PID COMM EUID RUID SVUID EGID RGID SVGID
		# UMASK FLAGS GROUPS; FLAGS shows C for capability mode.
		flags=$(procstat -s "$p" 2>/dev/null | awk 'NR==2 {print $10}')
		fd=$(procstat -f "$p" 2>/dev/null | awk 'NR>1 && $3 ~ /^[0-9]+$/')
		total=$(printf '%s\n' "$fd" | grep -c . )
		v=$(printf '%s\n' "$fd" | awk '$4=="v"' | grep -c .)
		so=$(printf '%s\n' "$fd" | awk '$4=="s"' | grep -c .)
		pi=$(printf '%s\n' "$fd" | awk '$4=="p"' | grep -c .)
		shm=$(printf '%s\n' "$fd" | awk '$4=="h"' | grep -c .)
		ot=$((total - v - so - pi - shm))
		# procstat -l columns: PID COMM RLIMIT SOFT HARD
		data=$(procstat -l "$p" 2>/dev/null | awk '$3=="data" {print $4"/"$5}')
		printf '| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' \
		    "$p" "$t" "${flags:-?}" "$total" "$v" "$so" "$pi" "$shm" "$ot" "${data:-?}"
	done

	for p in $pids; do
		t=$(proc_type "$p")
		section "Process $p: $t"
		printf 'Descriptors with capability rights (procstat -f -C):\n\n'
		code procstat -f -C "$p"
		printf '\nInherited environment variable names (values not recorded):\n\n'
		printf '```text\n'
		procstat -e "$p" 2>/dev/null | tail -n +2 | tr ' ' '\n' | \
		    sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' | sort -u | tr '\n' ' '
		printf '\n```\n'
	done
}

{
	printf '# Beryllium Phase 0 baseline\n\n'
	printf 'Collected %s UTC by freebsd/tools/baseline-collect.sh. ' \
	    "$(date -u '+%Y-%m-%d %H:%M')"
	printf 'Home directory, user name and host name are redacted.\n'
	collect_machine
	collect_packages
	collect_processes
} > "$out"

echo "wrote $out" >&2
