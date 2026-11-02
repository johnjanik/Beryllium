# Building Beryllium with Poudriere

`www/beryllium` is a Poudriere overlay port. It builds Beryllium from
Google's official Chromium `-lite` tarball, the imported FreeBSD patch set
(`files/patch-*`), Helium's patch series and tools (fetched at the commit the
`helium` submodule pins), and Beryllium's own patches (`files/beryllium/`).
`www/beryllium-devel` is the same build under a separate package name.

Status: **untested skeleton**. The first builds are expected to fail in
places (see "What to expect"); each failure log is the input for the next
fix.

## How to read the steps

- **Where:** every command runs from the top of your clone,
  `~/Beryllium`, unless the step says otherwise. Repository paths such as
  `freebsd/tools/sync-port` are relative to it.
- **Who:** steps marked *you* run as your normal user. Steps marked *root*
  need root; they are written with `doas`. Use `sudo` instead if that is
  what you have set up, or run them from a root shell (then type the path
  to your clone instead of `$HOME`).
- **Check:** each step ends with what you should see. If you see something
  else, stop there and send the output.

## Requirements

- amd64, 16 GB RAM or more (128 GB is comfortable), about 100 GB free disk,
  1.5 million free inodes.
- A ports tree in `/usr/ports` (a git checkout of the FreeBSD ports `main`
  branch is fine).

## One-time setup

### Step 1 (you): get the current code

```sh
cd ~/Beryllium
```

```sh
git checkout main && git pull && git submodule update --init
```

Check: `git -C helium describe --tags` prints `0.20.3`.

### Step 2 (root): host tools

```sh
doas pkg install -y poudriere git python3
```

Check: `poudriere version` prints 3.4 or newer, and `python3 --version`
prints a version.

### Step 3 (you): the port is in sync with the repository

```sh
freebsd/tools/sync-port --check
```

Check: `sync-port: port inputs are up to date`.

### Step 4 (root): Poudriere configuration

Find out whether the machine uses ZFS and what the pool is called:

```sh
zpool list -H -o name
```

Then edit `/usr/local/etc/poudriere.conf` (as root) so it contains these
lines. Use the pool name printed above for `ZPOOL`; if the command printed
nothing or failed, use `NO_ZFS=yes` instead of the `ZPOOL` line.

```sh
ZPOOL=zroot
BASEFS=/usr/local/poudriere
DISTFILES_CACHE=/usr/ports/distfiles
USE_TMPFS=no
ALLOW_MAKE_JOBS=yes
MAX_EXECUTION_TIME=172800
NOHANG_TIME=28800
```

`USE_TMPFS=no` because the build tree is tens of GB. The two time limits
allow a long first build.

Create the distfiles directory if it does not exist:

```sh
doas mkdir -p /usr/ports/distfiles
```

Check: `grep -E '^(ZPOOL|NO_ZFS|BASEFS|DISTFILES_CACHE|USE_TMPFS|ALLOW_MAKE_JOBS)' /usr/local/etc/poudriere.conf`
shows your values.

### Step 5 (root): a build jail

A FreeBSD 15.1 jail, because 15.x is a release target and packages built
for 15.x run on a 16-CURRENT host. This downloads the 15.1 base system.

```sh
doas poudriere jail -c -j 151amd64 -v 15.1-RELEASE -a amd64
```

Check: `doas poudriere jail -l` lists `151amd64` with version
`15.1-RELEASE`.

### Step 6 (root): the ports tree

Reuse your existing `/usr/ports` checkout:

```sh
doas poudriere ports -c -p default -m null -M /usr/ports
```

Check: `doas poudriere ports -l` lists `default` with method `null`.

### Step 7 (root): the Beryllium overlay

`$HOME` is expanded by your shell before `doas` runs, so this points at your
clone:

```sh
doas poudriere ports -c -p beryllium -m null -M "$HOME/Beryllium/freebsd/ports"
```

Check: `doas poudriere ports -l` now also lists `beryllium`.

## Before each build

### Step 8 (you): the port is still in sync

Repeat step 3 after every `git pull`:

```sh
freebsd/tools/sync-port --check
```

### Step 9 (root, then you): record the Helium archive checksum

`distinfo` pins every distfile except the Helium source archive, which this
project's automation could not download. Record it once per Helium update.
This also downloads all the other distfiles (about 2.2 GB, mostly the
Chromium tarball) into the cache Poudriere uses, so it takes a while.

```sh
doas make -C freebsd/ports/www/beryllium PORTSDIR=/usr/ports DISTDIR=/usr/ports/distfiles makesum
```

`makesum` rewrote `distinfo` as root; give it back to yourself:

```sh
doas chown "$(id -un)" freebsd/ports/www/beryllium/distinfo
```

Then check that only the Helium lines and the timestamp changed:

```sh
git diff freebsd/ports/www/beryllium/distinfo
```

Check: the diff adds two lines for `imputnet-helium-2f81b9ca...` (SHA256
and SIZE) and changes `TIMESTAMP`, nothing else. Any change to an existing
SHA256 line means a downloaded file differs from what was pinned: stop and
send the diff. The Chromium tarball's line must stay
`d9e8b637dbdd3a1cccb4966e81a66e3f3c4c29f5ce9732a70f5a4f949cd03923`
(Google's published hash for `chromium-156.0.8078.79-lite.tar.xz`).

## Build

### Step 10 (root): build

```sh
doas poudriere bulk -j 151amd64 -p default -O beryllium -b latest www/beryllium
```

`-b latest` takes every dependency from the official `latest` package
repository, so only Beryllium itself is compiled. Expect several hours.

Check: the summary at the end says `Built: 1` (success) or `Failed: 1`.

If it failed, find the log:

```sh
find /usr/local/poudriere/data/logs/bulk -name 'beryllium-*.log' | tail -1
```

and send the part from the first `Error`, `FAILED` or `***` line back to
the start of that build phase (the phases are marked `=======<phase: ...>`).

### Step 11 (root): install and run

```sh
doas pkg add "$(find /usr/local/poudriere/data/packages -name 'beryllium-*.pkg' | tail -1)"
```

Then, as you:

```sh
beryllium
```

Beryllium uses `~/.config/beryllium` and `/usr/local/share/beryllium`, so it
does not touch a stock `chromium` installation or its profile.

## What to expect from the first builds

- **BSD patches against a newer point release.** The imported set is for
  Chromium 156.0.8078.47; Beryllium builds 156.0.8078.79. A few patches may
  need fuzz or a refresh.
- **Helium patches against the `-lite` tarball.** Helium's patches and lists
  are made against Helium's own tarball. A patch that touches a file the
  `-lite` tarball lacks fails in `post-patch`; `tools/prune-existing` already
  handles absent pruning entries, and domain substitution skips absent
  files.
- **Packing list.** Helium adds components (for example the uBlock Origin
  fork) that may install files `pkg-plist` does not list yet. `stage-qa`
  and `check-plist` will name them.
- **Icons.** The build currently installs Helium's icons; replacing them with
  Beryllium's is a branding task before any package is shared.
