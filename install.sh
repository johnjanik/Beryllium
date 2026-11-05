#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
#
# Beryllium Browser installer for FreeBSD (amd64).
#
# Download it, read it, then run it as your normal user (it asks for root
# through doas or sudo only for the steps that need it):
#
#   fetch -o install.sh https://raw.githubusercontent.com/johnjanik/Beryllium/main/install.sh
#   sh install.sh
#
# (curl -fsSL -o install.sh <same URL> works too.)
#
#   sh install.sh               install the published package for this
#                               machine's FreeBSD version
#   sh install.sh --build       build from source with Poudriere (several
#                               hours, about 100 GB of disk), then install
#   sh install.sh --uninstall   remove Beryllium (your profile stays)
#
# Options:
#   --dry-run       show every command that would change the system, and
#                   change nothing
#   --yes           do not ask for confirmation
#   --release TAG   install the package from release TAG (default: latest)
#   --dir PATH      where --build keeps the source (default: ~/Beryllium)
#   --branch NAME   branch --build uses (default: main)
#   --help          show this text

set -eu

REPO="johnjanik/Beryllium"
GIT_URL="https://github.com/${REPO}.git"
RELEASES="https://github.com/${REPO}/releases"
POUDRIERE_CONF="${BERYLLIUM_POUDRIERE_CONF:-/usr/local/etc/poudriere.conf}"  # override for tests

MODE=package
DRYRUN=0
YES=0
RELEASE=latest
SRCDIR="${HOME:-/root}/Beryllium"
BRANCH=main
TMPDIR_B=""

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
warn() { printf 'install.sh: warning: %s\n' "$*" >&2; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

usage() {
	sed -n '3,/^$/s/^# \{0,1\}//p' "$0"
	exit 0
}

cleanup() {
	if [ -n "$TMPDIR_B" ] && [ -d "$TMPDIR_B" ]; then
		rm -rf "$TMPDIR_B"
	fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

# Run a command that changes the system, or show it under --dry-run.
run() {
	if [ "$DRYRUN" = 1 ]; then
		printf '+ %s\n' "$*"
	else
		"$@"
	fi
}

# The same, with root privileges.
SU=""
as_root() {
	if [ "$(id -u)" = 0 ]; then
		run "$@"
	else
		run "$SU" "$@"
	fi
}

find_su() {
	[ "$(id -u)" = 0 ] && return 0
	if command -v doas >/dev/null 2>&1; then
		SU=doas
	elif command -v sudo >/dev/null 2>&1; then
		SU=sudo
	else
		die "run as root, or install and configure doas or sudo"
	fi
}

confirm() {
	[ "$YES" = 1 ] && return 0
	printf '%s [y/N] ' "$1"
	answer=""
	if [ -r /dev/tty ]; then
		read -r answer </dev/tty || answer=""
	else
		read -r answer || answer=""
	fi
	case "$answer" in
	[yY] | [yY][eE][sS]) return 0 ;;
	*) return 1 ;;
	esac
}

download() { # url file
	if command -v fetch >/dev/null 2>&1; then
		fetch -q -o "$2" "$1"
	elif command -v curl >/dev/null 2>&1; then
		curl -fsSL -o "$2" "$1"
	else
		die "neither fetch nor curl is available"
	fi
}

check_platform() {
	[ "$(uname -s)" = FreeBSD ] || die "Beryllium is for FreeBSD; this is $(uname -s)"
	[ "$(uname -m)" = amd64 ] || die "Beryllium is built for amd64; this machine is $(uname -m)"
	command -v pkg >/dev/null 2>&1 || die "pkg is not installed; run 'pkg bootstrap' as root first"
	ABI=$(pkg config ABI)
	MAJOR=$(printf '%s' "$ABI" | cut -d: -f2)
	case "$MAJOR" in
	'' | *[!0-9]*) die "cannot read the FreeBSD version from pkg's ABI ($ABI)" ;;
	esac
}

sandbox_notice() {
	cat <<'EOF'

Beryllium is a development build. It has no sandbox yet: like the stock
FreeBSD Chromium, by default no Beryllium process is confined, so a
compromised web page is not contained. Do not rely on it for sensitive
browsing.
EOF
}

# kern.ipc.shm_allow_removed must be 1, or the launcher refuses to start.
check_shm() {
	value=$(sysctl -n kern.ipc.shm_allow_removed 2>/dev/null || printf unknown)
	[ "$value" = 1 ] && return 0
	step "kern.ipc.shm_allow_removed is $value; Beryllium needs 1"
	if confirm "Set it now and keep it across reboots (/etc/sysctl.conf)?"; then
		as_root sysctl kern.ipc.shm_allow_removed=1
		as_root sysrc -f /etc/sysctl.conf kern.ipc.shm_allow_removed=1
	else
		say "Beryllium will not start until you set it:"
		say "  sysctl kern.ipc.shm_allow_removed=1"
		say "and add kern.ipc.shm_allow_removed=1 to /etc/sysctl.conf."
	fi
}

