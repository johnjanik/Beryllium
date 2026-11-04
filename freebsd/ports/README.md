# Building Beryllium with Poudriere

`www/beryllium` is a Poudriere overlay port. It builds Beryllium from
Google's official Chromium `-lite` tarball, the imported FreeBSD patch set
(`files/patch-*`), Helium's patch series and tools (fetched at the commit the
`helium` submodule pins), and Beryllium's own patches (`files/beryllium/`).
`www/beryllium-devel` is the same build under a separate package name.

Status: **builds and runs**. The 16.0-CURRENT build of 3 November 2026 is
released as v0.20.3.1-1; what works and what is tested is in
`plan/13-FEATURE-MATRIX.md`.

`install.sh --build` at the top of the repository runs the steps below
for you (with `--dry-run` to see them first). Follow them by hand to
understand or adjust the setup.

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

Build in a jail with the **same FreeBSD major version as the machine you
will install on**: `pkg` refuses a package built for another major version
("wrong architecture: FreeBSD:15:amd64 instead of FreeBSD:16:amd64").
Create the jail that matches your machine; you can have both.

**16-CURRENT machine** (the project's build host). This downloads a recent
16.0-CURRENT snapshot of the base system:

```sh
doas poudriere jail -c -j 160amd64 -v 16.0-CURRENT -a amd64
```

A jail must not be newer than the running kernel. Compare the two numbers
these print; the first (the jail) must not be larger than the second (your
kernel):

```sh
grep -m1 '^#define __FreeBSD_version' /usr/local/poudriere/jails/160amd64/usr/include/sys/param.h
```

```sh
uname -K
```

If the jail is newer, update the machine to a current 16.0-CURRENT first,
or delete the jail (`doas poudriere jail -d -j 160amd64`) and build it from
the machine's own sources instead (about an hour):
`doas poudriere jail -c -j 160amd64 -b -m src=/usr/src -v 16.0-CURRENT`.

**FreeBSD 15.x machine** (the release target):

```sh
doas poudriere jail -c -j 151amd64 -v 15.1-RELEASE -a amd64
```

Check: `doas poudriere jail -l` lists the jail you created. The steps below
show both jails; use the one that matches your machine.

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

### Step 9 (root, then you): only after a Helium update

For Helium 0.20.3 this is done: `distinfo` pins every distfile, including
the Helium source archive (`imputnet-helium-2f81b9ca...`). Skip to step 10.

After the `helium` submodule moves to a new Helium release, `distinfo`
lacks the new Helium archive, which this project's automation cannot
download. Record it once, as below. This also downloads all the other
distfiles (about 2.2 GB, mostly the Chromium tarball) into the cache
Poudriere uses, so it takes a while.

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

Check: the diff changes only the two `imputnet-helium-...` lines (SHA256
and SIZE) and `TIMESTAMP`. Any change to an existing
SHA256 line means a downloaded file differs from what was pinned: stop and
send the diff. The Chromium tarball's line must stay
`d9e8b637dbdd3a1cccb4966e81a66e3f3c4c29f5ce9732a70f5a4f949cd03923`
(Google's published hash for `chromium-156.0.8078.79-lite.tar.xz`).

## Build

### Step 10 (root): build

16-CURRENT machine:

```sh
doas poudriere bulk -j 160amd64 -p default -O beryllium -b latest www/beryllium
```

FreeBSD 15.x machine:

```sh
doas poudriere bulk -j 151amd64 -p default -O beryllium -b latest www/beryllium
```

`-b latest` takes every dependency from the official `latest` package
repository, so only Beryllium itself is compiled. Expect several hours.

Check: the summary at the end says `Built: 1` (success) or `Failed: 1`.

Poudriere keeps one log directory per run; `latest` always points at the
current or most recent one. Progress of a running build (the newest
`[NN% step/total]` line; for the 15.x jail, write `151amd64` for
`160amd64`):

```sh
doas tail -1 /usr/local/poudriere/data/logs/bulk/160amd64-default/latest/logs/beryllium-0.20.3.2.log
```

`doas poudriere status` summarises the running build. If the build failed,
send that log file, or the part from the first `Error`, `FAILED` or `***`
line back to the start of that build phase (the phases are marked
`=======<phase: ...>`).

### Step 11 (root): install and run

16-CURRENT machine:

```sh
doas pkg add /usr/local/poudriere/data/packages/160amd64-default/All/beryllium-0.20.3.2.pkg
```

FreeBSD 15.x machine:

```sh
doas pkg add /usr/local/poudriere/data/packages/151amd64-default/All/beryllium-0.20.3.2.pkg
```

Then, as you:

```sh
beryllium
```

Beryllium uses `~/.config/beryllium` and `/usr/local/share/beryllium`, so it
does not touch a stock `chromium` installation or its profile.

### Testing a 15.x package on a 16-CURRENT machine

For release testing only; for everyday use, build in the 16-CURRENT jail.
Programs built for 15.x run on 16-CURRENT, but `pkg` needs to be told to
accept the package, and its dependencies should come from your machine's
own (16) repository rather than from Poudriere's 15.x copies.

As root, install the dependencies from the 16 repository:

```sh
doas pkg install -y $(pkg query -F /usr/local/poudriere/data/packages/151amd64-default/All/beryllium-0.20.3.2.pkg '%dn')
```

Then the package, accepting the 15.x ABI and OS version for this one
command (`OSVERSION` is the 15.1 value; without it `pkg` guesses 1500000 and
then asks whether to ignore the mismatch):

```sh
doas pkg -o ABI=FreeBSD:15:amd64 -o OSVERSION=1501000 add /usr/local/poudriere/data/packages/151amd64-default/All/beryllium-0.20.3.2.pkg
```

`pkg` may also print "Major OS version upgrade detected. Running pkg
bootstrap -f recommended". That is a side effect of the override; do not
run `pkg bootstrap -f` for it.

Check that every library is found (no output means all are):

```sh
ldd /usr/local/share/beryllium/beryllium | grep 'not found'
```

If a FreeBSD base library is reported missing, `doas pkg install
compat15x-amd64` provides the 15.x versions.

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
- **Branding.** The build installs Beryllium's icons and logos from
  `branding/` (see `branding/README.md`); Helium's generic page favicons are
  kept.

## Publishing a release (maintainer)

`install.sh` installs packages from this repository's GitHub releases, and
fetches itself from the `main` branch. After a successful build, bring
`main` up to date and push it, then publish from the top of your clone on
`main`. The release names the current commit as the package's source, so
that commit must contain the port the package was built from; commits that
change only documentation since the build are fine.

```sh
freebsd/tools/publish-release v0.20.3.2-1 /usr/local/poudriere/data/packages/160amd64-default/All/beryllium-0.20.3.2.pkg
```

Give it the packages from every jail you built (for example the 151amd64
one too). It names each `beryllium-FreeBSD-<major>-amd64.pkg`, writes
`SHA256SUMS` and release notes that name the commit as the corresponding
source, and creates the release with the GitHub CLI (`pkg install gh`,
then `gh auth login` once). `--draft` creates it unpublished, and
`--dry-run` only prepares the files. Without `gh`, it leaves the files in
a directory to upload on the releases page.

Before building the next release, raise the number in `revision.txt` at
the top of the repository and run `freebsd/tools/sync-port`, which writes
it into the port as `BERYLLIUM_REVISION` (for example 0.20.3.2 becomes 0.20.3.3). The
new package then has a higher version and `pkg` treats it as an update.
