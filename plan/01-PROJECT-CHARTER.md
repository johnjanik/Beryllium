# Beryllium: Project Charter

**Status:** Draft plan, no code written
**Date:** 18 October 2026; decisions D2, D3, D6 and D8 updated 1 November 2026
**Companion spec:** [helium-freebsd-security-port-spec.md](../helium-freebsd-security-port-spec.md)
**Project repository:** https://github.com/johnjanik/Beryllium (standalone platform repository; Helium's code is a pinned git submodule from https://github.com/imputnet/helium)

---

## 1. What Beryllium is

Beryllium is an independent, privacy-focused browser built natively for
FreeBSD from code derived from the Helium browser, with a FreeBSD-native
process confinement model added on top. It keeps the inherited product
behaviour (privacy defaults, the bundled uBlock Origin fork, `!bangs`,
onboarding, the "noise" fingerprinting defences; services integration is off
until Beryllium hosts its own instance, see D3) and replaces the
effectively absent FreeBSD Chromium sandbox with a layered design built around
Capsicum capability mode for renderers, optional jails as an outer perimeter,
calibrated resource limits, and a separately gated MAC study.

Beryllium is not affiliated with Helium (owner decision, 1 November 2026);
the GPL-3.0 attribution the licence requires is kept.

The spec document already defines the goals, non-goals, threat model, security
requirements and phase structure. This charter does not repeat them. It records
the decisions and facts that the spec left open and that the research snapshot
of 18 October 2026 resolved, and it sets the ground rules for the repository.

## 2. Upstreams and what each one contributes

| Upstream | What Beryllium takes from it | Current state (18 Oct 2026) |
|---|---|---|
| Chromium | The browser engine. Beryllium builds exactly the Chromium revision the pinned Helium tag uses. | Helium 0.20.3 pins `156.0.8078.79` (1 Nov 2026). Historical: `155.0.8059.84` at the 18 Oct snapshot. |
| Helium (`imputnet/helium`) | Product patches (347 patch files in `patches/`), `flags.gn`, pruning and domain-substitution lists, bundled uBlock fork, onboarding, branding, i18n (81 languages), the ungoogled-chromium derived build tooling in `utils/`. | Pinned at tag 0.20.3, commit `2f81b9ca`, revision 3 (1 Nov 2026). Version scheme is `version.txt`.`(chromium_major - 136)`.`revision.txt`. Historical: `832faa78`, 0.19.4 at the snapshot. |
| Helium platform repos (`helium-linux`, `helium-macos`, `helium-windows`) | The shape of a platform packaging repo: a build wrapper that prepares the Chromium tree with the shared tooling and then builds, plus a small platform patch series (helium-linux has 7: branding, binary rename, default theme, flags). Beryllium borrows this shape. | Upstream closed a FreeBSD port request (imputnet/helium issue 773, January 2026) as "not planned" for lack of bandwidth. Beryllium is an independent project and not one of Helium's platforms (D8). |
| Helium prepared tarballs (`imputnet/chromium-tarballs`) | `chromium-<ver>-base.tar.zst` (1.96 GB compressed, 8.6 GB and 587k files unpacked), a pinned `gclient` checkout with hooks run, shared by every Helium host; per-host layers add Google's prebuilt toolchains and Linux sysroots. Helium's `pruning.list` and `domain_substitution.list` are regenerated in CI against the base layer. Per-file sha256 manifests and `.hashes` files are on GitHub releases; archives are hosted on `tarballs.imput.net`. | Built automatically within hours of every Chromium stable release. No BSD host layer exists and none is needed, since FreeBSD uses host toolchains. |
| ungoogled-chromium | The patch application, binary pruning and domain substitution tooling that Helium inherited and extended. Also the proof that this tooling works inside a FreeBSD port (`www/ungoogled-chromium`). | FreeBSD's `www/ungoogled-chromium` is at `151.0.7922.169`, three Chromium majors behind the main port. |
| FreeBSD Ports `www/chromium` | The FreeBSD port skeleton (Makefile, options, dependencies, install layout), 1,659 `files/patch-*` BSD adaptations, the build environment conventions (LLVM 22, Rust, Node, Go, system libraries), and the `sandbox/policy/freebsd/` stub that Beryllium will replace. | `156.0.8078.47_1` (1 Nov 2026), maintained by `chromium@FreeBSD.org`. Historical: `154.0.8037.57_2` at the snapshot. |
| OpenBSD Ports `www/chromium` | The origin of most BSD patches (the FreeBSD files carry the same `.orig` timestamps), the pledge/unveil sandbox implementation that is the closest working analogue of what Beryllium wants to do with Capsicum, and the per-process `unveil.*`/`pledge.*` policy files. | `155.0.8059.84` at the 18 Oct snapshot (not re-checked on 1 Nov). Maintained by Robert Nagy. |

