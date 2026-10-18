# Beryllium: Baseline Findings (Research Snapshot)

**Status:** Research record, 18 October 2026. Everything here will drift; re-verify on day one (see the list at the end of [10-RISKS-AND-OPEN-QUESTIONS.md](10-RISKS-AND-OPEN-QUESTIONS.md)).
**Method:** direct reads of the Helium repository (shallow clone), the FreeBSD and OpenBSD ports trees, the Helium release pages, the freebsd-chromium list archives and Bugzilla notification mails, the FreeBSD wiki page (which is now only a pointer page), and the Helium platform repositories. Items that could not be confirmed are marked as such.

---

## 1. Helium

### 1.1 Versions and cadence

| Item | Value |
|---|---|
| Latest release | Helium 0.19.4, 16 October 2026, Chromium 155.0.8059.84 |
| Platform tags | helium-linux 0.19.4.1 (16 Oct), helium-windows 0.19.4.1, helium-macos 0.19.4.1 (17 Oct) |
| `main` | commit `832faa78`, same Chromium version, revision 4 |
| Version formula | `version.txt` (0) . (Chromium major - 136) . `revision.txt` . platform revision |
| Release count | 115 releases since 0.3.3 on 18 August 2025, roughly two per week |
| Lag behind Chromium stable | 5 to 40 hours for the last six Chromium releases (measured from chromiumdash and GitHub release timestamps) |
| Release automation | `release-and-tag.yml` tags whenever the computed version changes; platform repos bump via a shared action |
| `johnjanik/Beryllium` | recreated on 18 October 2026 as a standalone repository with the `helium` submodule pinned at `0.19.4` (`832faa78`); the earlier GitHub fork had been an unmodified copy 32 commits behind, pinning Chromium 155.0.8059.39 |

### 1.2 Repository contents that matter for the port

- `patches/`: 346 patch files in `series` (347 on disk including one not in series at the snapshot), grouped: `helium/core` 127, `helium/ui` 104, `helium/settings` 26, `ungoogled-chromium` 70, `inox-patchset` 6, `brave` 4, `bromite` 3, `iridium-browser` 3, `upstream-fixes` 2, `debian` 1.
- Helium patches touch 1,070 distinct Chromium files; the inherited sets touch 723.
- Platform conditionals inside Helium patches: `IS_MAC` 87, `IS_CHROMEOS` 71, `IS_WIN` 47, `IS_ANDROID` 35, `IS_LINUX` 30 (17 patches), `IS_POSIX` 2, `IS_BSD`/`IS_FREEBSD` 0.
- Linux-specific files touched by Helium patches: `chrome/common/chrome_paths_linux.cc`, `components/crash/core/app/crashpad_linux.cc`, `chrome/browser/ui/color/linux/native_chrome_color_mixer_linux.cc`, `chrome/common/importer/firefox_importer_utils_linux.cc`, `chrome/browser/extensions/api/messaging/launch_context_posix.cc`.
- No Helium or helium-linux patch touches `sandbox/`, `content/zygote/`, the zygote host, or the child process launcher. Helium relies on Chromium's stock Linux sandbox (user namespaces plus seccomp-bpf, zygote); `chrome_sandbox` (the SUID helper) is neither built nor shipped. Helium's packaging rules forbid adding `--no-sandbox` or disabling CFI.
- `flags.gn`: 17 arguments (full text in [07-PRIVACY-INVARIANTS-PLAN.md](07-PRIVACY-INVARIANTS-PLAN.md)). `flags.linux.gn` adds `is_official_build=true symbol_level=1 blink_symbol_level=0 ffmpeg_branding="Chrome" proprietary_codecs=true fatal_linker_warnings=false rtc_use_pipewire=true is_clang=true is_debug=false use_kerberos=false use_sysroot=true use_vaapi=true use_system_libffi=false use_siso=true`.
- `deps.ini`: search engine data (helium-nonfree-assets 202609082320), onboarding (helium-onboarding 202610161403), uBlock Origin fork 1.75.0 (`imputnet/uBlock`), with sha256 and output paths.
- `downloads.ini`: the `-base.tar.zst` from `tarballs.imput.net`, hashes from `imputnet/chromium-tarballs` releases.
- Tooling: Python 3.10 pinned for repo tooling (CI lint uses 3.13; chromium-tarballs needs 3.11+); quilt for patch development; `devutils/validate_patches.py`, `update_lists.py` (regenerates prune and domsub lists against the tarball in CI).
- helium-linux: 7 platform patches (`use-oauth2-client-switches-as-default`, `change-chromium-branding`, `rename-chrome-binary`, `use-default-theme`, `add-middle-click-paste-flag`, `add-error-for-missing-desktop-file`, `disable-tab-strokes`); build in a Debian trixie container with Google's bundled toolchain; outputs tar.xz, AppImage, .deb, COPR; GPG signed; 10 chained 5-hour CI jobs per build.
- Build order in helium-linux `shared.sh`: fetch, prune (`--keep-build-dependencies`), patches (Helium then platform), domain substitution, name substitution, i18n, version, resources, write `args.gn` (`flags.gn` + `flags.linux.gn`), `gn gen --fail-on-unused-args`, `autoninja chrome chromedriver` with siso.