# Install a package file, taking its dependencies from the machine's own
# pkg repository (only those not yet installed).
install_pkg_file() { # file
	step "Dependencies"
	missing=""
	for dep in $(pkg query -F "$1" '%dn'); do
		pkg info -e "$dep" || missing="$missing $dep"
	done
	if [ -n "$missing" ]; then
		# shellcheck disable=SC2086 # one argument per package name
		as_root pkg install -y $missing
	else
		say "All dependencies are installed."
	fi
	step "Beryllium"
	if pkg info -e beryllium; then
		as_root pkg add -f "$1"
	else
		as_root pkg add "$1"
	fi
}

finish() {
	check_shm
	cat <<'EOF'

Done. Start Beryllium from your desktop menu, or run: beryllium
Profile: ~/.config/beryllium. Check its status at beryllium://version and
beryllium://gpu.
EOF
}

# ---------------------------------------------------------------------------

mode_package() {
	check_platform
	asset="beryllium-FreeBSD-${MAJOR}-amd64.pkg"
	if [ "$RELEASE" = latest ]; then
		base="${RELEASES}/latest/download"
	else
		base="${RELEASES}/download/${RELEASE}"
	fi
	TMPDIR_B=$(mktemp -d "${TMPDIR:-/tmp}/beryllium.XXXXXX")

	step "Fetching the release checksums ($RELEASE)"
	if ! download "${base}/SHA256SUMS" "$TMPDIR_B/SHA256SUMS"; then
		die "no published Beryllium release found at ${RELEASES} ($RELEASE).
Build it from source instead: sh install.sh --build"
	fi
	expected=$(awk -v f="$asset" '$2 == f || $2 == "*" f { print $1 }' "$TMPDIR_B/SHA256SUMS")
	if [ -z "$expected" ]; then
		say "This release has packages for:"
		awk '{ print "  " $2 }' "$TMPDIR_B/SHA256SUMS"
		die "none for FreeBSD ${MAJOR} (amd64). Build it from source: sh install.sh --build"
	fi

	step "Fetching $asset"
	download "${base}/${asset}" "$TMPDIR_B/$asset" || die "could not download $asset"
	actual=$(sha256 -q "$TMPDIR_B/$asset")
	[ "$actual" = "$expected" ] || die "checksum mismatch for $asset:
  expected $expected
  got      $actual
Nothing was installed."
	say "SHA-256 verified: $actual"

	pkgabi=$(pkg query -F "$TMPDIR_B/$asset" '%q')
	pkgname=$(pkg query -F "$TMPDIR_B/$asset" '%n-%v')
	[ "$pkgabi" = "$ABI" ] || die "$asset is for $pkgabi, but this machine is $ABI"
	say "Package: $pkgname for $pkgabi"

	sandbox_notice
	confirm "Install $pkgname?" || die "cancelled; nothing was installed"
	find_su
	install_pkg_file "$TMPDIR_B/$asset"
	finish
}

# ---------------------------------------------------------------------------

conf_get() { # key -> value from poudriere.conf, empty if unset
	[ -r "$POUDRIERE_CONF" ] || return 0
	# poudriere.conf is a shell fragment; read it the way poudriere does.
	# shellcheck disable=SC2016 # expanded by the inner shell
	sh -c '. "$1" >/dev/null 2>&1; eval "printf %s \"\${$2:-}\""' sh "$POUDRIERE_CONF" "$1"
}

ensure_tools() {
	missing=""
	# Any flavour counts: poudriere-devel, git-lite, any python3 provider.
	pkg info -e poudriere || pkg info -e poudriere-devel || missing="$missing poudriere"
	command -v git >/dev/null 2>&1 || missing="$missing git"
	command -v python3 >/dev/null 2>&1 || missing="$missing python3"
	if [ -n "$missing" ]; then
		step "Installing build tools:$missing"
		# shellcheck disable=SC2086 # one argument per package name
		as_root pkg install -y $missing
	fi
}

