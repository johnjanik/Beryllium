# Building Beryllium with Poudriere

`www/beryllium` is a Poudriere overlay port. It builds Beryllium from
Google's official Chromium `-lite` tarball, the imported FreeBSD patch set
(`files/patch-*`), Helium's patch series and tools (fetched at the commit the
`helium` submodule pins), and Beryllium's own patches (`files/beryllium/`).
`www/beryllium-devel` is the same build under a separate package name.

Status: **untested skeleton**. The first builds are expected to fail in
places (see "What to expect"); each failure log is the input for the next
fix.

## Requirements

- amd64, 16 GB RAM or more (128 GB is comfortable), about 100 GB free disk,
  1.5 million free inodes.
- `ports-mgmt/poudriere` 3.4 or newer (`-b` fetches dependency packages).
- A ports tree close to the one the BSD patches were imported from (ports
  commit in `www/beryllium/files/IMPORTED-FROM`); a current `main` works.

## One-time setup

All commands as root.

1. Poudriere configuration (`/usr/local/etc/poudriere.conf`), at least:

   ```sh
   ZPOOL=zroot            # or NO_ZFS=yes
   BASEFS=/usr/local/poudriere
   DISTFILES_CACHE=/usr/ports/distfiles
   USE_TMPFS=no           # the build tree is tens of GB
   ALLOW_MAKE_JOBS=yes
   MAX_EXECUTION_TIME=172800
   NOHANG_TIME=28800
   ```

2. A build jail for a release target. Packages built for 15.x run on a
   16-CURRENT host:

   ```sh
   poudriere jail -c -j 151amd64 -v 15.1-RELEASE -a amd64
   ```

3. The ports tree (reusing an existing git checkout of `/usr/ports`):

   ```sh
   poudriere ports -c -p default -m null -M /usr/ports
   ```

4. The Beryllium overlay (adjust the path to your clone):

   ```sh
   poudriere ports -c -p beryllium -m null -M /home/you/Beryllium/freebsd/ports
   ```

## Before each build

1. Make sure the port is in sync with the repository (CI checks this too):

   ```sh
   freebsd/tools/sync-port --check
   ```

2. `distinfo` pins every distfile except the Helium source archive, which
   this project's automation could not download. Record it once per Helium
   update (this also fetches the other distfiles into the cache Poudriere
   uses):

   ```sh
   make -C freebsd/ports/www/beryllium PORTSDIR=/usr/ports DISTDIR=/usr/ports/distfiles makesum
   ```

   Then check that only the Helium line was added and nothing else changed:

   ```sh
   git diff freebsd/ports/www/beryllium/distinfo
   ```

   Any change to an existing SHA256 line means a distfile differs from what
   was pinned: stop and report it. The Chromium tarball must match Google's
   published hash, `d9e8b637dbdd3a1cccb4966e81a66e3f3c4c29f5ce9732a70f5a4f949cd03923`
   for `chromium-156.0.8078.79-lite.tar.xz`.

## Build

```sh
poudriere bulk -j 151amd64 -p default -O beryllium -b latest www/beryllium
```

`-b latest` takes every dependency from the official `latest` package
repository, so only Beryllium itself is compiled. The log is under
`/usr/local/poudriere/data/logs/bulk/151amd64-default-beryllium/latest/logs/`.

To keep the work directory of a failed build for inspection, add `-k` and
`-i` (interactive) or set `KEEP_FAILED_WRKDIR` style options; the log alone
is usually enough.

## Install and run

```sh
pkg add /usr/local/poudriere/data/packages/151amd64-default-beryllium/All/beryllium-0.20.3.1.pkg
```

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

Send the failing part of the log (from the first `Error` or `FAILED` line
back to the start of that step) and it becomes the next fix.