### 1.3 Prepared tarballs

- `chromium-155.0.8059.84-base.tar.zst`: 1.96 GB compressed, 8.58 GB and 587,299 files unpacked; a `gclient` checkout with `checkout_configuration=small`, PGO profiles, `target_os=linux`, hooks run. Contains `third_party/depot_tools`, `third_party/node` (Linux node plus node_modules), `third_party/rust-toolchain`, `third_party/cpython3`, `third_party/widevine`.
- `chromium-155.0.8059.84-linux-x64.tar.zst`: 1.20 GB, adds `third_party/llvm-build` (clang 24), the Rust toolchain, `buildtools/linux64/gn`, siso, ninja, Debian bullseye sysroots.
- Per-file sha256 manifests in `.metadata.zip`; releases marked immutable; no signatures on the archives.
- No BSD host layer. FreeBSD needs none: the port uses host LLVM, Rust, Node, Go, Python.

### 1.4 Services and endpoints

Recorded in [07-PRIVACY-INVARIANTS-PLAN.md](07-PRIVACY-INVARIANTS-PLAN.md) section 3. Headline facts: services origin `https://services.helium.imput.net` with paths `/ext`, `/ext/cws_snippet`, `/ubo/assets.json`, `/bangs.json`, `/dict/`; crash intake `https://crash.helium.computer/crash`; update appcasts at `https://updates.helium.computer/` compiled for macOS and Windows only; `helium-services` is AGPL-3.0 and self-hostable.

### 1.5 Upstream stance

- Issue `imputnet/helium#773` "[FR]: Freebsd Port" (18 January 2026) closed as not planned on 2 February 2026: no bandwidth to maintain it. Locked in March.
- CONTRIBUTING and AGENTS require human-written contributions and threaten bans for AI-generated material; macOS is the primary development platform.
- Licensing: Helium code GPL-3.0; ungoogled tooling BSD-3-Clause; helium-services AGPL-3.0; uBlock fork GPL-3.0; helium-nonfree-assets GPL-3.0 outside `nonfree/`, brand icons claimed under fair use.

## 2. FreeBSD `www/chromium`

### 2.1 Versions and maintenance

| Item | Value |
|---|---|
| Version | 154.0.8037.57, PORTREVISION 2; updated 26 September 2026 by Robert Nagy; last touched 14 October 2026 (Rust 1.99 sweep) |
| `www/ungoogled-chromium` | 151.0.7922.169, PORTREVISION 4; updated 21 August 2026 |
| OpenBSD `www/chromium` | 155.0.8059.84, 17 October 2026 |
| Maintainer | `chromium@FreeBSD.org`; every version update committed by Robert Nagy, who also maintains the OpenBSD port. The wiki's team list is stale. |
| Shared patch set | FreeBSD moved to the combined OpenBSD/FreeBSD patch set in February 2022. 1,651 patches are common after name normalisation; 8 FreeBSD-only; 24 OpenBSD-only (mostly 155 skew). No public shared repository; flow is from the maintainer's private tree, OpenBSD usually first. |
| Branches built | Package cluster builds for 13.5, 14.3, 14.4, 15.0, 15-stable and main on amd64, 15.0 on arm64. No OS version conditionals in the Makefile. |
| Open build bug | 298960: 154.0.8037.57 build failure (open, September to October 2026) |

### 2.2 Build system facts

