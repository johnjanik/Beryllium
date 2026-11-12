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
#   --verify-only   check the release's signature and the package, and
#                   install nothing
#   --allow-downgrade
#                   install the latest release although a newer version is
#                   installed
#   --allow-unsigned
#                   with --release TAG: install a release from before
#                   releases were signed (0.20.3.18 and earlier), checked
#                   against its checksum file only
#   --from URL      take the release's files from URL (a mirror, or
#                   file:///a/directory); they are verified the same way
#   --dir PATH      where --build keeps the source (default: ~/Beryllium)
#   --branch NAME   branch --build uses (default: main)
#   --ccache        with --build: keep a compiler cache (ccache), so the next
#                   build compiles only what changed. For test builds only:
#                   a release is built without it
#   --help          show this text

set -eu

REPO="johnjanik/Beryllium"
GIT_URL="https://github.com/${REPO}.git"
RELEASES="https://github.com/${REPO}/releases"
POUDRIERE_CONF="${BERYLLIUM_POUDRIERE_CONF:-/usr/local/etc/poudriere.conf}"  # override for tests

# Release signing (plan/18 section 5; freebsd/release-keys/README.md). A
# release carries RELEASE, which names it and lists the SHA-256 of its
# files, and RELEASE.sig, made with a key that is not on GitHub. The two
# lists below are freebsd/release-keys/allowed_signers and revoked_keys,
# line for line: this script is fetched alone, so it carries them.
SIGNER="release@beryllium"
SIGN_NAMESPACE="beryllium-release"
FIRST_SIGNED="0.20.3.19"
MANIFEST_MAX=65536 # bytes; a release manifest is a few hundred

# The last release made before releases were signed. This installer knows
# its FreeBSD 16 package by its SHA-256 (as GitHub served it on 12 November
# 2026), so that package installs by its name without a signature and
# nothing else can be passed off as it. It was also accepted as "the latest
# release" until the first signed one, 0.20.3.19, was published (12
# November 2026); since then the latest release has to be signed.
LAST_UNSIGNED_TAG="v0.20.3.18"
LAST_UNSIGNED_VERSION="0.20.3.18"
LAST_UNSIGNED_SHA256_16="0094119e7283cec3f8ff8a3388a615c4debc04738d513b63f8bc0f7981bb1c26"

allowed_signers() {
	cat <<'EOF'
release@beryllium namespaces="beryllium-release",valid-after="20261111",valid-before="20270101" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIsdyAeLdF0QS0/rhJhIO4pIgWgWY4kKoeVM5oOpYll3
EOF
}

revoked_keys() {
	cat <<'EOF'
EOF
}
POUDRIERE_D="$(dirname "$POUDRIERE_CONF")/poudriere.d"
CCACHE_SET=ccache # --ccache builds are Poudriere's set "ccache" (bulk -z ccache)
CCACHE_MAX=30G

MODE=package
DRYRUN=0
YES=0
RELEASE=latest
VERIFY_ONLY=0
ALLOW_DOWNGRADE=0
ALLOW_UNSIGNED=0
FROM=""
SRCDIR="${HOME:-/root}/Beryllium"
BRANCH=main
CCACHE=0
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

# The release's signed manifest, checked and taken apart. RELEASE reads:
#
#   beryllium-release 1
#   version 0.20.3.19
#   tag v0.20.3.19
#   commit <40 hex digits>
#   date 2026-11-12
#   sha256 <64 hex digits>  beryllium-FreeBSD-16-amd64.pkg
#   sha256 <64 hex digits>  BUILD-MANIFEST-FreeBSD-16-amd64.json
#
# Nothing in it is acted on before the signature has verified, and after
# that only lines of exactly these shapes: one of each field, a file name
# of letters, digits, dots, hyphens and underscores, one line a file.
# Anything else refuses the whole manifest. Output: the same fields, with
# "asset <digest> <name>" for each file.
parse_manifest() { # file
	LC_ALL=C awk '
	function bad(why) { print "install.sh: release manifest: " why > "/dev/stderr"; failed = 1; exit 1 }
	function hex(v, n) { return length(v) == n && v !~ /[^0-9a-f]/ }
	length($0) > 300 { bad("line " NR " is too long") }
	/[^ -~]/ { bad("line " NR " has a character that does not belong in a manifest") }
	NR == 1 {
		if ($0 != "beryllium-release 1")
			bad("not a Beryllium release manifest of a kind this installer knows")
		next
	}
	NF == 2 && ($1 == "version" || $1 == "tag" || $1 == "commit" || $1 == "date") {
		if (seen[$1]++) bad("two " $1 " lines")
		if ($1 == "version" && $2 !~ /^[0-9][0-9A-Za-z._,]*$/) bad("version is not a version")
		if ($1 == "tag" && $2 !~ /^v[0-9][0-9A-Za-z._-]*$/) bad("tag is not a release tag")
		if ($1 == "commit" && !hex($2, 40)) bad("commit is not a commit")
		if ($1 == "date" && $2 !~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/) bad("date is not a date")
		print $1, $2
		next
	}
	NF == 3 && $1 == "sha256" {
		if (!hex($2, 64)) bad("line " NR " has no SHA-256")
		if ($3 !~ /^[A-Za-z0-9][A-Za-z0-9._-]*$/) bad("line " NR " names a file this installer will not touch")
		if (named[$3]++) bad("two lines for " $3)
		print "asset", $2, $3
		assets++
		next
	}
	{ bad("line " NR " is not one this installer knows") }
	END {
		if (failed) exit 1
		if (NR == 0) { print "install.sh: release manifest: empty" > "/dev/stderr"; exit 1 }
		if (!seen["version"] || !seen["tag"] || !seen["commit"] || !seen["date"] || !assets) {
			print "install.sh: release manifest: a field is missing" > "/dev/stderr"
			exit 1
		}
	}' "$1"
}