The important consequence: on 1 November 2026 FreeBSD's port and the pinned
Helium tag are on the same Chromium major (156.0.8078.47 versus
156.0.8078.79), so the first BSD import is a copy of the FreeBSD set plus
point-release fixes. At the 18 October snapshot it would have been the
OpenBSD 155 set plus FreeBSD deltas. All three upstreams move weekly, so this
is re-checked at every import.

## 3. Decisions recorded by this charter

Each decision below is a recommendation with the reason. Items marked
**needs owner sign-off** are product or legal choices that only the project
owner can make; the plan proceeds under the stated default until overruled.

### D1. Platform repository with Helium as a pinned submodule

`johnjanik/Beryllium` is a standalone repository, not a GitHub fork. It
borrows the structure of Helium's platform repositories (`helium-linux`,
`helium-macos`, `helium-windows`) without being one of them (D8): Helium's
code is a git submodule pinned at a release tag, and everything else in the
repository is Beryllium-owned.

```text
Beryllium/
  helium/                     # git submodule: imputnet/helium at a release tag (0.20.3 on 1 Nov 2026)
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

### D2. Branding: ship as Beryllium only (decided 1 November 2026)

The package, binary name, profile directory, `.desktop` entry and user-visible
name are "Beryllium". Helium's `change-chromium-branding.patch` is kept and a
Beryllium branding patch is layered after it.

Decision: the product carries no Helium name, logo or branding, and
Beryllium does not ask imputnet for permission to use them. Helium's code is
GPL-3.0, so the licence and attribution notices stay; the credits page and
`pkg-descr` state that the code is derived from Helium and that the projects
are not affiliated. Helium's `helium-nonfree-assets` are non-free in any
case (see Q5).

Scope of the rename: user-visible strings, binary and package names, icons,
profile directory, `.desktop` entry. Internal identifiers that users never see
stay as they are (`helium.services.*` preference names, component ids), which
keeps the Beryllium patch layer small. Helium's own `name_substitution.py`
step (Chromium to Helium) runs unchanged and the Beryllium branding patch
replaces the user-visible results.

WebUI scheme (Q11, decided 1 November 2026): pages appear as `beryllium://`
(for example `beryllium://settings`, `beryllium://setup`), implemented by
`patches/branding/beryllium-webui-scheme.patch`, which changes the value of
Helium's display scheme. Internally pages stay `chrome://`, as in Helium.
`helium://` is not kept as an alias. Strings that `name_substitution.py`
rewrites to `helium://` in `.grd`/`.xtb` files still need a Beryllium
string-substitution step.

Open sub-question: whether the non-free search-engine icon pack can be
redistributed in a FreeBSD package at all (if not, the port must set
`RESTRICTED`/`NO_CDROM` or drop the pack).

### D3. Helium services: not used; services off until Beryllium self-hosts (decided 1 November 2026)

Helium services (`https://services.helium.imput.net`) provide the extension
proxy, `!bangs`, uBlock filter assets, dictionaries and component updates. The
preference `helium.services.origin_override` allows pointing at another
instance, and `helium-services` is AGPL-3.0 and self-hostable with Ansible
playbooks.