- Source: `chromium-<ver>-linux.tar.xz` from `chromium-linux-tarballs/chromium-tarballs` GitHub releases (1.93 GB), plus `-profdata.tar.xz` and a vendored TypeScript tarball from `nerd.hu/distfiles` (also OpenBSD's mirror), PulseAudio 16.1 headers, rollup, esbuild and TypeScript via `GH_TUPLE`.
- Toolchain: `LLVM_DEFAULT=22` with `BINARY_ALIAS` for cc, c++, ar, nm, ld.lld; bundled libc++ and libunwind; `lang/rust` with `RUSTC_BOOTSTRAP=1` and `rust-bindgen-cli`; `www/node` symlinked into `third_party/node/freebsd`; Go builds `tsgo`; `devel/esbuild` rebuilt neutral; cargo builds a rollup native binding; Qt5 for `moc` only.
- System libraries via `replace_gn_files.py`: dav1d, flac, fontconfig, harfbuzz, libdrm, libpng, libusb, libwebp, libxml, libxslt, openh264, opus. FreeType stays bundled.
- Resource message: Release 8 GB RAM and 35 GB disk; LTO 16 GB and 40 GB; Debug 32 GB and 60 GB; 1.5 million inodes. The package cluster regularly times out; a user reported builds timing out at 95 percent in March 2026.
- Options: CODECS, CUPS, DEBUG, DRIVER, KERBEROS (Heimdal/Heimdal base/MIT), LTO (not aarch64), PIPEWIRE (screen capture), TEST, WIDEVINE (adds `foreign-cdm` run dependency; `enable_widevine=true` is unconditional); audio group ALSA, PULSEAUDIO, SNDIO all on by default.
- Wrapper `chrome.in`: refuses to start unless `kern.ipc.shm_allow_removed=1`, sets `ulimit -c 0`, sources the foreign-cdm environment.
- GN `is_linux` is true on BSD while the C++ `BUILDFLAG(IS_LINUX)` is false; `IS_BSD`, `IS_FREEBSD`, `IS_OPENBSD` exist upstream in `build/build_config.h`. That is why 1,600 patches add `|| BUILDFLAG(IS_BSD)`.
- Display: ozone X11 default, Wayland enabled (`ozone_platform_wayland=true`), Wayland is a hard build dependency. GPU: ANGLE, EGL, Vulkan loader and Mesa ICDs, SwiftShader on amd64; VA-API patched for BSD but `use_vaapi` not set in the Makefile (default unconfirmed). Audio: sndio manager replaces the Linux manager with runtime selection among sndio, ALSA and PulseAudio and a `chrome://flags` entry.
- Crashpad is patched to build but is not started on BSD (`chrome_main_delegate.cc` patch); no crash reporter runs.

### 2.3 Sandbox reality on FreeBSD today

From the patched sources (see also the per-file notes in [06-SECURITY-MODEL.md](06-SECURITY-MODEL.md)):

| Fact | Evidence |
|---|---|
| No zygote | `content/public/common/zygote/features.gni`: `use_zygote = is_posix && !is_android && !is_mac && !is_bsd`; `ZygoteMain` returns false on BSD; the child launcher always calls `base::LaunchProcess` |
| No seccomp, no SUID client, no syscall broker | `sandbox/features.gni` and `sandbox/linux/BUILD.gn` patches gate them on `!is_bsd` |
| No Linux sandbox IPC thread | `SandboxHostLinux::Init` skips creating the pipe and thread under `IS_BSD`; `sandbox_ipc_linux.cc` removed from the build |
| `sandbox/policy/freebsd/sandbox_freebsd.cc` | 210 lines, class still named `SandboxLinux`, header is a copy of the OpenBSD one (guard `SANDBOX_POLICY_LINUX_SANDBOX_OPENBSD_H_`, declares `SetPledge`/`SetUnveil`/`GetStatus` that are never defined). `PreinitializeSandbox`: browser does NSS init, `CRYPTO_pre_sandbox_init`, creates `~/.cache/chromium` and `~/.local/share/applications`; renderer calls `gfx::InitializeFonts()`. `InitializeSandbox`: returns early on `--no-sandbox`; otherwise lowers `RLIMIT_DATA` to `kDataSizeLimit` and runs the pre-sandbox hook. No `cap_enter`. |
| Service hooks are no-ops | `NetworkPreSandboxHook`, audio, print, speech, translation, shape detection, screen AI, hardware video hooks have their broker setup compiled out under `IS_BSD` and return true; `kNetworkServiceSandbox` is enabled by default but does nothing |
| GPU hook | `gpu_pre_sandbox_hook_bsd.cc` `dlopen`s `libvulkan.so`, `libvulkan_intel.so`, `libvulkan_intel_hasvk.so`, `libvulkan_radeon.so` with `RTLD_NOW|RTLD_GLOBAL|RTLD_NODELETE`; comment "TODO(tsepez): enable namspace sandbox here once crashes are understood" |
| Switches | `--disable-unveil` string exists with nothing behind it on FreeBSD; `--no-zygote-sandbox` enabled for BSD |
| `chrome://sandbox` | registered under `IS_BSD`; the FreeBSD backend defines no `GetStatus()`; what the page shows is unconfirmed |
| Shared memory | `PlatformSharedMemoryRegion::Create` on BSD takes the generic POSIX path (a temporary file in the shmem temp directory, unlinked after open); the X11 shm image pool uses SysV shm, hence the `shm_allow_removed` requirement |
| Fonts | Renderers bind the Mojo `FontService` (`RendererBlinkPlatformImpl` patched for `IS_BSD`) and also call `gfx::InitializeFonts()` before "sandboxing"; whether any path-based font open remains after startup is unconfirmed |

Net effect: every FreeBSD Chromium process runs without kernel-enforced confinement. The spec's warning is confirmed from source.

### 2.4 OpenBSD's working model

`sandbox/policy/openbsd/sandbox_openbsd.cc` (448 lines, present in both ports, compiled only on OpenBSD) applies `unveil(2)` from `/etc/chromium/unveil.{main,gpu,utility_network,utility_audio,utility_video,cdm}` and `pledge(2)` per sandbox type:

| Process | pledge |
|---|---|
| browser (`kNoSandbox`) | from `/etc/chromium/pledge.main`: `rpath wpath cpath stdio dns inet flock unix proc prot_exec tty sendfd recvfd exec mcast ps drm fattr route getpw vminfo video` |
| renderer | `stdio rpath flock prot_exec recvfd sendfd ps` (comments: `prot_exec` for V8, `flock` for SQLite); unveil only `/dev/null` |
| GPU and on-device model | `stdio drm inet rpath flock cpath wpath prot_exec recvfd sendfd unix`; unveil `/dev/dri`, Mesa and Vulkan directories, `~/.cache/mesa_shader_cache`, `/tmp` |
| network | from file: `rpath wpath cpath stdio dns inet prot_exec sendfd recvfd mcast route flock unix`; unveil `~/.pki`, `~/.cache/chromium`, `~/.config/chromium`, `/etc/machine-id`, `/tmp` |
| audio | `stdio prot_exec recvfd sendfd dns unix rpath cpath wpath`; unveil `~/.sndio`, `/tmp` |
| video capture | audio set plus `video`; unveil `/dev/video0-7`, `/tmp` |
| CDM | `stdio rpath flock recvfd sendfd`; unveil `/etc/openwv`, `~/.config/chromium/WidevineCdm` |
| utility and service | `stdio rpath cpath wpath fattr flock sendfd recvfd prot_exec` |

Memory limits in the OpenBSD version are per process type (renderer 8 to 32 GB of `RLIMIT_DATA` scaled by physical memory, doubled under a feature flag). The renderer's `unveil` of only `/dev/null` while keeping `rpath` shows that OpenBSD renderers do not open files by path after startup; how they create shared memory is one of the questions for the Chromium internals survey.

### 2.5 Prior and current Capsicum work on FreeBSD Chromium

| When | Who | What |
|---|---|---|
| January to February 2023 | `sigsys@gmail.com`, bug 269234 | "Chromium port basic Capsicum support": header cleanup plus rudimentary `cap_enter` for renderers that only limited the stdio descriptors; admitted not to know what other descriptors renderers hold; rebased to 110 then dormant |
| March 2026 | Alex S (`shkhln`), same bug | The cleanup part was merged quietly long ago; the sandbox part "breaks at the first sysctl call (`vm.stats.vm.v_page_count`)". Working on an alternative: libc calls redirected through a libpreopen-style shim to `cap_sysctl` and `cap_net` Casper services plus pre-opened files and directories; re-enables the zygote (plain `fork`) to share Casper channels with children |
| April 2026 | same | "mostly done", branch https://github.com/shkhln/freebsd-ports/tree/chromium-sandbox for testing; bugs 294915 (thread ids in logs), 294916 (audio sandbox flag), 294919 (network sandbox flag; maintainer replied the flag already reflects the context manager, so forcing it is wrong), 294933 (re-enable zygotes, rebased for 150 in July) |
| May 2026 | gist https://gist.github.com/shkhln/76ea1cdcfe342b39cd7fc09eb2ea0ba3 | `cap_rights_limit`/`cap_ioctls_limit` plus `caph_enter_casper()`; new `sandbox/policy/freebsd/interceptors.{cc,h}` (about 1,100 lines) overriding open, openat, stat, mkdir, unlink, dlopen, realpath via pre-opened directory descriptors; `cap_net` limits `connect()` in the network service; `cap_sysctl` allowlist; per-type policies for audio, GPU (X11, DRI, Vulkan, NVIDIA), network, renderer (MIME cache, fontconfig), utility and print; early return for `kNoSandbox` and `kCdm`; known gaps: `LOCAL_PEERCRED` with socketpair disabled, a `localtime_r` deadlock bypass, "TODO: Wayland", broker `#if 0` |
| May 2026 | ports tree, 148.0.7778.96 | Only the sandbox-type flag changes from bugs 294916 and 294919 landed (8 May 2026); the maintainer's reply on 294933 (zygote) was "not sure that this is something we want or actually require" |
| October 2026 | ports tree | The sandbox implementation itself has not landed; the `chromium-sandbox` branch was last updated 15 October 2026 |

This is the most important external input to Phase 2: a working prototype exists, from an author who has hit the real obstacles (sysctl in capability mode, path-based opens in libraries, timezone handling, zygote for Casper sharing). Beryllium should evaluate that branch on day one of Phase 2 and decide between adopting it, collaborating, or diverging with a written reason.

### 2.6 Known issues relevant to Beryllium (from the 2025 to 2026 list and Bugzilla traffic)

- 292816: immediate SIGTRAP on 15.0-STABLE (illegal instruction in V8 JIT code, even with `--no-sandbox` and `--disable-gpu`). A 15.x risk to test early.
- 295495: SIGTRAP when the kernel lacks `COMPAT_FREEBSD11` (missing `vm.stats.vm.v_cache_count` sysctl). Relevant both as a kernel-config requirement and as a sysctl-in-capability-mode data point.
- 296899: fails to build on 14.4-STABLE (summer 2026, resolution unconfirmed).
- 296119: crash on WebAuthn/FIDO2 prompt (`hid_service_freebsd.cc` `O_NONBLOCK` on `/dev/uhid`).
- 292306/292307: cannot store passwords (NSS error loading root certificates). Helium removes the password manager anyway.
- 291555, 292714, 286635: Wayland flicker and GPU process crashes on specific versions.
- 290718: micro-stutter at 1080p60.
- 298988: chromedriver leaks its listening socket; helper processes outlive the browser.
- 293265: proposal to make Wayland optional; notes PulseAudio-off builds break.
- 294118: ungoogled port has known CVEs because it lags.

## 3. Chromium sandbox internals (upstream main, October 2026)

- `sandbox/policy/` upstream has `fuchsia/`, `linux/`, `mac/`, `win/`, `mojom/`
  and no BSD directory; the BSD directories exist only in the ports patch
  sets. A 2019 chromium-dev thread on upstreaming BSD patches ended with the
  statement that Chromium developers will not consider BSD when changing
  things; no decision was recorded. Upstreaming the sandbox is therefore not
  a plan input.
- Linux lockdown sequence in `SandboxLinux::InitializeSandbox`: single-thread
  check, `PreinitializeSandbox`, optional namespace engage (no-zygote case),
  `CHECK(!HasOpenDirectories())`, `InitLibcLocaltimeFunctions()`,
  `DiscourageGetaddrinfo()`, `LimitAddressSpace()`, then the pre-sandbox hook
  and the seccomp policy. The BSD stub keeps the shape and drops the
  substance; the Capsicum implementation slots into the same place.
- Renderer: `RendererMainPlatformDelegate::EnableSandbox` raises the fd limit
  to 4096, calls `Sandbox::Initialize` with no hook, then self-checks that the
  promised layers are active. The BSD patch compiles the self-checks out.
- Utility processes pick a pre-sandbox hook by sandbox type (network, print
  backend, audio, speech, translation, screen AI, shape detection, hardware
  video); on BSD `utility_main.cc` always calls `Sandbox::Initialize` with
  default options and every hook's broker setup is compiled out.
- Upstream `kNetworkServiceSandbox` is disabled by default on Linux; the BSD
  patch enables it by default (with a no-op hook).
- Zygote rationale (`docs/linux/zygote.md`): amortise relocations and library
  initialisation, keep a handle on the pre-update binary, own the layer-1
  namespace sandbox. Without a zygote, `--no-zygote` processes engage the
  namespace sandbox themselves. The BSD ports disable the zygote entirely.
- Shared memory: Linux uses `memfd_create` with seals and a `/proc/self/fd`
  read-only twin; all other POSIX platforms, including BSD, create and unlink
  a temp file. Mojo non-broker processes delegate allocation to the broker
  unless `force_direct_shared_memory_allocation` is set (where content sets
  this per platform is unconfirmed). Legacy sandbox IPC now serves only
  `localtime`; shm creation moved to Mojo's broker years ago.
- Descriptor passing: Mojo channel is an `AF_UNIX` `SOCK_STREAM` socketpair
  passed through `fds_to_remap`; `--shared-files=key:fd` carries V8 snapshot,
  field-trial and embedder descriptors; `base::LaunchProcess` does the `dup2`
  shuffle and `CloseSuperfluousFds` by listing `/dev/fd` on the BSDs.
- Fonts: the Mojo `FontService` (`components/services/font/`) serves
  matching, fallback and file descriptors; the BSD patches wire it for
  `IS_BSD` in Skia, the renderer and the utility platform.
- `chrome://sandbox`: the Linux status block is compiled only for
  `IS_LINUX`/`IS_CHROMEOS`; BSD builds show no rows unless patched.
  `Sandbox::IsProcessSandboxed()` returns `false` on BSD, and `true` for any
  non-browser process launched with `--no-sandbox`.
- Tests: `sandbox_linux_unittests` covers seccomp, namespaces, the broker and
  the SUID client, none of which build on BSD; the renderer self-checks and
  `RunSandboxSanityChecks` are the pattern to copy for FreeBSD.
- Prior art: Watson et al. 2010 reported about 100 lines to add Capsicum to
  Chromium (versus 11,301 for seccomp at the time), with the one significant
  change being SysV to POSIX shared memory; the prototype's TODO list (process
  descriptors, zygote `cap_enter`, fd closing zygote to renderer, X11 SHM
  replacement) reads like Beryllium's Phase 2. Matthias Wolf's EuroBSDCon 2021
  talk listed "add proper Capsicum support" as a wish and noted upstream does
  not accept patches for unsupported platforms. Firefox on FreeBSD ships
  without content-process sandboxing (Capsicum backend unimplemented;
  current status unconfirmed).

