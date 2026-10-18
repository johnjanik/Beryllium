# Beryllium: Roadmap

**Status:** Draft plan, no code written
**Date:** 18 October 2026
**Implements:** spec section 12, refined with the research snapshot

---

## 1. Shape of the roadmap

The spec's seven phases are kept. This document adds the concrete work items
the research turned up, the order dependencies, what each phase is allowed to
claim, and rough effort for one experienced maintainer working alone. Effort is
in calendar weeks at roughly half time and is an estimate for planning, not a
commitment; Chromium build cycles on one machine (hours per full build) set the
floor.

```text
Phase 0  Baseline           2-3 weeks   facts, reference build, matrices
Phase 1  Native build       4-8 weeks   www/beryllium builds and runs, no sandbox claims
Phase 2  Capsicum renderer  6-10 weeks  the central security milestone
Phase 3  Other processes    4-8 weeks   utilities, GPU, network service policies
Phase 4  Jail + resources   3-5 weeks   optional outer layers, measured
Phase 5  MAC study          2-4 weeks   decision document, prototype optional
Phase 6  Release engineering ongoing   CI, signing, cadence, handover
```

Phase 2 can start before Phase 1 is polished, as soon as a renderer launches
from a Beryllium build, because its first weeks are investigation on the
running process. Phases 4 and 5 are independent of each other. Phase 6 work
(CI, manifests) starts in Phase 1 and grows.

## 2. Phase 0: establish the baseline

Goal: reproduce the current state and write down what is actually enforced.

Work items:

1. Fact collection on the build machine (spec section 15 commands), committed
   as `freebsd/BASELINE.md`.
2. Move the `helium` submodule to the latest Helium release tag (pinned at
   `0.19.4` on 18 October 2026); record Chromium version, Helium commit,
   FreeBSD ports commit, OpenBSD ports commit.
3. Build and run stock `www/chromium` 154 from ports on the machine
   (Poudriere). Record: process tree, per-process descriptors from `procstat -f`,
   `chrome://version`, `chrome://sandbox` text, `chrome://gpu`, loaded
   libraries, startup log, network endpoints at first launch.
4. Confirm by observation what the research already shows from source: BSD
   builds run without zygote (`use_zygote` is false for `is_bsd`), the Linux
   `SandboxHostLinux` IPC thread is compiled out, `SandboxLinux::InitializeSandbox`
   on FreeBSD only lowers `RLIMIT_DATA` and runs the pre-sandbox hook, so no
   process is in capability mode. Write `freebsd/SANDBOX-BASELINE.md` with a
   per-process-type table.
5. Build the import tool and produce the first BSD patch import for Chromium
   155 (OpenBSD 155 set plus FreeBSD 154 deltas); produce
   `freebsd/PATCH-MATRIX.md` for the three layers.
6. Run the Capsicum standalone oracle on each target branch and commit the
   JSON tables.
7. Decide the tarball source for Phase 1 (section 3 below) by extracting both
   candidates and diffing their file lists against `pruning.list` and
   `domain_substitution.list`.

Exit criteria: spec 12 Phase 0, plus the oracle tables and the tarball decision.

## 3. Phase 1: native FreeBSD Beryllium build

Goal: `pkg install beryllium` works, the browser is recognisably Helium, and
the project claims nothing about sandboxing.

Work items:

1. Create `freebsd/ports/www/beryllium` from `www/chromium` and
   `www/ungoogled-chromium`, with the six-stage layering from
   [05-PATCH-STRATEGY.md](05-PATCH-STRATEGY.md) and the generated GN args from
   [07-PRIVACY-INVARIANTS-PLAN.md](07-PRIVACY-INVARIANTS-PLAN.md).
2. Tarball handling: the port fetches Helium's `chromium-<ver>-base.tar.zst`
   (hash from the GitHub release `.hashes` file, recorded in `distinfo`) or the
   official tarball, per the Phase 0 decision; `USES=tar:zst` or an explicit
   extract rule. Helium's `deps.ini` downloads (search engine data, onboarding,
   uBlock fork) become additional `DISTFILES` with their sha256 in `distinfo`,
   fetched by the ports framework, never by `utils/downloads.py` at build time.
3. Build environment: the `www/chromium` toolchain lines (LLVM 22, Rust,
   Node, Go for `tsgo`, esbuild, rollup via cargo, Qt5 for `moc`, system
   libraries via `replace_gn_files.py`) are carried over unchanged. Helium's
   `use-system-python3` patch helps here; its `rbe-nativelink-config` patch is
   irrelevant and skipped via a series exclusion.
4. Helium version injection (`helium/utils/helium_version.py --platform-tree .`),
   resources (`utils/generate_resources.py`, `replace_resources.py`), i18n
   application (`utils/i18n_apply.py`), and the uBlock component setup
   (`ublock-install-as-component`), all wired into `post-patch`/`pre-configure`.
5. Beryllium branding layer (charter D2) and the FreeBSD platform patches for
   crash upload default, update check default, profile directory name.
