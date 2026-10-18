# Beryllium: Project Charter

**Status:** Draft plan, no code written
**Date:** 18 October 2026
**Companion spec:** [helium-freebsd-security-port-spec.md](../helium-freebsd-security-port-spec.md)
**Project repository:** https://github.com/johnjanik/Beryllium (standalone platform repository; Helium is a pinned git submodule from https://github.com/imputnet/helium)

---

## 1. What Beryllium is

Beryllium is a native FreeBSD build of the Helium browser with a FreeBSD-native
process confinement model added on top. It keeps Helium's product behaviour
(privacy defaults, the bundled uBlock Origin fork, `!bangs`, onboarding, the
"noise" fingerprinting defences, Helium services integration) and replaces the
effectively absent FreeBSD Chromium sandbox with a layered design built around
Capsicum capability mode for renderers, optional jails as an outer perimeter,
calibrated resource limits, and a separately gated MAC study.

The name follows Helium's periodic-table theme: helium is element 2, beryllium
is element 4.

The spec document already defines the goals, non-goals, threat model, security
requirements and phase structure. This charter does not repeat them. It records
the decisions and facts that the spec left open and that the research snapshot
of 18 October 2026 resolved, and it sets the ground rules for the repository.

## 2. Upstreams and what each one contributes

| Upstream | What Beryllium takes from it | Current state (18 Oct 2026) |
|---|---|---|
| Chromium | The browser engine. Beryllium builds exactly the Chromium revision Helium pins. | Helium main pins `155.0.8059.84`. |
| Helium (`imputnet/helium`) | Product patches (347 patch files in `patches/`), `flags.gn`, pruning and domain-substitution lists, bundled uBlock fork, onboarding, branding, i18n (81 languages), the ungoogled-chromium derived build tooling in `utils/`. | main at commit `832faa78`, revision 4. Version scheme is `version.txt`.`(chromium_major - 136)`.`revision.txt`, so main is Helium 0.19.4. |
| Helium platform repos (`helium-linux`, `helium-macos`, `helium-windows`) | The shape of a platform packaging repo: a build wrapper that prepares the Chromium tree with the shared tooling and then builds, plus a small platform patch series (helium-linux has 7: branding, binary rename, default theme, flags). Beryllium is the FreeBSD equivalent of these. | Latest platform tag 0.19.4.1 (16 Oct 2026). Linux and macOS are the recommended development platforms. Upstream closed a FreeBSD port request (imputnet/helium issue 773, January 2026) as "not planned" for lack of bandwidth, so Beryllium is an independent downstream, not an upstream platform. |
| Helium prepared tarballs (`imputnet/chromium-tarballs`) | `chromium-<ver>-base.tar.zst` (1.96 GB compressed, 8.6 GB and 587k files unpacked), a pinned `gclient` checkout with hooks run, shared by every Helium host; per-host layers add Google's prebuilt toolchains and Linux sysroots. Helium's `pruning.list` and `domain_substitution.list` are regenerated in CI against the base layer. Per-file sha256 manifests and `.hashes` files are on GitHub releases; archives are hosted on `tarballs.imput.net`. | Built automatically within hours of every Chromium stable release. No BSD host layer exists and none is needed, since FreeBSD uses host toolchains. |
| ungoogled-chromium | The patch application, binary pruning and domain substitution tooling that Helium inherited and extended. Also the proof that this tooling works inside a FreeBSD port (`www/ungoogled-chromium`). | FreeBSD's `www/ungoogled-chromium` is at `151.0.7922.169`, three Chromium majors behind the main port. |
| FreeBSD Ports `www/chromium` | The FreeBSD port skeleton (Makefile, options, dependencies, install layout), 1,659 `files/patch-*` BSD adaptations, the build environment conventions (LLVM 22, Rust, Node, Go, system libraries), and the `sandbox/policy/freebsd/` stub that Beryllium will replace. | `154.0.8037.57_2`, maintained by `chromium@FreeBSD.org`. |
| OpenBSD Ports `www/chromium` | The origin of most BSD patches (the FreeBSD files carry the same `.orig` timestamps), the pledge/unveil sandbox implementation that is the closest working analogue of what Beryllium wants to do with Capsicum, and the per-process `unveil.*`/`pledge.*` policy files. | `155.0.8059.84`, the same Chromium revision Helium pins. Maintained by Robert Nagy. |

The important consequence: at this snapshot, the BSD patch set already exists
for Helium's exact Chromium revision, but on OpenBSD, not FreeBSD. Forward
porting BSD fixes to 155 is therefore mostly a matter of taking the OpenBSD 155
set and re-applying the FreeBSD-specific deltas, not of rebasing from scratch.
This must be re-verified on the day work starts because all three move weekly.