manifest_field() { # name
	awk -v k="$1" '$1 == k { print $2; exit }' "$TMPDIR_B/RELEASE.fields"
}

# verify_signature FILE SIGNATURE: FILE was signed by a release key that is
# in the list, in its validity and not withdrawn. The answer is ssh-keygen's
# exit status, so nothing stands between the command and the test.
verify_signature() {
	command -v ssh-keygen >/dev/null 2>&1 ||
		die "ssh-keygen is needed to check the release's signature, and is not installed.
It is part of FreeBSD's base system; where that was built without OpenSSH,
'pkg install openssh-portable' provides it. Nothing was installed."
	allowed_signers >"$TMPDIR_B/allowed_signers"
	revoked_keys >"$TMPDIR_B/revoked_keys"
	if ssh-keygen -Y verify -f "$TMPDIR_B/allowed_signers" -I "$SIGNER" -n "$SIGN_NAMESPACE" \
	    -s "$2" -r "$TMPDIR_B/revoked_keys" <"$1" >"$TMPDIR_B/verify.out" 2>&1; then
		return 0
	fi
	return 1
}

# The release's manifest: fetched, its signature verified, read, and
# compared with what was asked for. Sets expected (the package's SHA-256)
# and m_version.
signed_release() { # base asset
	step "Fetching the signed release manifest ($RELEASE)"
	if ! download "$1/RELEASE" "$TMPDIR_B/RELEASE"; then
		if download "$1/SHA256SUMS" "$TMPDIR_B/SHA256SUMS" 2>/dev/null; then
			if known_unsigned_release "$2"; then
				return 0
			fi
			if [ "$RELEASE" = latest ]; then
				die "the latest release is not signed. Releases are signed from $FIRST_SIGNED on, and
this installer takes nothing else for the latest. The last release from
before that installs by its name:
  sh install.sh --release $LAST_UNSIGNED_TAG
Nothing was installed."
			fi
			die "this release ($RELEASE) is not signed. Releases are signed from $FIRST_SIGNED on,
and this installer installs nothing else unless told to. A release from
before that installs by name, checked against its checksum file only:
  sh install.sh --release $RELEASE --allow-unsigned
Nothing was installed."
		fi
		die "no published Beryllium release found at ${FROM:-$RELEASES} ($RELEASE).
Build it from source instead: sh install.sh --build"
	fi
	download "$1/RELEASE.sig" "$TMPDIR_B/RELEASE.sig" 2>/dev/null ||
		die "the release manifest has no signature beside it (RELEASE.sig). Nothing was installed."
	size=$(wc -c <"$TMPDIR_B/RELEASE" | tr -d ' ')
	[ "$size" -le "$MANIFEST_MAX" ] ||
		die "the release manifest is $size bytes; a real one is a few hundred. Nothing was installed."
	if ! verify_signature "$TMPDIR_B/RELEASE" "$TMPDIR_B/RELEASE.sig"; then
		tr -cd '[:print:]\n' <"$TMPDIR_B/verify.out" | sed 's/^/  ssh-keygen: /' >&2
		die "the signature on the release manifest does not verify against Beryllium's
release keys (freebsd/release-keys in the repository). Nothing was installed."
	fi
	say "Signature verified: $(grep -m1 '^Good ' "$TMPDIR_B/verify.out" | tr -cd '[:print:]')"
	parse_manifest "$TMPDIR_B/RELEASE" >"$TMPDIR_B/RELEASE.fields" ||
		die "the release manifest is signed but is not what this installer expects. Nothing was installed."
	m_version=$(manifest_field version)
	m_tag=$(manifest_field tag)
	say "Release: Beryllium $m_version ($m_tag), dated $(manifest_field date), source commit $(manifest_field commit)"
	if [ "$RELEASE" != latest ] && [ "$m_tag" != "$RELEASE" ]; then
		die "asked for release $RELEASE, and the signed manifest is that of $m_tag. Nothing was installed."
	fi
	expected=$(awk -v f="$2" '$1 == "asset" && $3 == f { print $2 }' "$TMPDIR_B/RELEASE.fields")
	if [ -z "$expected" ]; then
		say "This release has packages for:"
		awk '$1 == "asset" && $3 ~ /\.pkg$/ { print "  " $3 }' "$TMPDIR_B/RELEASE.fields"
		if [ "$VERIFY_ONLY" = 1 ]; then
			say "Signature and manifest verified. There is no package for FreeBSD ${MAJOR} (amd64) to check."
			exit 0
		fi
		die "none for FreeBSD ${MAJOR} (amd64). Build it from source: sh install.sh --build"
	fi
	if [ "$RELEASE" = latest ] && [ "$ALLOW_DOWNGRADE" = 0 ] && pkg info -e beryllium; then
		installed=$(pkg query '%v' beryllium)
		if [ "$(pkg version -t "$installed" "$m_version")" = '>' ]; then
			die "Beryllium $installed is installed, and the release offered as the latest is $m_version, which is older.
That is what a replayed old release looks like. To install it all the same:
  sh install.sh --allow-downgrade
Nothing was installed."
		fi
	fi
}