6. First full build; fix build breaks; classify each fix as BSD-import,
   Helium-conflict, or Beryllium-platform and file it in the right layer.
7. Launch as a normal user on X11 and Wayland; run the functional smoke list.
8. Write `freebsd/PRIVACY-INVARIANTS.md` from the inventory and run the first
   privacy capture.
9. Write the known-limitations list (features that differ on FreeBSD: crash
   reporting, update checks, Widevine via foreign-cdm, anything that did not
   build).
10. Set up the Poudriere nightly build and the build suite in CI.

Exit criteria: spec 12 Phase 1.

Known risks specific to this phase are in
[10-RISKS-AND-OPEN-QUESTIONS.md](10-RISKS-AND-OPEN-QUESTIONS.md): tarball
layout mismatch with the prune and substitution lists, Helium patches that
assume Linux crashpad, and the sheer build time.

## 4. Phase 2: Capsicum renderer sandbox

Goal: every production renderer is in capability mode with an inventoried,
rights-limited descriptor set, fails closed, and ordinary browsing works.

Work items, in order:

0. **Evaluate the existing prototype first.** Alex S (shkhln) has an
   unmerged Capsicum sandbox for the FreeBSD Chromium port (bug 269234, bugs
   294915/294916/294919/294933, branch `chromium-sandbox` in
   `shkhln/freebsd-ports`, gist of May 2026): `cap_rights_limit` and
   `cap_ioctls_limit`, `caph_enter_casper`, about 1,100 lines of libpreopen-style
   interceptors for `open`/`openat`/`stat`/`dlopen`/`realpath` over pre-opened
   directory descriptors, `cap_sysctl` and `cap_net` Casper services, per-type
   policies, and a re-enabled zygote so children inherit Casper channels. Build
   it against Beryllium's tree, run the oracle and sandbox suites against it,
   and write a one-page decision: adopt and maintain jointly, borrow specific
   pieces (the sysctl and timezone findings at minimum), or diverge, with the
   reason. The spec's descriptor-inventory and fail-closed requirements apply
   to whichever base is chosen; the prototype's known gaps (`LOCAL_PEERCRED`
   handling, a `localtime_r` deadlock bypass, no Wayland policy, the broker
   left `#if 0`) go straight into the Phase 2 work list. Coordinate on the
   bugs rather than forking silently, and remember charter D8 when writing to
   the list.

1. **Instrumented inventory.** In `beryllium-devel`, log every descriptor
   present at the renderer's sandbox initialisation point and every later
   `open`/`socket`/`shm_open` attempt (via an LD_PRELOAD shim or ktrace on the
   renderer pid) across the workload set: blank page, text page, image-heavy
   page, video, WebGL, WebAssembly, PDF, font fallback (CJK, emoji), web
   worker, service worker, large form, file upload. Output is
   `freebsd/sandbox/inventory/<workload>.json`.
2. **Design the allowlist** from the inventory (see
   [06-SECURITY-MODEL.md](06-SECURITY-MODEL.md) section 4 for the expected
   shape: the Mojo channel socketpair, shared memory regions passed by the
   browser, the resource pak and ICU data descriptors, `/dev/null` for
   stdin/stdout, a logging descriptor, possibly a pre-opened font fallback
   directory capability, and nothing else).
