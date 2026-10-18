# Beryllium: Build and Porting Plan

**Status:** Draft plan, no code written
**Date:** 18 October 2026
**Implements:** spec section 11 and Phase 1 of section 12
**Depends on:** [05-PATCH-STRATEGY.md](05-PATCH-STRATEGY.md) for the layering order

---

## 1. Shape of the port

`freebsd/ports/www/beryllium` is a full standalone port modelled on
`www/chromium` (current layout, 154-era build steps) and
`www/ungoogled-chromium` (the pattern for running Helium's tooling inside the
framework). It is not a slave port of `www/chromium`: the two ports pin
different Chromium versions by design, and slave ports cannot do that.

A second port, `www/beryllium-devel`, is a slave of `www/beryllium`
(`MASTERDIR`) that flips the fail-closed build flag off, keeps the debug
switches and sandbox test hooks, builds `is_component_build=true` for faster
iteration, and installs under a distinct package name with `CONFLICTS` set.

## 2. Source acquisition

### 2.1 Chromium tree

Primary: Helium's `chromium-<ver>-base.tar.zst`, because Helium's
`pruning.list` and `domain_substitution.list` are regenerated against it in
Helium CI, which removes the layout-mismatch risk (R1). Facts to design around:

- 1.96 GB compressed, 8.6 GB and 587k files unpacked. `USES=tar:zst` (or an
  explicit `zstd` extract dependency) and a `WRKDIR` on a filesystem with
  inode headroom; the port prints the same 1.5 million inode warning as
  `www/chromium`.
- `distinfo` records the sha256 from the release's `.hashes` file. The port's
  `MASTER_SITES` lists `tarballs.imput.net` first and a Beryllium-controlled
  mirror second; the plan keeps every tarball a release was built from on that
  mirror (R2).
- The base layer bundles Google's prebuilt `third_party/depot_tools`,
  `third_party/node` (Linux node and node_modules), `third_party/rust-toolchain`,
  `third_party/cpython3` and `third_party/widevine`. Pruning (stage 1) deletes
  the binaries that `pruning.list` names; the port's `pre-configure` then
  symlinks host tools exactly as `www/chromium` does (`third_party/node/freebsd/node-freebsd/bin/node`,
  `third_party/rust-toolchain/bin/rustc`, `third_party/gperf/cipd/bin/gperf`,
  `buildtools/freebsd/{gn,clang-format,strip}`) and a check fails the build if
  any remaining ELF under those trees is a Linux binary (R20). The `node_modules`
  shipped in the base layer are a bonus: `www/chromium` has to reconstruct
  rollup and esbuild from GitHub tuples; Phase 1 determines whether Helium's
  bundled `node_modules` plus the port's neutral esbuild rebuild is enough.

Fallback: the official `chromium-<ver>-lite.tar.xz` from Google (what
`www/ungoogled-chromium` uses) or the `chromium-linux-tarballs` `-linux`
tarball (what `www/chromium` uses). Both will need a check that the prune and
substitution lists apply without missing files; the roadmap's Phase 0 item 7
measures this once.

Not used: `utils/downloads.py` at build time (the framework fetches and
verifies all distfiles), `utils/clone.py` (needs `gclient` and network).

### 2.2 Helium dependencies

`deps.ini` becomes three more `DISTFILES` with hashes in `distinfo`:

| Dep | Output path | Note |
|---|---|---|
| `nonfree-search-engines-data-<ver>.tar.gz` | `third_party/search_engines_data/resources_internal` | licence status decides whether it ships (Q5); if not, the port substitutes Chromium's free defaults and documents the difference |
| `helium-onboarding-<ver>.tar.gz` | `components/helium_onboarding` | Svelte build output, no toolchain needed |
| `uBlock0_<ver>.chromium.zip` | `third_party/ublock` | `strip_leading_dirs`; the comment in `deps.ini` about re-stripping `assets.json` applies when bumping |

Plus `www/chromium`'s extra distfiles that Beryllium still needs: PulseAudio
16.1 headers (if the PULSEAUDIO option stays), the vendored TypeScript tarball
and the rollup/esbuild/TypeScript GitHub tuples unless the base layer's
`node_modules` make them unnecessary, and the `-profdata` tarball only if PGO
is ever enabled (not in Phase 1; Helium sets `chrome_pgo_phase=0`).

### 2.3 Beryllium and Helium sources

