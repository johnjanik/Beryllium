# Beryllium: Source Layering and Patch Strategy

**Status:** Draft plan, no code written
**Date:** 18 October 2026
**Depends on:** [01-PROJECT-CHARTER.md](01-PROJECT-CHARTER.md) decisions D1 and D4

---

## 1. The problem

Beryllium has to combine four patch sources that were never designed to be
applied together, on one Chromium tree, in an order that is reproducible from a
clean FreeBSD port build:

| Source | Form | Applied by | Count at snapshot |
|---|---|---|---|
| Helium product patches (includes ungoogled-chromium, Inox, Iridium, Bromite, Debian, Brave patches) | quilt-style unified diffs listed in `helium/patches/series`, `-p1` | `utils/patches.py apply` | 347 files, 370-line series |
| FreeBSD BSD adaptations | `files/patch-<path with _ for />` unified diffs, `-p0` style (`--- file.orig` / `+++ file`) | FreeBSD ports framework `do-patch` | 1,659 files for Chromium 154 |
| OpenBSD BSD adaptations (origin of most of the above) | OpenBSD ports `patches/patch-*` | OpenBSD ports framework | tracks Chromium 155 |
| Beryllium security and platform patches | new, quilt-style, listed in `patches/series` | `helium/utils/patches.py apply` (second patch directory) | none yet |

Plus two tree rewrites that are not patches: Helium's binary pruning
(`pruning.list`, 1.26 MB of paths) and domain substitution
(`domain_substitution.list`, 17,490 entries, `domain_regex.list`), both of which
assume the file layout of Helium's prepared tarball.

## 2. Existing precedent: how `www/ungoogled-chromium` does it

The FreeBSD `www/ungoogled-chromium` port is the only existing example of the
ungoogled tooling inside the ports framework. Its Makefile runs, in
`pre-patch`, on the official `chromium-<ver>-lite.tar.xz`:

1. `utils/prune_binaries.py ${WRKSRC} pruning.list`
2. `PATCH_BIN=gpatch utils/patches.py apply ${WRKSRC} patches`
3. `utils/domain_substitution.py apply -r domain_regex.list -f domain_substitution.list -c ${WRKSRC}/domsubcache.tar.gz ${WRKSRC}`

and then the framework applies `files/patch-*`, which is a near-verbatim copy
of `www/chromium/files/` (1,602 files versus 1,659; the difference is the
subset that no longer applied or was not needed). The GN flags from
ungoogled's `flags.gn` are copied into the Makefile by hand ("sync with
flags.gni" comment).

What this precedent teaches:

- The ungoogled tooling works unmodified inside a port build. Python is a
  `PATCH_DEPENDS`, `gpatch` is required.
- Copying the BSD patch directory is a maintenance trap: the ungoogled port is
  three Chromium majors behind the main port precisely because every update
  means re-copying and re-fuzzing 1,600 files by hand.
- Hand-copying `flags.gn` into the Makefile invites drift. Beryllium will
  generate the GN args from `flags.gn` plus a FreeBSD fragment instead.

## 3. Beryllium layering order

The final tree is built in six stages. Each stage is reproducible on its own
and leaves a marker so the next one can refuse to run twice.

```text
Stage 0  Extract Chromium source tarball                    (ports: do-extract)
Stage 1  Prune binaries                        pruning.list (ports: pre-patch)
Stage 2  Apply BSD platform patches            files/patch-* (ports: do-patch)
Stage 3  Apply Helium series                   helium/patches/series (ports: post-patch)
Stage 4  Apply Beryllium series                patches/series (ports: post-patch)
Stage 5  Domain substitution                   domain_substitution.list (ports: post-patch)
Stage 6  Name substitution (Chromium -> Helium) utils/name_substitution.py --sub (ports: post-patch)
Stage 7  i18n, version, resources, downloaded deps (ports: post-patch / pre-configure)
```

Stages 1, 3, 5, 6 and 7 are exactly helium-linux's `shared.sh` sequence
(prune, patches, domsub, name substitution, i18n, version, resources); stage 2
and stage 4 are the Beryllium insertions.

Why this order and not the ungoogled port's order:

- **BSD patches before Helium patches (stage 2 before 3).** The BSD set is
  imported from FreeBSD/OpenBSD and must keep applying to a pristine Chromium
  tree so it can be re-synced mechanically. Helium's 347 patches are the
  smaller and more actively curated set, and Helium's maintainers already
  refresh them against every Chromium bump; rebasing them over the BSD set is
  the cheaper direction. Conflicts between the two are expected to be rare,
  since Helium's patches touch UI, prefs and services while the BSD set touches
  `base/`, `sandbox/`, build files and `*_linux.cc`; the 2 Helium patches that
  touch Linux-specific files (`chrome/common/chrome_paths_linux.cc`,
  `components/crash/core/app/crashpad_linux.cc`,
  `chrome/browser/ui/color/linux/native_chrome_color_mixer_linux.cc`,
  `chrome/common/importer/firefox_importer_utils_linux.cc`,
  `chrome/browser/extensions/api/messaging/launch_context_posix.cc`) are the
  first candidates for the conflict matrix.
- **Beryllium security patches after both (stage 4).** The Capsicum code
  modifies `sandbox/policy/freebsd/sandbox_freebsd.cc`, a file that only exists
  after the BSD patch that creates it. It also touches process launching and
  shared memory, which the BSD set modifies.
- **Domain substitution last (stage 5).** Substitution rewrites Google
  hostnames across the tree into `qjz9zk` placeholders. Running it last means
  the BSD patches cannot reintroduce unsubstituted hostnames and the
  substitution list only ever has to match one final layout. The FreeBSD port's
  own `google_api_key` is dropped, not substituted; see
  [07-PRIVACY-INVARIANTS-PLAN.md](07-PRIVACY-INVARIANTS-PLAN.md).

This differs from the ungoogled port, which patches before the BSD set and
substitutes before the BSD set. The choice is deliberate and must be validated
in Phase 1 by building both orders once if stage 3 produces more than a handful
of conflicts; the roadmap budgets that experiment.

## 4. Where each layer lives in the repository

```text
Beryllium/
  helium/                             # submodule: Helium's patches/series, flags.gn, lists, utils/ (never edited)
  patches/
    series                            # Beryllium series, applied after helium/patches/series
    platform/                         # FreeBSD counterparts of helium-linux's 7 platform patches
                                      # (branding, binary rename, default theme, crash, paths)
    branding/                         # Beryllium naming, icons, credits
    security/
      capsicum/                       # renderer and utility confinement
      launcher/                       # descriptor hygiene at child launch
      shm/                            # capability-safe shared memory
      diagnostics/                    # chrome://sandbox status, structured failure logs
  flags.freebsd.gn                    # FreeBSD GN fragment
  revision.txt                        # Beryllium platform revision
  freebsd/ports/www/beryllium/
    Makefile, distinfo, pkg-descr, pkg-plist, pkg-message
    files/
      patch-*                         # imported BSD set, never hand-edited
      beryllium.in, beryllium.desktop.in
    files/IMPORTED-FROM               # FreeBSD ports commit + OpenBSD ports commit + date
  freebsd/tools/
    import-bsd-patches                # sync files/patch-* from a ports checkout, record provenance
    gnargs-from-flags                 # emit GN args from helium/flags.gn + flags.freebsd.gn
    patch-matrix                      # produce the conflict matrix (section 6)
    build-manifest                    # emit the per-build provenance manifest
```

Rules:

1. `files/patch-*` is write-only for the import tool. A FreeBSD-specific fix
   that is not yet in FreeBSD ports goes into `patches/platform/` and
   is submitted upstream to `chromium@FreeBSD.org`; when it lands, the next
   import removes the local copy.
2. Every Beryllium patch starts with a header block: purpose, which stage it
   depends on, upstream bug or thread if any, the Chromium revision it was last
   refreshed against, and the test that covers it. Helium's
   `devutils/validate_patches.py` and `check_patch_files.py` are extended to
   require that header for Beryllium's `patches/` (run from the submodule
   against Beryllium's directory, never by editing Helium's copies).
3. A patch that touches process creation, IPC, descriptor passing, shared
   memory, the GPU process, the network service or sandbox setup carries a
   `security-review: required` line and cannot merge without a second reader
   (spec section 14).

## 5. Importing the BSD set

The FreeBSD port's `files/` and the OpenBSD port's `patches/` are the same
lineage; FreeBSD's copies carry the OpenBSD `.orig` timestamps, and the files
`patch-sandbox_policy_openbsd_sandbox__openbsd.{cc,h}` are present in the
FreeBSD port unchanged. At the snapshot OpenBSD is at Chromium 155 and FreeBSD
at 154, so the first import for Beryllium will combine:

- the OpenBSD 155 set, converted to FreeBSD naming
  (`patch-path_with_underscores`) and `-p0` form, as the base, and
- the FreeBSD-only deltas from the 154 set (anything in FreeBSD's `files/`
  whose OpenBSD counterpart is absent or different: FreeBSD-specific files such
  as `patch-base_process_process__metrics__freebsd.cc`,
  `patch-base_system_sys__info__freebsd.cc`, the `sandbox_freebsd.*` stub, the
  ALSA/OSS and `libepoll-shim` bits, and anything referencing `${LOCALBASE}`).

The import tool records the two source commits and produces three lists:
applied cleanly, applied with fuzz, failed. Fuzzed and failed patches are
reviewed by hand and the result is committed with the provenance file. From
then on the FreeBSD port's own catch-up to 155 (which will happen on its own
schedule) is diffed against Beryllium's import and reconciled.

When Beryllium and FreeBSD are on the same Chromium version, the import is a
straight copy and the OpenBSD step is skipped.

## 6. The patch conflict matrix

Phase 0 produces `freebsd/PATCH-MATRIX.md`, generated by `freebsd/tools/patch-matrix`.
One row per (patch, file) pair where more than one layer touches the same file:

| Column | Meaning |
|---|---|
| File | Chromium path |
| Layers | Which of BSD / Helium / Beryllium touch it |
| Hunk overlap | none / adjacent / overlapping (computed from hunk ranges) |
| Semantic risk | none / build-only / behavioural (hand-assessed) |
| Resolution | which layer owns the merged hunk, or "split" |
| Test | the test that proves the merged behaviour |

The matrix is regenerated on every Chromium bump and the diff is part of the
update review. Rows with behavioural risk that have no test block the update.

Expected hot spots, from the file inventories collected at the snapshot:

- `components/crash/core/app/crashpad_linux.cc` and the crashpad `BUILD.gn`
  files: Helium's `crash-reporter-privacy-tweaks` and `crash-reporting-prefs`
  versus the BSD crashpad build patches. Beryllium's platform decision (crash
  uploads off, local dumps on) is implemented here.
- `chrome/common/chrome_paths_linux.cc`: Helium's profile naming versus the BSD
  path patches. Beryllium's profile directory name goes here too.
- `sandbox/policy/sandbox_type.cc` and the `*_sandbox_hook_linux.cc` files:
  BSD stubs versus the Capsicum policies.
- `base/memory/platform_shared_memory_region_posix.cc`: BSD adds the
  `executable` parameter; Beryllium changes the creation path to a
  capability-safe one.
- `content/browser/child_process_launcher_helper_linux.cc`: BSD removes the
  zygote; Beryllium adds descriptor hygiene at launch.

## 7. Refresh procedure per Chromium update

1. Helium publishes a release tag with a new `chromium_version.txt` and a
   refreshed series. Beryllium moves the `helium` submodule to that tag; there
   is no merge.
2. Fetch the new Chromium tarball, run stages 0 to 1.
3. Re-import the BSD set for the new version (section 5). If neither BSD port
   has reached the version yet, Beryllium waits unless a security advisory
   forces the update, in which case the maintainer forward-ports the failing
   BSD patches by hand and tags the build as `prerelease`.
4. Apply stage 3 and 4 with `utils/patches.py apply`; refresh failed patches
   with quilt as Helium's CONTRIBUTING guide describes.
5. Regenerate the matrix and `flags` diff; review both.
6. Run the sandbox and privacy regression suites
   ([08-TESTING-AND-VERIFICATION.md](08-TESTING-AND-VERIFICATION.md)).
7. Update `freebsd/ports/www/beryllium/distinfo`, bump the platform revision,
   write the build manifest, tag.

## 8. Upstreaming policy

| Change type | Destination |
|---|---|
| Generic FreeBSD build or runtime fix | FreeBSD ports `www/chromium` (and OpenBSD when relevant), via `chromium@FreeBSD.org` |
| Capsicum sandbox implementation | Beryllium first; offered to FreeBSD ports once stable, since `www/chromium` would benefit directly. Chromium upstream acceptance is unlikely without a Chromium-side owner and is not planned. |
| Helium feature adaptations that are platform-neutral | Pull request to `imputnet/helium` following its CONTRIBUTING rules (issue first for non-trivial changes) |
| Beryllium branding and policy defaults | Stay in Beryllium |