## 4. Summary table: what each process type has today versus what Beryllium targets

| Process | FreeBSD today | OpenBSD today | Beryllium target (phase) |
|---|---|---|---|
| Browser | unconfined | pledge from file, unveil from file | unconfined but hardened launcher; jail-profile aware (4) |
| Renderer | `RLIMIT_DATA` only | pledge `stdio rpath flock prot_exec recvfd sendfd ps`, unveil `/dev/null` | capability mode, allowlisted and rights-limited descriptors, trace disabled, fail closed (2) |
| PDF, print, image, generic utility | unconfined | utility pledge | renderer-like capability mode (3) |
| Audio | unconfined | pledge from file, unveil `~/.sndio` | capability mode with pre-connected audio descriptor (3) |
| Network | unconfined (feature flag on, hook no-op) | pledge from file, unveil profile network dirs | rights-limited descriptors, filesystem reach restricted, `cap_net`/`cap_dns` evaluated (3) |
| GPU | unconfined, Vulkan ICDs preloaded | pledge with `drm`, unveil `/dev/dri` and Mesa dirs | capability mode with DRM ioctl allowlist as far as drivers allow; residual risk documented (3) |
| CDM (foreign-cdm) | unconfined, opt-in | pledge `stdio rpath flock recvfd sendfd`, unveil CDM dirs | policy or documented unsandboxed opt-in (3) |
| Crash handler | not started | not started | not started; core dump policy documented (1) |