The port's `PATCH_DEPENDS` are `gpatch` and Python (3.11 or newer; Helium's
tooling pins 3.10 for its own repo but runs on newer). `BUILD_DEPENDS` adds
`py-pillow` and `py-requests` only if `generate_resources.py` and
`i18n_apply.py` need them (helium-linux installs both).

GitHub archive tarballs do not include submodules, so the port lists two
`GH_TUPLE` entries: `johnjanik:Beryllium:<beryllium tag>` and
`imputnet:helium:<commit recorded in the submodule>:helium`, the second
extracted into the first's `helium/` directory. This is the same mechanism
`www/ungoogled-chromium` uses to fetch `ungoogled-software/ungoogled-chromium`
at `UGVERSION`, so a Poudriere build is self-contained. A port-time check
compares the Helium tuple's commit with the submodule pointer at the
Beryllium tag and fails on a mismatch.

## 3. Build stages in port targets

| Port target | Beryllium action |
|---|---|
| `pre-everything` | print memory, disk and inode requirements; refuse on `aarch64` until supported |
| `post-extract` | verify the extracted tree matches the per-file manifest from the tarball's `.metadata.zip` for a sampled subset (cheap integrity check beyond the archive hash) |
| `pre-patch` | stage 1: `utils/prune_binaries.py --keep-build-dependencies ${WRKSRC} pruning.list` |
| `do-patch` (framework) | stage 2: `files/patch-*` (the imported BSD set) |
| `post-patch` | stages 3 and 4 in one call: `PATCH_BIN=gpatch helium/utils/patches.py apply ${WRKSRC} helium/patches patches` (Helium's series, then Beryllium's, as helium-linux does); stage 5: `helium/utils/domain_substitution.py apply -r helium/domain_regex.list -f helium/domain_substitution.list -c ${WRKSRC}/domsubcache.tar.gz ${WRKSRC}`; stage 6: `helium/utils/name_substitution.py --sub`; stage 7: `helium/utils/i18n_apply.py`, `helium/utils/helium_version.py --tree helium --platform-tree . --chromium-tree ${WRKSRC}`, `helium/utils/generate_resources.py`, `helium/utils/replace_resources.py`; unpack the three deps into their output paths |
| `pre-configure` | `www/chromium`'s steps: `replace_gn_files.py --system-libraries ...`, FFmpeg configure for `freebsd/${FFMPEG_TARGET}`, `REINPLACE` of `${LOCALBASE}` and `${MODCLANG_VERSION}` in the rust and strip gni files, tool symlinks, the Linux-ELF check |
| `do-configure` | bootstrap GN (`tools/gn/bootstrap/bootstrap.py ${GN_BOOTSTRAP_FLAGS}`); `gn gen --args="$(freebsd/tools/gnargs-from-flags)" out/${BUILDTYPE}`; the `--fail-on-unused-args` that helium-linux uses is tried and kept if the FreeBSD fragment is clean |
| `do-build` | `ninja -C out/${BUILDTYPE} chrome` (plus `chromedriver` under DRIVER); siso and remote execution are not used |
| `do-install` | `www/chromium`'s layout under `${DATADIR}` = `share/beryllium`, binary installed as `beryllium`, wrapper `bin/beryllium`, man page, icons, `.desktop`, ANGLE/EGL/Vulkan/SwiftShader libraries; `helium-linux`'s `rename-chrome-binary` is mirrored by a Beryllium platform patch so internal paths agree |
| `post-install` | emit `freebsd/tools/build-manifest` output into `${DATADIR}/BUILD-MANIFEST.json`; emit the licence manifest |

## 4. GN arguments

Generated, never hand-copied (R14). `freebsd/tools/gnargs-from-flags` concatenates:

1. `helium/flags.gn` (17 privacy and build-policy arguments).
2. `flags.freebsd.gn`: the platform fragment, derived from
   `www/chromium`'s `GN_ARGS` with the privacy-relevant keys removed
   (`enable_hangout_services_extension=true` and `google_api_key` are the two
   that conflict) and Helium Linux's `flags.linux.gn` consulted for anything
   FreeBSD should match (`proprietary_codecs`, `ffmpeg_branding`,
   `rtc_use_pipewire`, `use_vaapi` when the BSD VA-API path is confirmed
   working, `is_official_build=true`, `symbol_level`).
3. Option-driven arguments from the Makefile (`use_sndio`, `use_alsa`,
   `use_pulseaudio`, `use_cups`, `use_kerberos`, `use_thin_lto`, DEBUG
   settings), passed through as today.