ensure_source() {
	step "Source in $SRCDIR"
	if [ -d "$SRCDIR/.git" ]; then
		url=$(git -C "$SRCDIR" remote get-url origin 2>/dev/null || true)
		case "$url" in
		*"$REPO"*) ;;
		*) die "$SRCDIR is a git checkout of '$url', not of $REPO; use --dir" ;;
		esac
		run git -C "$SRCDIR" fetch origin "$BRANCH"
		run git -C "$SRCDIR" checkout "$BRANCH"
		run git -C "$SRCDIR" merge --ff-only "origin/$BRANCH"
		run git -C "$SRCDIR" submodule update --init
	elif [ -e "$SRCDIR" ]; then
		die "$SRCDIR exists and is not a git checkout; use --dir"
	else
		run git clone --branch "$BRANCH" --recurse-submodules "$GIT_URL" "$SRCDIR"
	fi
	if [ "$DRYRUN" = 0 ]; then
		"$SRCDIR/freebsd/tools/sync-port" --check ||
			die "the port in $SRCDIR is out of sync with the repository"
	fi
}

# Settings from freebsd/ports/README.md step 4.
ensure_poudriere_conf() {
	step "Poudriere configuration ($POUDRIERE_CONF)"
	add=""
	if [ -z "$(conf_get ZPOOL)" ] && [ -z "$(conf_get NO_ZFS)" ]; then
		pools=$(zpool list -H -o name 2>/dev/null || true)
		if [ -z "$pools" ]; then
			add="${add}NO_ZFS=yes
"
		elif printf '%s\n' "$pools" | grep -qx zroot; then
			add="${add}ZPOOL=zroot
"
		elif [ "$(printf '%s\n' "$pools" | wc -l)" -eq 1 ]; then
			add="${add}ZPOOL=$pools
"
		else
			die "several ZFS pools ($(printf '%s' "$pools" | tr '\n' ' ')); set ZPOOL in $POUDRIERE_CONF and run again"
		fi
	fi
	for kv in BASEFS=/usr/local/poudriere DISTFILES_CACHE=/usr/ports/distfiles \
	    USE_TMPFS=no ALLOW_MAKE_JOBS=yes MAX_EXECUTION_TIME=172800 NOHANG_TIME=28800; do
		key=${kv%%=*}
		want=${kv#*=}
		have=$(conf_get "$key")
		case "$key" in
		BASEFS | DISTFILES_CACHE) [ -n "$have" ] && continue ;;
		MAX_EXECUTION_TIME | NOHANG_TIME)
			[ -n "$have" ] && [ "$have" -ge "$want" ] 2>/dev/null && continue ;;
		*) [ "$have" = "$want" ] && continue ;;
		esac
		add="${add}${kv}
"
	done
	if [ -z "$add" ]; then
		say "Already set up for Beryllium."
	else
		say "These settings will be added (a later line overrides an earlier one):"
		printf '%s' "$add" | sed 's/^/  /'
		confirm "Change $POUDRIERE_CONF (a backup is kept)?" ||
			die "cancelled; set these by hand (freebsd/ports/README.md step 4)"
		if [ -f "$POUDRIERE_CONF" ]; then
			as_root cp -p "$POUDRIERE_CONF" "$POUDRIERE_CONF.beryllium-backup"
		elif [ -f "$POUDRIERE_CONF.sample" ]; then
			as_root cp "$POUDRIERE_CONF.sample" "$POUDRIERE_CONF"
		fi
		block="# Added by the Beryllium installer
${add}"
		if [ "$DRYRUN" = 1 ]; then
			printf '+ append to %s:\n%s' "$POUDRIERE_CONF" "$block" | sed '2,$s/^/    /'
		else
			printf '%s' "$block" | as_root tee -a "$POUDRIERE_CONF" >/dev/null
		fi
	fi
	distfiles=$(conf_get DISTFILES_CACHE)
	as_root mkdir -p "${distfiles:-/usr/ports/distfiles}"
}

jail_exists() { poudriere jail -l -q 2>/dev/null | awk '{ print $1 }' | grep -qx "$1"; }
ports_exists() { poudriere ports -l -q 2>/dev/null | awk '{ print $1 }' | grep -qx "$1"; }

# A jail with the same FreeBSD version as this machine, so the package
# installs here (pkg refuses another major version).
ensure_jail() {
	version=$(freebsd-version -u | sed 's/-p[0-9]*$//')
	majmin=$(printf '%s' "$version" | cut -d- -f1 | tr -d .)
	case "$version" in
	*-RELEASE) JAIL="${majmin}amd64" ;;
	*-CURRENT) JAIL="${majmin}amd64" ;;
	*-STABLE) JAIL="${majmin}samd64" ;;
	*) die "unsupported FreeBSD version '$version' for a build jail" ;;
	esac
	step "Build jail $JAIL ($version)"
	if jail_exists "$JAIL"; then
		say "Jail $JAIL exists."
	else
		as_root poudriere jail -c -j "$JAIL" -v "$version" -a amd64
	fi
	[ "$DRYRUN" = 1 ] && return 0
	path=$(poudriere jail -l -q | awk -v j="$JAIL" '$1 == j { print $NF }')
	jailver=$(awk '/^#define __FreeBSD_version/ { print $3; exit }' "$path/usr/include/sys/param.h" 2>/dev/null || true)
	kernver=$(uname -K)
	if [ -n "$jailver" ] && [ "$jailver" -gt "$kernver" ]; then
		die "jail $JAIL ($jailver) is newer than the running kernel ($kernver).