Decision: Beryllium does not use any Helium endpoint
(`services.helium.imput.net`, `crash.helium.computer`,
`updates.helium.computer`) and does not ask imputnet to serve Beryllium
clients. Phase 1 ships with `helium.services.enabled=false` and no origin.
Self-hosting a Beryllium instance of `helium-services` is the recommended path
before the first public release; who hosts it and where is open item Q10.
Until it exists, the consequences listed in
[07-PRIVACY-INVARIANTS-PLAN.md](07-PRIVACY-INVARIANTS-PLAN.md) section 3
apply. The one that blocks a public release is component updates (CRLSets,
certificate transparency logs, the uBlock component): with services off they
go stale, which is a security problem (R13), so the first public release
requires either the hosted instance or another update source for them.

Two services are different on FreeBSD regardless:

- **Browser update checks** (`https://updates.helium.computer/`): the in-app
  checker is compiled only for macOS and Windows, so there is nothing to
  disable on FreeBSD. The pref `helium.services.browser_updates` still gates
  Chromium component updates (CRLSets, certificate transparency logs, the
  uBlock component), which the code routes through the services origin; they
  resume once a Beryllium origin exists. Browser updates arrive through `pkg`,
  and the onboarding and settings text that mentions automatic browser updates
  is adjusted.
- **Crash reporting** (pref `helium.crash_reporting_mode`): no upload, since
  Crashpad does not start on BSD and the Helium crash endpoint is not used.
  Local crash dumps stay available for triage in `beryllium-devel`. Revisit
  only if a Beryllium crash endpoint is ever hosted (Q6).

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
| FreeBSD branches | The two supported stable branches at release time (currently 14.x and 15.x), with the kernel patched for `FreeBSD-SA-26:28.capsicum` | `-CURRENT` for development and early testing only |
| Display | Wayland (recommended) and X11, as the FreeBSD port supports both; X11 is a published limitation (RT-07) | |
| Audio | sndio, OSS via ALSA shim, PulseAudio, as port options | |
| GPU | Same options as `www/chromium` (Vulkan, VA-API where present); NVIDIA proprietary driver on Wayland is the first GPU target (owner's hardware) | GPU sandbox tightening in Phase 3 |
| Development host | FreeBSD 16.0-CURRENT, amd64, 128 GB RAM, 24 cores, about 7 TB disk, Wayland, NVIDIA RTX 5090 with driver 595.99.02 (decided 1 November 2026). Builds for 14.x and 15.x run in Poudriere jails and runtime tests in bhyve guests on the same host. The `SA-26:28` fix on 16-CURRENT is confirmed by the oracle's `sigqueue` probe, not by version number. This host is also the dedicated builder RT-11 asks for. | |

### D7. Versioning

Beryllium package version = Helium version + Beryllium platform revision, in the
form Helium already supports through `utils/helium_version.py` with a
`--platform-tree` pointing at the repository root (`HELIUM_PLATFORM` from `revision.txt`, as in helium-linux). Example:
Helium 0.20.3 with platform revision 1 is `0.20.3.1`; the port's `PORTVERSION`
carries the same string and `DISTVERSION` carries the Chromium version for
tarball naming. Every package also records the Chromium revision, the Helium
commit, the FreeBSD ports commit used for BSD patches, and the OpenBSD ports
commit if any patches were imported from there.

### D8. Relationship with upstream Helium (decided 1 November 2026)

Beryllium is independent and does not associate itself with Helium: no
shared name, no use of Helium's services, no requests to imputnet, and no
planned upstream contributions. Beryllium consumes Helium's published GPL-3.0
code through the pinned submodule and keeps the attribution the licence
requires. Should a contribution ever be sent, Helium's CONTRIBUTING and AGENTS
rules apply (human-written only; AI-generated material is rejected and the
author banned), and this AI-assisted planning material must not be pasted
into upstream issues or pull requests.

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
   spec, the README and the logo committed. Done on 1 November 2026: pin
   moved to `0.20.3` (commit `2f81b9ca`, Chromium `156.0.8078.79`).
   Beryllium tracks Helium release tags, not `main`; Helium cuts a tag for
   every Chromium stable point release, usually within a day, so tags are
   frequent enough.
2. Run the fact-collection session from spec section 15 on the build machine
   and commit `freebsd/BASELINE.md`.
3. Proceed to Phase 0 as laid out in [09-ROADMAP.md](09-ROADMAP.md).