4. The fail-closed flag (`beryllium_sandbox_required=true` in `www/beryllium`,
   `false` in `-devel`), added by the Beryllium build-config patch in Phase 2.

Expected FreeBSD fragment at the snapshot (to be confirmed by a first build):

```text
is_clang=true use_lld=true use_sysroot=false use_custom_libcxx=true use_custom_libunwind=true
use_aura=true toolkit_views=true use_qt5=true moc_qt5_path="..." optimize_webui=true
icu_use_data_file=false use_allocator_shim=false use_partition_alloc=true
use_partition_alloc_as_malloc=false enable_backup_ref_ptr_support=false
use_system_freetype=false use_system_harfbuzz=true use_system_libffi=true use_system_libjpeg=true
use_udev=false enable_rust=true rust_sysroot_absolute="${LOCALBASE}" use_typescript_go=false
fatal_linker_warnings=false extra_cxxflags="..." extra_ldflags="..." ffmpeg_branding="..."
is_official_build=true is_debug=false symbol_level=0 blink_symbol_level=0
```

Note `use_system_libffi` differs between the FreeBSD port (`true`) and Helium
Linux (`false`); FreeBSD's value wins since it is a platform fact.

## 5. Toolchain and dependencies

Carried over from `www/chromium` 154 unchanged unless the 155 import changes
them: LLVM 22 via `BINARY_ALIAS`, `lang/rust` with `RUSTC_BOOTSTRAP=1`,
`rust-bindgen-cli`, `www/node`, Go for `tsgo` (or `lang/typescript-go`),
`devel/esbuild`, cargo for the rollup native binding, Qt5 build tools, nasm on
amd64, the 35 library dependencies, `xdg-utils` and `noto-basic` at runtime.

Hardening audit (spec 11.2), done once in Phase 1 and recorded in the build
manifest: confirm PIE, RELRO, stack protector and `-fstack-clash-protection`
status of the produced `beryllium` binary with `readelf`/`checksec`-style
checks; record whether `is_cfi` is on (Helium Linux requires it; Chromium
turns it on for official Linux x64 builds, and whether the FreeBSD toolchain
and the BSD patch set keep it is unknown until tried); do not change
`treat_warnings_as_errors` or `fatal_linker_warnings` to hide problems.

## 6. Build infrastructure

- Poudriere on the build host with one jail per supported branch; `USE_TMPFS`
  limited to `wrkdir` only if RAM allows, otherwise off (several past
  stable/14 failures were tied to `USE_TMPFS=all`).
- `ccache` for `beryllium-devel` iteration; not for release builds, so the
  manifest reflects a clean build.
- Expect many hours per full build on a workstation. The FreeBSD package
  cluster times out on `www/chromium` regularly; Beryllium's CI uses a
  generous timeout and builds nightly rather than per commit.
- Overlay use: `poudriere bulk -O beryllium-overlay www/beryllium` with the
  `freebsd/ports` directory as the overlay, so the port can be consumed before
  it is in the tree.

## 7. Package layout and install

Follows `www/chromium` and the ungoogled port's renaming: everything under
`share/beryllium`, launcher `bin/beryllium`, `beryllium-chromedriver` under the
DRIVER option, icons under the `beryllium` name, `.desktop` file
`beryllium.desktop`, man page `beryllium.1`.

Wrapper script changes relative to `chrome.in`:

- The `kern.ipc.shm_allow_removed` check stays until Phase 2 removes the
  SysV shm dependency from confined processes; the message names Beryllium.
- `ulimit -c 0` is kept in the production wrapper and dropped in `-devel`.
- The foreign-cdm environment sourcing stays under the WIDEVINE option.
- No sandbox-related switches are ever added by the wrapper.

`pkg-message`: update channel is `pkg`; kernel requirements (`COMPAT_FREEBSD11`
until the sysctl work lands; the advisory preflight list); the sandbox status
of this release in one paragraph; how to report bugs.

## 8. Phase 1 acceptance

From the roadmap: package installs and removes cleanly; the browser starts on
X11 and Wayland; onboarding appears as `helium://setup` with Beryllium
branding; uBlock component present and active; the privacy capture baseline
recorded; `BUILD-MANIFEST.json` present; the known-limitations list written.
No sandbox claim is made in Phase 1 release notes beyond "same as
`www/chromium`: none".