3. **Move namespace-dependent operations before `cap_enter`.** The first
   known blocker is `sysctl`: the 2023 attempt died at the first
   `vm.stats.vm.v_page_count` read after `cap_enter`, and the port already
   crashes on kernels without `COMPAT_FREEBSD11` for a related sysctl. Either
   cache every value `base::SysInfo` and process metrics need before entry
   (the BSD stub's `PreinitializeSandbox` already pre-calls three of them) or
   route reads through `cap_sysctl`. Then fonts (verify
   the Mojo FontService path fully covers renderer font loading on BSD; if the
   renderer still opens font files by path after startup, that must be
   brokered or pre-opened), timezone data, locale data, `dlopen` of any lazily
   loaded library, `sysctl` reads for `SysInfo`, random number source.
4. **Capability-safe shared memory.** Change
   `PlatformSharedMemoryRegion::Create` on FreeBSD to `shm_open(SHM_ANON)` or
   `memfd_create`, so renderer-created regions do not need a temp directory.
   Remove the `kern.ipc.shm_allow_removed` dependency where it comes from
   SysV shm in the X11 shm image pool if that code runs in a confined process
   (it should only run in the browser or GPU process; verify).
5. **Descriptor hygiene at launch.** In the browser's child launcher, pass only
   the `fds_to_remap` set and close everything else in the child before
   `exec` (`closefrom`/`close_range`), so the renderer starts with a known
   minimal set rather than relying on `FD_CLOEXEC` discipline across 1,600
   patched files.
6. **Implement `SandboxLinux::InitializeSandbox` for `kRenderer`:** apply
   `cap_rights_limit`/`cap_ioctls_limit`/`cap_fcntls_limit` per allowlisted
   descriptor, close any descriptor not in the allowlist, call `cap_enter`,
   verify with `cap_getmode`, record status, and on any failure in a production
   build log a structured line and abort the process.
7. **Process-control hardening** at the same point: `procctl(PROC_TRACE_CTL,
   PROC_TRACE_CTL_DISABLE)` so a renderer cannot be traced by a same-user
   process and cannot trace; `procctl(PROC_NO_NEW_PRIVS_CTL)`; review
   `setrlimit` values already applied by `LimitAddressSpace`.
8. **Status reporting.** Make `GetStatus()` return a FreeBSD bitmask
   (capability mode, rights limited, trace disabled) and teach
   `chrome://sandbox` to render it; add the kernel advisory preflight.
9. **Fail-closed build flag** and the production/devel split (charter D5).
10. **Run the sandbox suite** and the functional suite with the sandbox on;
    iterate. The rule from spec 13.3 applies: when confinement breaks a
    feature, redesign the handoff, do not widen the sandbox.
11. **Security design review** document: residual authority of a renderer
    (what the Mojo channel to the browser allows it to ask for), known gaps,
    and the test evidence.

Exit criteria: spec 12 Phase 2.

## 5. Phase 3: broaden process-specific policies

Goal: kernel-enforced isolation for every process class that is claimed to be
sandboxed, and an explicit risk statement for every class that is not.

Order of attack, chosen by risk times feasibility:

1. **PDF, print compositor, image/data decoders and the "service" utility
   type**: renderer-like, no device access; reuse the renderer policy with a
   smaller allowlist. The BSD set already compiles the Linux pre-sandbox hooks
   for print backend, speech recognition, on-device translation, shape
   detection, screen AI and hardware video; each gets a Capsicum policy or an
   explicit "runs unsandboxed, here is why" statement.
2. **Audio service**: sndio, OSS and PulseAudio each need a different
   descriptor shape (a pre-connected sndio socket, an open `/dev/dsp` with an
   ioctl allowlist, a PulseAudio socket). Pre-connect in the hook, enter
   capability mode, verify playback continues.
3. **Network service**: separate process already; it needs the global network
   namespace, so capability mode is not the tool. Use `cap_rights_limit` on
   its file descriptors, restrict its filesystem reach to the profile's
   network directory and the NSS database, consider `capsicum` with
   `cap_net`/`cap_dns` casper services only after measuring, and audit every
   Mojo interface a renderer can reach that results in a network request.
4. **GPU process**: follow OpenBSD's shape (device nodes under `/dev/dri`,
   Mesa cache directory, Vulkan ICDs, the pre-sandbox library preload that the
   BSD `GpuPreSandboxHook` already does). Capability mode with an ioctl
   allowlist on the DRM descriptor is the target; the driver surface that
   remains is documented as residual risk.
5. **CDM (Widevine via foreign-cdm)**: policy modelled on OpenBSD's
   `unveil.cdm`, or documented as unsandboxed opt-in.

Exit criteria: spec 12 Phase 3, with the per-process authority matrix in
[06-SECURITY-MODEL.md](06-SECURITY-MODEL.md) filled with tested values.

## 6. Phase 4: optional jail and resource profiles

1. An administrator-managed example jail configuration (`jail.conf` fragment,
   a `ZFS` dataset layout, `devfs` ruleset exposing only `/dev/dri` and the
   chosen audio device, a VNET or shared-stack choice, Wayland socket or
   X11 socket mapping with the trade-offs written down).
2. Three resource profiles (`desktop`, `constrained`, `jail`) with measured
   baselines from the resource suite, delivered as documented `rctl` rule sets
   and `login.conf` classes, never applied by the package.
3. Jail integration tests: the browser starts, renders, plays audio, downloads
   to the mapped directory, and the renderer sandbox is still enforced inside
   the jail.

Exit criteria: spec 12 Phase 4.

## 7. Phase 5: MAC feasibility study

A written decision, not necessarily code: which residual threat from the
Phase 2 and 3 reviews a MAC module would address, whether `mac_mls` labels
on the profile and downloads directories give a confidentiality property that
Capsicum plus jail do not, the cost of labelling a user's home directory, and
a prototype on a disposable system only if the answer is yes. The default
expectation is "not for the first release".

## 8. Phase 6: release engineering and maintenance

Covered by [11-MAINTENANCE-AND-RELEASE.md](11-MAINTENANCE-AND-RELEASE.md).
Milestone: the handover test passes.

## 9. First public release definition

The first release that is announced beyond the project's own testers requires:

- Phase 1 and Phase 2 exit criteria met.
- Phase 3 complete for at least the PDF, print and generic utility classes,
  with the audio, network, GPU and CDM classes either done or listed in the
  known-limitations page as unsandboxed with their risk statements.
- Phase 6 CI running and the handover test passed.
- The sandbox status table published.

Phases 4 and 5 are not required for the first release.