## 3. Decisions recorded by this charter

Each decision below is a recommendation with the reason. Items marked
**needs owner sign-off** are product or legal choices that only the project
owner can make; the plan proceeds under the stated default until overruled.

### D1. Platform repository with Helium as a pinned submodule

`johnjanik/Beryllium` is a standalone repository, not a GitHub fork. It is the
FreeBSD sibling of Helium's own platform repositories (`helium-linux`,
`helium-macos`, `helium-windows`), and it follows their structure: Helium
itself is a git submodule pinned at a release tag, and everything else in the
repository is Beryllium-owned.

```text
Beryllium/
  helium/                     # git submodule: imputnet/helium at a release tag (0.19.4 on 18 Oct 2026)
  patches/
    series                    # Beryllium series, applied after helium/patches/series
    platform/                 # FreeBSD counterparts of helium-linux's platform patches
    branding/                 # Beryllium naming, icons, credits
    security/                 # Capsicum, launcher hygiene, shared memory, diagnostics
  flags.freebsd.gn            # FreeBSD GN fragment, appended to helium/flags.gn
  revision.txt                # Beryllium platform revision (HELIUM_PLATFORM)
  freebsd/
    ports/www/beryllium/      # the FreeBSD port, usable as an overlay or submitted upstream
    sandbox/                  # Capsicum design notes, descriptor inventories, policy data
    tests/                    # sandbox, privacy and functional test suites
    tools/                    # sync scripts (import BSD patches, diff flags, build manifest)
    branding/                 # logo and icon sources
  plan/                       # these planning documents
  README.md, LICENSE
```

Rules:

- Nothing inside `helium/` is ever edited. Every change to Helium's behaviour
  is a patch in `patches/`, applied after Helium's own series by Helium's
  `utils/patches.py`, which accepts several patch directories in order exactly
  as helium-linux uses it.
- Updating Helium means moving the submodule pointer to a newer release tag.
  There is no merge, so there are no upstream conflicts; the only work is
  refreshing Beryllium patches that no longer apply.
- Helium's tooling (`helium/utils/`, `helium/devutils/`) is used from the
  submodule, never copied.

Reason: an earlier version of this plan kept Beryllium inside a GitHub fork of
Helium. That model turns every upstream sync into a merge, stays conflict-free
only while Beryllium never touches a Helium-owned file (replacing the README
already broke that), and makes GitHub propose `imputnet/helium` as the default
target for pull requests, which matters given D8. The repository was
recreated as a standalone platform repository on 18 October 2026; the fork's
three planning commits were carried over and its history is kept only as a
local archive branch.

### D2. Branding: ship as Beryllium, not as Helium (needs owner sign-off)

The package, binary name, profile directory, `.desktop` entry and user-visible
name are "Beryllium". Helium's `change-chromium-branding.patch` is kept and a
Beryllium branding patch is layered after it.

Reason: Helium's code is GPL-3.0 and forkable, but Helium's name and logo are
the imputnet project's identity, and `helium-nonfree-assets` is explicitly
non-free. Shipping a modified browser under their name without agreement would
misattribute Beryllium's sandbox claims and bugs to them. Beryllium's credits
page and `pkg-descr` state plainly that it is a Helium derivative.

Scope of the rename: user-visible strings, binary and package names, icons,
profile directory, `.desktop` entry. Internal identifiers stay Helium's
(`helium://` scheme, `helium.services.*` preference names, component ids),
exactly as helium-linux keeps Chromium's internals under the Helium name. This
keeps profiles portable between Helium Linux and Beryllium and keeps the
Beryllium patch layer small. Helium's own `name_substitution.py` step
(Chromium to Helium) runs unchanged; Beryllium does not add a second blanket
substitution.

Open sub-questions: whether the non-free search-engine icon pack can be
redistributed in a FreeBSD package at all (if not, the port must set
`RESTRICTED`/`NO_CDROM` or drop the pack), and whether to ask imputnet for
permission to keep "Helium" in the name.

### D3. Helium services: keep upstream endpoints in Phase 1, decide hosting by Phase 2 (needs owner sign-off)

Helium services (`https://services.helium.imput.net`) provide the extension
proxy, `!bangs`, uBlock filter assets and more. The preference
`helium.services.origin_override` already allows pointing at a self-hosted
instance, and `helium-services` is self-hostable with Ansible playbooks.

Default for Phase 1: keep the upstream endpoints so that "Helium behaviour is
preserved" can be verified against a known reference. Before Phase 2 ships
anything to users: contact imputnet, and either obtain their agreement to serve
Beryllium clients or stand up a Beryllium-hosted instance and change the default
origin. Either way the privacy invariants document lists every endpoint.

Two services are different on FreeBSD regardless:

- **Browser update checks** (`https://updates.helium.computer/`): the in-app
  checker is compiled only for macOS and Windows, so there is nothing to
  disable on FreeBSD. The pref `helium.services.browser_updates` still gates
  Chromium component updates (CRLSets, certificate transparency logs, the
  uBlock component), which Helium routes through its services; Beryllium keeps
  those on. Browser updates arrive through `pkg`, and the onboarding and
  settings text that mentions automatic browser updates is adjusted.
- **Crash reporting** (`https://crash.helium.computer/crash`, pref
  `helium.crash_reporting_mode`): uploads disabled by default on FreeBSD. Crashes
  of a different build with a different sandbox are noise to imputnet, and the
  upload path is a privacy-relevant network channel. Local crash dumps stay
  available for triage. Revisit if a Beryllium crash endpoint is ever hosted.

### D4. Security patches are Beryllium product code, maintained as a quilt series

The Capsicum work lives in `patches/security/` and is applied with
Helium's `utils/patches.py` after the BSD platform patches. It is not mixed
into the imported BSD patch set, so that the imported set can be re-synced from
FreeBSD/OpenBSD ports mechanically. See
[05-PATCH-STRATEGY.md](05-PATCH-STRATEGY.md) for the layering order.

### D5. Fail-closed is a build-time property

Production builds define a build flag (name to be chosen in Phase 2, for example
`beryllium_sandbox_required=true`) that makes a failed `cap_enter()` fatal for
the affected process and compiles out the `--no-sandbox`/`--disable-unveil`
style escape hatches from the production launcher. Development builds that keep
the switches are produced under a different package name
(`beryllium-devel`) so they cannot be confused with the production package.

### D6. Target matrix

| Item | First release | Later |
|---|---|---|
| Architecture | `amd64` | `aarch64` once CI covers it |
| FreeBSD branches | The two supported stable branches at release time (currently 14.x and 15.x), with the kernel patched for `FreeBSD-SA-26:28.capsicum` | `-CURRENT` for early testing only |
| Display | X11 and Wayland, as the FreeBSD port supports both | |
| Audio | sndio, OSS via ALSA shim, PulseAudio, as port options | |
| GPU | Same options as `www/chromium` (Vulkan, VA-API where present) | GPU sandbox tightening in Phase 3 |

### D7. Versioning

Beryllium package version = Helium version + Beryllium platform revision, in the
form Helium already supports through `utils/helium_version.py` with a
`--platform-tree` pointing at the repository root (`HELIUM_PLATFORM` from `revision.txt`, as in helium-linux). Example:
Helium 0.19.4 with platform revision 1 is `0.19.4.1`; the port's `PORTVERSION`
carries the same string and `DISTVERSION` carries the Chromium version for
tarball naming. Every package also records the Chromium revision, the Helium
commit, the FreeBSD ports commit used for BSD patches, and the OpenBSD ports
commit if any patches were imported from there.

### D8. Relationship with upstream Helium

Helium's CONTRIBUTING and AGENTS files require human-authored contributions
and state that AI-generated issues, descriptions or code will be rejected and
the author banned. Any change Beryllium sends upstream must therefore be
written, understood and described by the maintainer personally, and must
follow the issue-first rule. Platform-neutral fixes are still worth offering;
a FreeBSD platform itself is not, since upstream declined it in issue 773.
This planning material was prepared with AI assistance and is not to be
pasted into upstream issues or pull requests.

## 4. Ground rules carried over from the spec

These are restated as one-liners because every later document relies on them:

1. No silent sandbox downgrade (spec 2.3.1).
2. Security fixes outrank patch convenience (spec 2.3.2, 4.3).
3. Kernel-enforced boundaries, not IPC policy alone (spec 2.3.3).
4. Document what is enforced versus configured versus aspirational (spec 2.3.5).
5. Do not remove a Helium privacy feature to fix a FreeBSD build problem
   (spec 10.2).
6. No SUID helpers, no root-running browser components (spec 7.2, 11.3).
7. Jails and MAC are optional outer layers, never substitutes for the renderer
   sandbox (spec 7, 9).

## 5. First actions (before any code)

1. Done on 18 October 2026: `johnjanik/Beryllium` recreated as a standalone
   repository with the `helium` submodule pinned at release tag `0.19.4`
   (commit `832faa78`, Chromium `155.0.8059.84`), and these documents, the
   spec, the README and the logo committed. Beryllium tracks Helium release
   tags, not `main`; Helium cuts a tag for every Chromium stable point
   release, usually within a day, so tags are frequent enough.
2. Run the fact-collection session from spec section 15 on the build machine
   and commit `freebsd/BASELINE.md`.
3. Proceed to Phase 0 as laid out in [09-ROADMAP.md](09-ROADMAP.md).