# The one unsigned release this installer knows by its package's SHA-256,
# when it is asked for by its name. Sets expected and m_version as
# signed_release does; the checksum file beside the package is not
# consulted.
known_unsigned_release() { # asset
	[ "$1" = "beryllium-FreeBSD-16-amd64.pkg" ] || return 1
	[ -z "$FROM" ] || return 1
	[ "$RELEASE" = "$LAST_UNSIGNED_TAG" ] || return 1
	cat <<EOF
Release $LAST_UNSIGNED_TAG is from before releases were signed (they are from
$FIRST_SIGNED on). This installer knows its package by its SHA-256 and
accepts that package only.
EOF
	expected=$LAST_UNSIGNED_SHA256_16
	m_version=$LAST_UNSIGNED_VERSION
	return 0
}

# A release from before releases were signed: its checksum file is all
# there is, and whoever can replace the package can replace that too.
unsigned_release() { # base asset
	cat <<EOF

NOT VERIFIED BY SIGNATURE (--allow-unsigned). Release $RELEASE is checked
against the checksum file published beside it and nothing more: whoever
could replace the package could replace that file as well.
EOF
	step "Fetching the release checksums ($RELEASE)"
	if ! download "$1/SHA256SUMS" "$TMPDIR_B/SHA256SUMS"; then
		die "no published Beryllium release found at ${FROM:-$RELEASES} ($RELEASE).
Build it from source instead: sh install.sh --build"
	fi
	expected=$(awk -v f="$2" '$2 == f || $2 == "*" f { print $1 }' "$TMPDIR_B/SHA256SUMS")
	if [ -z "$expected" ]; then
		say "This release has packages for:"
		awk '{ print "  " $2 }' "$TMPDIR_B/SHA256SUMS"
		die "none for FreeBSD ${MAJOR} (amd64). Build it from source: sh install.sh --build"
	fi
	m_version=""
}

mode_package() {
	check_platform
	asset="beryllium-FreeBSD-${MAJOR}-amd64.pkg"
	if [ -n "$FROM" ]; then
		base=${FROM%/}
	elif [ "$RELEASE" = latest ]; then
		base="${RELEASES}/latest/download"
	else
		base="${RELEASES}/download/${RELEASE}"
	fi
	TMPDIR_B=$(mktemp -d "${TMPDIR:-/tmp}/beryllium.XXXXXX")

	if [ "$ALLOW_UNSIGNED" = 1 ]; then
		unsigned_release "$base" "$asset"
	else
		signed_release "$base" "$asset"
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
	if [ -n "$m_version" ]; then
		pkgversion=$(pkg query -F "$TMPDIR_B/$asset" '%v')
		[ "$pkgversion" = "$m_version" ] ||
			die "the package says it is version $pkgversion, and the signed manifest says $m_version. Nothing was installed."
	fi
	say "Package: $pkgname for $pkgabi"

	if [ "$VERIFY_ONLY" = 1 ]; then
		say "Verified: the signature, the release's name and version, and the package. Nothing was installed (--verify-only)."
		return 0
	fi
	sandbox_notice
	confirm "Install $pkgname?" || die "cancelled; nothing was installed"
	find_su
	install_pkg_file "$TMPDIR_B/$asset"
	finish
}