Update this machine first, or recreate the jail from its own sources:
  $SU poudriere jail -d -j $JAIL
  $SU poudriere jail -c -j $JAIL -b -m src=/usr/src -v $version"
	fi
}

ensure_ports() {
	step "Ports trees"
	if ports_exists default; then
		say "Ports tree 'default' exists."
	elif [ -f /usr/ports/Mk/bsd.port.mk ]; then
		as_root poudriere ports -c -p default -m null -M /usr/ports
	else
		as_root poudriere ports -c -p default
	fi
	if ports_exists beryllium; then
		say "Ports tree 'beryllium' exists."
	else
		as_root poudriere ports -c -p beryllium -m null -M "$SRCDIR/freebsd/ports"
	fi
}

check_resources() {
	mem=$(sysctl -n hw.physmem)
	if [ "$mem" -lt 17179869184 ]; then
		warn "less than 16 GB of RAM; the build may fail or take much longer"
	fi
	base=$(conf_get BASEFS)
	base=${base:-/usr/local/poudriere}
	dir=$base
	while [ ! -d "$dir" ]; do dir=$(dirname "$dir"); done
	free=$(df -k "$dir" | awk 'NR == 2 { print $4 }')
	if [ "$free" -lt 104857600 ]; then
		warn "less than 100 GB free under $dir; the build needs about that much"
	fi
}

mode_build() {
	check_platform
	find_su
	cat <<'EOF'
This builds Beryllium from source with Poudriere: it installs poudriere, git
and python3 if needed, sets up Poudriere for the build, and compiles the
browser (several hours; run it inside tmux or screen so a closed terminal
does not stop it). Dependencies come as packages from the official FreeBSD
repository.
EOF
	sandbox_notice
	confirm "Continue?" || die "cancelled"
	ensure_tools
	check_resources
	ensure_source
	ensure_poudriere_conf
	ensure_jail
	ensure_ports

	step "Building (several hours)"
	base=$(conf_get BASEFS)
	say "Progress, from another terminal:"
	say "  $SU tail -1 ${base:-/usr/local/poudriere}/data/logs/bulk/${JAIL}-default/latest/logs/beryllium-*.log"
	as_root poudriere bulk -j "$JAIL" -p default -O beryllium -b latest www/beryllium

	if [ "$DRYRUN" = 1 ]; then
		say "+ pkg add <the new beryllium package>"
		finish
		return 0
	fi
	data=$(conf_get POUDRIERE_DATA)
	if [ -z "$data" ]; then
		base=$(conf_get BASEFS)
		data="${base:-/usr/local/poudriere}/data"
	fi
	# shellcheck disable=SC2012 # newest file by time; names have no spaces
	pkgfile=$(ls -t "$data/packages/${JAIL}-default/All/"beryllium-[0-9]*.pkg 2>/dev/null | head -1)
	[ -n "$pkgfile" ] || die "the build finished, but no beryllium package was found under $data/packages/${JAIL}-default/All"
	install_pkg_file "$pkgfile"
	finish
}

mode_uninstall() {
	command -v pkg >/dev/null 2>&1 || die "pkg is not installed"
	if ! pkg info -e beryllium; then
		say "Beryllium is not installed."
		return 0
	fi
	confirm "Remove Beryllium? Your profile in ~/.config/beryllium is kept." || die "cancelled"
	find_su
	as_root pkg delete -y beryllium
}

# ---------------------------------------------------------------------------

while [ $# -gt 0 ]; do
	case "$1" in
	--build) MODE=build ;;
	--uninstall) MODE=uninstall ;;
	--dry-run) DRYRUN=1 ;;
	--yes | -y) YES=1 ;;
	--release) shift; RELEASE=${1:?--release needs a tag} ;;
	--dir) shift; SRCDIR=${1:?--dir needs a path} ;;
	--branch) shift; BRANCH=${1:?--branch needs a name} ;;
	--help | -h) usage ;;
	*) die "unknown option '$1' (see --help)" ;;
	esac
	shift
done

[ "$DRYRUN" = 1 ] && say "Dry run: commands that would change the system are shown, not run."

case "$MODE" in
package) mode_package ;;
build) mode_build ;;
uninstall) mode_uninstall ;;
esac
