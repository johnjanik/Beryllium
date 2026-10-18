# Beryllium: Risk Register and Open Questions

**Status:** Draft plan, no code written
**Date:** 18 October 2026

---

## 1. Risk register

Likelihood and impact are rated low, medium or high. "Mitigation" is what the
plan already does; "trigger" is the signal that the risk has materialised.

| # | Risk | L | I | Mitigation | Trigger |
|---|---|---|---|---|---|
| R1 | Helium's `pruning.list` and `domain_substitution.list` do not match the file layout of whichever tarball the port uses, so pruning leaves binaries behind or substitution aborts on missing files | M | M | Phase 0 item 7 diffs both candidate tarballs against the lists before the port is written; prefer Helium's `-base` tarball, which the lists were generated from | stage 1 or 5 reports missing files |
| R2 | Helium's prepared tarball is not redistributable or not stable (hosted outside GitHub, hashes on GitHub releases) and a release disappears | L | M | `distinfo` pins hashes; the port can fall back to the official Google tarball; keep a local mirror of every tarball a release was built from | fetch failure |
| R3 | BSD patch forward-port to Helium's Chromium version is larger than expected because FreeBSD lags and OpenBSD's set has FreeBSD-incompatible pieces | M | H | Import tool with provenance; OpenBSD 155 plus FreeBSD 154 deltas; budget in Phase 0; coordinate with `chromium@FreeBSD.org` | more than a few dozen failed patches on import |
| R4 | Helium patches conflict with BSD patches in behavioural ways (crashpad, paths, process launch) | M | M | Patch matrix with semantic-risk column; tests per hot spot | matrix rows with behavioural risk and no test |
| R5 | Renderers depend on namespace access after startup (fonts opened by path, `dlopen` of codecs, locale files, `/dev/urandom` reopened) so `cap_enter` breaks real pages | H | H | Phase 2 instrumented inventory across workloads before any policy; pre-open and broker; the spec's rule against widening the sandbox to fix a feature | functional suite failures only with sandbox on |
| R6 | Shared-memory creation in confined processes (temp-dir file today) and SysV shm for X11 (`kern.ipc.shm_allow_removed`) conflict with capability mode | H | H | Switch to `shm_open(SHM_ANON)`/`memfd_create` on FreeBSD; confirm SysV use is browser/GPU only | `ECAPMODE` from shm paths in the inventory |
| R7 | Chromium's process metrics, `SysInfo`, thread naming or priority code uses `sysctl`/`procfs`-like calls that fail in capability mode | M | M | Oracle test for `sysctl` in capability mode; cache values in `PreinitializeSandbox` as the BSD stub already starts to do | log noise or crashes right after `cap_enter` |
| R8 | A Capsicum kernel bug (as in `SA-26:28`) weakens the sandbox on users' machines | M | M | Advisory checklist, oracle tests, honest status reporting; does not block running | new advisory |
| R9 | Build time and memory make iteration slow (full Chromium builds take hours; the port wants 8 GB minimum, 16 GB for LTO, 35 to 60 GB disk) | H | M | Component builds in `beryllium-devel` for iteration; `ccache`; a second build host for CI | developer throughput |
| R10 | GPU process cannot be meaningfully confined because Mesa drivers need broad device and ioctl access, so the "sandboxed" claim stays partial | H | M | Phase 3 treats GPU separately; document residual driver surface; ioctl allowlist as far as it goes | GPU functional failures under confinement |
| R11 | Upstream Helium rejects or ignores platform-neutral contributions, so Beryllium carries more local patches than planned | M | L | Follow Helium's CONTRIBUTING (issue first); keep local patches small and separable | growing `patches/platform/` |
| R12 | Branding, non-free assets, or Helium services use create a licensing or relationship problem with imputnet | M | M | Charter D2 and D3; contact upstream early in Phase 1 | upstream objection |
| R13 | Disabling browser update checks also disables component updates (CRLSets, CT logs, uBlock component) because Helium gates both on one pref | H | M | Phase 1 platform patch to split the pref or route components through the services origin independently; verify by capture | components stale in a fresh profile after a week |
| R14 | `www/ungoogled-chromium` style drift: the port and the Helium pin diverge, flags are copied by hand, and the port falls behind | M | H | Generated GN args; import tool; CI on every Helium tag; the handover test | version gap to Helium grows beyond one release |
| R15 | Wayland or X11 integration leaks authority into the renderer (display socket passed, clipboard) | L | H | Sandbox suite test that renderers cannot reach display sockets; jail profile notes | a display socket in a renderer's descriptor list |
| R16 | Jail profile encourages users to think the browser is "jailed" and skip the renderer sandbox | M | M | Jail is optional and documented as outer perimeter only; package never installs it | support questions treating the jail as the sandbox |
| R17 | `aarch64` divergence (no SwiftShader, no LTO option in the port) | L | L | `amd64` only until CI covers `aarch64` | |
| R18 | Single maintainer bus factor | H | H | Handover test; written procedures; offer the port to the FreeBSD tree | |
| R19 | Upstream Helium declined a FreeBSD port (issue 773, "not planned") and rejects AI-assisted contributions outright, so Beryllium cannot expect upstream help and every upstream submission must be hand-written by the maintainer | H | M | Charter D8; keep platform-neutral fixes small; budget maintainer time for upstream interaction | upstream rejection or ban |
| R20 | Helium's `-base` tarball bundles Google's prebuilt depot_tools, node, Rust and Python; the FreeBSD port symlinks host tools into the same paths, and pruning is expected to delete the bundled binaries first. If pruning and the port's symlink setup disagree, the build picks up Linux binaries or fails late | M | M | Phase 0 item 7 and the port's `pre-configure` verify the tool paths resolve to host binaries; a check fails the build if any ELF under `third_party/*-toolchain`, `third_party/node` or `third_party/depot_tools` is a Linux binary | Linux ELF found in the prepared tree |
| R21 | FreeBSD 15.x shows an immediate SIGTRAP in V8 JIT code on some 15.0-STABLE systems (bug 292816, January 2026) and kernels without `COMPAT_FREEBSD11` crash on a missing sysctl (bug 295495); Beryllium inherits both | M | H | Test on 15.x early in Phase 0; document the kernel option requirement in `pkg-message`; the sysctl caching work in Phase 2 removes the second | SIGTRAP at startup on a 15.x test VM |
| R22 | Two Capsicum efforts diverge (Beryllium and the shkhln prototype), splitting scarce reviewer attention and producing two incompatible policies for the same port | M | M | Roadmap Phase 2 item 0: evaluate and decide before writing policy code; coordinate on bug 269234 | parallel incompatible patch sets |