# ---------------------------------------------------------------------------

conf_get() { # key [file] -> value from poudriere.conf (or file), empty if unset
	conf_file=${2:-$POUDRIERE_CONF}
	[ -r "$conf_file" ] || return 0
	# poudriere.conf is a shell fragment; read it the way poudriere does.
	# shellcheck disable=SC2016 # expanded by the inner shell
	sh -c '. "$1" >/dev/null 2>&1; eval "printf %s \"\${$2:-}\""' sh "$conf_file" "$1"
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

# Who Poudriere compiles as; the cache directory must belong to them.
build_owner() {
	if [ "$(conf_get BUILD_AS_NON_ROOT)" = no ]; then
		printf 'root:wheel'
		return 0
	fi
	user=$(conf_get PORTBUILD_USER)
	case "${user:-nobody}" in
	nobody) printf 'nobody:nobody' ;;
	root) printf 'root:wheel' ;;
	*) # Poudriere creates this user in the jail, by number
		uid=$(conf_get PORTBUILD_UID)
		uid=${uid:-65532}
		gid=$(conf_get PORTBUILD_GID)
		printf '%s:%s' "$uid" "${gid:-$uid}" ;;
	esac
}

# --ccache: a compiler cache (devel/ccache) for builds of the set "ccache",
# and for no other build. Poudriere reads <set>-poudriere.conf for that set
# alone, mounts CCACHE_DIR into the jail and switches the ports framework's
# ccache support on; the set has its own packages and logs. A build without
# --ccache does not read the file, so it stays a clean build.
ensure_ccache() {
	setconf="$POUDRIERE_D/${CCACHE_SET}-poudriere.conf"
	step "Compiler cache for the build set '$CCACHE_SET'"
	if [ -n "$(conf_get CCACHE_DIR)" ]; then
		warn "CCACHE_DIR is set in $POUDRIERE_CONF: every Poudriere build on this machine uses a compiler cache, also without --ccache"
	fi
	owner=$(build_owner)
	add=""
	CCACHE_PATH=$(conf_get CCACHE_DIR "$setconf")
	if [ -z "$CCACHE_PATH" ]; then
		base=$(conf_get BASEFS)
		CCACHE_PATH="${base:-/usr/local/poudriere}/ccache-beryllium"
		add="${add}CCACHE_DIR=$CCACHE_PATH
"
	fi
	# Without this Poudriere compiles as root whenever a cache is in use.
	if [ "$(conf_get CCACHE_DIR_NON_ROOT_SAFE "$setconf")" != yes ]; then
		add="${add}CCACHE_DIR_NON_ROOT_SAFE=yes
"
	fi
	cat <<EOF
A build with --ccache is a test build. It keeps what the compiler produced
(up to $CCACHE_MAX) in:
  $CCACHE_PATH
The next build with --ccache compiles only what changed. The package records
that a compiler cache was used, and freebsd/tools/publish-release refuses to
publish it: a release is built without --ccache.
The first build with --ccache also fetches the dependencies again, into the
set's own package directory.
EOF
	if [ -z "$add" ] && [ -d "$CCACHE_PATH" ]; then
		say "Already set up."
	else
		if [ -n "$add" ]; then
			say "These settings will be added to $setconf:"
			printf '%s' "$add" | sed 's/^/  /'
		fi
		[ -d "$CCACHE_PATH" ] || say "$CCACHE_PATH will be created, owned by $owner."
		confirm "Set up the compiler cache?" ||
			die "cancelled; build without --ccache, or set it up by hand (freebsd/ports/README.md)"
		if [ -n "$add" ]; then
			as_root mkdir -p "$POUDRIERE_D"
			block="# Added by the Beryllium installer (install.sh --build --ccache)
${add}"
			if [ "$DRYRUN" = 1 ]; then
				printf '+ append to %s:\n%s' "$setconf" "$block" | sed '2,$s/^/    /'
			else
				printf '%s' "$block" | as_root tee -a "$setconf" >/dev/null
			fi
		fi
		if [ ! -d "$CCACHE_PATH" ]; then
			as_root mkdir -p "$CCACHE_PATH"
			# ccache's own default is 5 GB, less than one build of the browser.
			if [ "$DRYRUN" = 1 ]; then
				printf '+ write %s: max_size = %s\n' "$CCACHE_PATH/ccache.conf" "$CCACHE_MAX"
			else
				printf 'max_size = %s\n' "$CCACHE_MAX" |
					as_root tee "$CCACHE_PATH/ccache.conf" >/dev/null
			fi
			as_root chown -R "$owner" "$CCACHE_PATH"
		fi
	fi
	if [ -d "$CCACHE_PATH" ]; then
		# shellcheck disable=SC2012 # owner and group as ls prints them
		have=$(ls -ld "$CCACHE_PATH" | awk '{ print $3 ":" $4 }')
		[ "$have" = "$owner" ] ||
			warn "$CCACHE_PATH belongs to $have, but Poudriere compiles as $owner: the cache may stay empty (chown -R $owner $CCACHE_PATH)"
	fi
}