## 2. Open questions needing the project owner

| # | Question | Default in the plan | Decide by |
|---|---|---|---|
| Q1 | Ship under the name Beryllium, or seek permission to keep "Helium" in the name? | Beryllium | before Phase 1 branding work |
| Q2 | Keep upstream Helium services endpoints, self-host, or ask imputnet to serve Beryllium clients? | keep upstream endpoints in Phase 1, decide before Phase 2 release | before first public release |
| Q3 | Track Helium `main` or Helium release tags? | release tags (the submodule is pinned at `0.19.4`) | decided |
| Q4 | Which FreeBSD branches at first release? | the two supported stable branches, both patched past `SA-26:28` | Phase 0 |
| Q5 | Is the non-free search-engine icon pack redistributable in the package? | assume no until the licence is read; port sets `RESTRICTED` if needed | Phase 1 |
| Q6 | Crash uploads: off forever, or stand up a Beryllium endpoint later? | off | can wait |
| Q7 | Offer the port to the FreeBSD ports tree, or stay an overlay? | offer after Phase 2 | after Phase 2 |
| Q8 | Is PGO (the port's profdata tarball) wanted, given Helium sets `chrome_pgo_phase=0`? | no PGO in Phase 1 | Phase 6 |
| Q9 | Widevine via `foreign-cdm` as a default option or off? | same default as the port (`WIDEVINE` option off by default) | Phase 1 |

## 3. Facts to re-verify on day one

These were true at the 18 October 2026 snapshot and will have moved:

- Helium `chromium_version.txt` (`155.0.8059.84`), Helium revision (4), latest
  Helium release tag.
- The `helium` submodule pin (`0.19.4`, `832faa78`) is still the latest Helium release.
- FreeBSD `www/chromium` version (`154.0.8037.57_2`) and `LLVM_DEFAULT` (22).
- FreeBSD `www/ungoogled-chromium` version (`151.0.7922.169_4`).
- OpenBSD `www/chromium` version (`155.0.8059.84`).
- The FreeBSD `sandbox_freebsd.cc` stub still contains no `cap_enter`.
- The list of FreeBSD advisories affecting Capsicum (one known: `SA-26:28`).