ccache_report() {
	cat <<EOF

This package was built with a compiler cache: it is a test build, and
freebsd/tools/publish-release refuses it. Build a release without --ccache.
EOF
	if command -v ccache >/dev/null 2>&1; then
		say "The cache, all builds so far:"
		CCACHE_DIR="$CCACHE_PATH" ccache -s || true
	else
		say "To see how much of a build came from the cache, install ccache"
		say "on this machine (pkg install ccache) and run:"
		say "  CCACHE_DIR=$CCACHE_PATH ccache -s"
	fi
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
	# Poudriere names a build's packages and logs <jail>-<tree>[-<set>].
	master="${JAIL}-default"
	set --
	if [ "$CCACHE" = 1 ]; then
		ensure_ccache
		master="${master}-${CCACHE_SET}"
		set -- -z "$CCACHE_SET"
	fi

	step "Building (several hours)"
	base=$(conf_get BASEFS)
	say "Progress, from another terminal:"
	say "  $SU tail -1 ${base:-/usr/local/poudriere}/data/logs/bulk/${master}/latest/logs/beryllium-*.log"
	as_root poudriere bulk -j "$JAIL" -p default "$@" -O beryllium -b latest www/beryllium

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
	pkgfile=$(ls -t "$data/packages/${master}/All/"beryllium-[0-9]*.pkg 2>/dev/null | head -1)
	[ -n "$pkgfile" ] || die "the build finished, but no beryllium package was found under $data/packages/${master}/All"
	[ "$CCACHE" = 1 ] && ccache_report
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
	--verify-only) VERIFY_ONLY=1 ;;
	--allow-downgrade) ALLOW_DOWNGRADE=1 ;;
	--allow-unsigned) ALLOW_UNSIGNED=1 ;;
	--from) shift; FROM=${1:?--from needs a URL} ;;
	--dir) shift; SRCDIR=${1:?--dir needs a path} ;;
	--branch) shift; BRANCH=${1:?--branch needs a name} ;;
	--ccache) CCACHE=1 ;;
	--help | -h) usage ;;
	*) die "unknown option '$1' (see --help)" ;;
	esac
	shift
done

if [ "$CCACHE" = 1 ] && [ "$MODE" != build ]; then
	die "--ccache goes with --build"
fi
if [ "$ALLOW_UNSIGNED" = 1 ] && [ "$RELEASE" = latest ]; then
	die "--allow-unsigned goes with --release TAG: the latest release is always checked by its signature"
fi
if [ "$ALLOW_UNSIGNED" = 1 ] && [ "$VERIFY_ONLY" = 1 ]; then
	die "--verify-only checks a signature, and --allow-unsigned asks for none"
fi
if [ "$ALLOW_UNSIGNED" = 1 ] && [ -n "$FROM" ]; then
	die "--from takes files from a place of your choosing, so they must be signed: it does not go with --allow-unsigned"
fi
if [ "$MODE" != package ] && [ "$VERIFY_ONLY$ALLOW_DOWNGRADE$ALLOW_UNSIGNED$FROM" != 000 ]; then
	die "--verify-only, --allow-downgrade, --allow-unsigned and --from are for installing a release, not for --build or --uninstall"
fi
[ "$DRYRUN" = 1 ] && say "Dry run: commands that would change the system are shown, not run."

case "$MODE" in
package) mode_package ;;
build) mode_build ;;
uninstall) mode_uninstall ;;
esac
