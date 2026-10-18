# Beryllium: Architecture

**Status:** Draft plan, no code written
**Date:** 18 October 2026
**Implements:** spec section 5 (target process architecture) and the repository/build architecture implied by sections 4 and 11

---

## 1. Three architectures, one document

Beryllium has a source architecture (how four upstreams become one tree), a
build architecture (how that tree becomes a package reproducibly), and a
runtime architecture (which processes exist, what each may touch, and who
enforces it). The first two are summarised here and detailed in
[05-PATCH-STRATEGY.md](05-PATCH-STRATEGY.md) and
[04-BUILD-AND-PORTING-PLAN.md](04-BUILD-AND-PORTING-PLAN.md); the third is
the subject of this document and of [06-SECURITY-MODEL.md](06-SECURITY-MODEL.md).

## 2. Source architecture

```text
            Chromium 155.0.8059.84 (Helium's prepared base tarball)
                             |
        stage 1: prune binaries (Helium pruning.list)
                             |
        stage 2: BSD platform patches  <-- imported from FreeBSD + OpenBSD ports, never hand-edited
                             |
        stage 3: Helium series (346 patches: ungoogled, inox, iridium, bromite, debian, brave, helium)
                             |
        stage 4: Beryllium series (platform, branding, security)
                             |
        stage 5-7: domain substitution, name substitution, i18n, version, resources, deps
                             |
                     prepared Beryllium tree  ->  GN (helium/flags.gn + flags.freebsd.gn + options)  ->  ninja
```

Ownership: stage 2 is owned by the BSD port maintainers (imported), stage 3 by
Helium (pinned submodule), stage 4 by Beryllium (authored). Only stage 4 is
Beryllium's to change; everything else changes by moving a pin.

## 3. Build architecture

```text
 johnjanik/Beryllium (git)                     FreeBSD build host
 ├── helium/ (submodule at a Helium tag)        ┌──────────────────────────────┐
 ├── patches/ (Beryllium series)                │ Poudriere jail per branch    │
 ├── freebsd/ports/www/beryllium  ──overlay──>  │   fetch: base tarball, deps, │
 ├── flags.freebsd.gn, revision.txt             │   Beryllium + Helium tuples  │
 ├── freebsd/tools/*                            │   stages 1-7, gn, ninja      │
 └── freebsd/tests/*                            │   stage-qa, plist, manifest  │
                                                └───────────┬──────────────────┘
                                                            │ signed pkg repo
                                                            v
                                     test VMs (14.x, 15.x; X11 + Wayland) run the suites
```

Invariants: the build needs no network beyond the framework's fetch step; no
credentials; no maintainer home directory; nothing from a Linux toolchain. The
manifest ties every artefact to the five commits that produced it (Chromium
version, Helium commit, Beryllium commit, FreeBSD ports commit, OpenBSD ports
commit).

## 4. Runtime process architecture

Chromium on FreeBSD today has the same process types as Linux minus the
zygote: the browser forks and execs every child directly with
`base::LaunchProcess` and a descriptor remap table. Beryllium keeps that
model in Phase 1 and 2. Whether to reintroduce a zygote (as the shkhln
prototype does, to share Casper channels) is a Phase 2 decision; a zygote
makes descriptor inheritance harder to audit, which argues against it unless
Casper sharing proves necessary.

### 4.1 Process map and trust boundaries

```text
                     ┌───────────────────────────────────────────────┐
  user session       │ browser process (TCB)                         │
  X11/Wayland ◄─────►│  UI, profile, prefs, permissions, downloads,  │
  dbus, portals      │  file chooser, child launcher, Mojo broker,   │
  ~/.config, ~/.cache│  font service, discardable memory manager     │
                     └───┬──────────┬──────────┬──────────┬──────────┘
                         │ Mojo     │ Mojo     │ Mojo     │ Mojo
                         ▼          ▼          ▼          ▼
                     ┌────────┐ ┌────────┐ ┌─────────┐ ┌───────────┐
                     │renderer│ │network │ │  GPU    │ │ utilities │
                     │(per    │ │service │ │ process │ │ audio,pdf,│
                     │ site)  │ │        │ │         │ │ print,... │
                     └────────┘ └───┬────┘ └────┬────┘ └───────────┘
                      Capsicum   sockets,    /dev/dri,    per-type
                      cap mode   NSS db      Mesa, Vulkan policies
```

Every arrow is a Mojo channel over a Unix socketpair created by the browser
and passed to the child at launch. Shared memory regions are passed as
descriptors over those channels. The browser is the only process that owns
the profile. The network service is the only process that owns Internet
sockets. The GPU process is the only process that opens `/dev/dri`. Renderers
own nothing but CPU, memory, and what they were handed.

### 4.2 Authority matrix (target)

The spec's table (section 5) restated with FreeBSD mechanisms and the phase
that delivers each row. "Enforced by" names the kernel feature; "verified by"
names the test suite from [08-TESTING-AND-VERIFICATION.md](08-TESTING-AND-VERIFICATION.md).

| Process | Must be able to | Must not be able to | Enforced by | Phase |
|---|---|---|---|---|
| Browser | everything a user may do; launch children; broker files, fonts, shared memory, permissions | run as root; pass broad descriptors to children; expose unauthenticated helper APIs | design review, launcher descriptor hygiene (`closefrom` before exec), IPC validation; optional jail | 1-2 (hygiene), 4 (jail) |
| Renderer | compute; talk to its Mojo channel; map passed shared memory; read passed resource paks and ICU data; log to a passed descriptor | open any path; create or connect sockets; signal, trace or inspect other processes; `dlopen` by path; create named shared memory; read the profile | `cap_enter`, `cap_rights_limit` on every retained fd, `cap_ioctls_limit`/`cap_fcntls_limit`, `procctl` trace disable, `RLIMIT_DATA`; browser-side IPC checks | 2 |
| PDF, print compositor, data decoder, generic utility and service | as renderer, plus what the specific service needs (print compositor: none extra) | as renderer | same as renderer with a per-type allowlist | 3 |
| Audio service | read/write a pre-opened audio device or pre-connected sndio/PulseAudio socket; shared memory with renderers | open other devices; network; profile | `cap_enter` with the device/socket pre-opened in the hook, ioctl allowlist for `/dev/dsp` | 3 |
| Network service | create sockets, resolve names, read NSS database and the profile's network directory, write cookies and cache | read the rest of the profile or home; exec | `cap_rights_limit` on fds, filesystem reach by pre-opened directory capabilities with `O_RESOLVE_BENEATH`; capability mode with `cap_net`/`cap_dns` only if measured viable; otherwise documented as partially confined | 3 |
| GPU process | `/dev/dri/*` with an ioctl allowlist, Mesa shader cache directory, Vulkan ICD libraries pre-loaded, shared memory and dma-buf descriptors | home directory, profile, network, other devices | `cap_enter` after the pre-sandbox hook pre-opens devices and loads drivers; `cap_ioctls_limit` on DRM fds | 3 |
| CDM (foreign-cdm) | its library directory and the per-profile CDM storage | anything else | policy modelled on OpenBSD `unveil.cdm`, or unsandboxed opt-in with a warning | 3 |
| Crash handler | none (not started on BSD) | | | 1 (documented) |
| Updater | none (pkg) | | | 1 |

### 4.3 Brokered resources

Everything a confined process needs from the namespace is provided through
one of three routes, listed in order of preference:

1. **Passed at launch** (the browser opens, limits rights, and remaps into the
   child's descriptor table): Mojo channel, resource paks, ICU data, V8
   snapshot, log descriptor, `/dev/null` for stdio. Static, auditable, in the
   allowlist file.
2. **Passed over Mojo on demand** (the browser or a service opens and sends a
   descriptor): font files via the `FontService`, shared memory regions, files
   the user picked in the chooser, download targets, dma-bufs from the GPU
   process. Already how Chromium works on Linux; on FreeBSD the renderer's
   `FontService` binding is present in the BSD patch set.
3. **Casper services** (`cap_sysctl`, `cap_dns`, `cap_net`, `cap_fileargs`):
   for libc-level needs that neither of the above covers. Used only where a
   process genuinely needs the capability (the network service for DNS and
   connect; possibly `cap_sysctl` for process metrics if caching before entry
   proves insufficient). Each Casper channel is itself a descriptor in the
   allowlist with a documented reason.

What is not acceptable: an `LD_PRELOAD`-style interceptor that silently turns
path opens into broker calls for the renderer. Interceptors are a useful
diagnostic (Phase 2 inventory) and the shkhln prototype's choice for broad
compatibility, but a production renderer policy whose correctness depends on
intercepting every libc path call is hard to audit. If evaluation shows that
the renderer genuinely needs path opens after startup beyond fonts and
timezone, the plan is to fix those call sites (pre-open, pass over Mojo), and
to treat any remaining interceptor as a documented exception with its own
test.

### 4.4 Shared memory

Three mechanisms exist in the FreeBSD tree today and each needs a decision:

| Use | Today on FreeBSD | Capability-mode status | Plan |
|---|---|---|---|
| `base::PlatformSharedMemoryRegion::Create` (Mojo data pipes, discardable memory, canvas, media buffers) | temporary file in the temp directory, unlinked after open (upstream's non-Linux POSIX path; Linux uses `memfd_create` with seals) | fails in a confined process (path open); but Mojo non-broker processes delegate allocation to the browser unless configured otherwise, so renderers may rarely hit it | switch FreeBSD to `memfd_create(2)` with seals (FreeBSD 13 and later) reusing the Linux path, `shm_open(SHM_ANON)` as fallback; count direct creations in the Phase 2 inventory; Phase 2 |
| `DiscardableSharedMemoryManager` | browser-side allocation, regions passed to children | fine | none |
| X11 MIT-SHM image pool (`ui/base/x/x11_shm_image_pool.cc`) | SysV `shmget`/`shmat`/`IPC_RMID` (the reason for `kern.ipc.shm_allow_removed=1`) | SysV IPC is a global namespace, unavailable in capability mode | confirm it runs only in the browser and GPU processes; if so, unaffected in Phase 2; the sysctl requirement is dropped only if the pool is replaced, which is not planned |

### 4.5 Fonts

On Linux, sandboxed renderers never open font files: Skia's
`SkFontConfigInterface` is backed by the Mojo `FontService` in the browser,
which matches with fontconfig and sends file descriptors. The BSD patch set
keeps that binding (`RendererBlinkPlatformImpl` patched for `IS_BSD`) but also
calls `gfx::InitializeFonts()` in the renderer's `PreinitializeSandbox`, which
initialises fontconfig in-process and reads `/etc/fonts` and the caches. The
Phase 2 inventory determines whether any font file is opened by path after
that point (Blink's `FontCache`, `FontUniqueNameLookup`, emoji and CJK
fallback, PDFium's font mapper in the PDF utility). The target is: fontconfig
initialised before `cap_enter`, all later font access through `FontService`,
and a renderer allowlist without any font directory capability. OpenBSD
reaches the same state (renderer unveils only `/dev/null`), which is evidence
it is achievable with this patch lineage.

### 4.6 Timezone, locale, random, logging

- Timezone: ICU and libc both consult `/etc/localtime` and the zoneinfo
  directory. Pre-read before entry with `caph_cache_tzdata()` plus ICU's
  default timezone in `PreinitializeSandbox` (upstream Linux does the
  equivalent in `InitLibcLocaltimeFunctions()`; the shkhln prototype needed
  a `localtime_r` deadlock workaround, to be understood before reuse).
- Locale and ICU data: `icu_use_data_file=false` in the FreeBSD port means
  ICU data is compiled in; resource paks are passed at launch.
- Random: `arc4random` in base's `rand_util_posix` (BSD patch) needs no
  descriptor; verify nothing reopens `/dev/urandom`.
- Logging: a descriptor passed at launch; `VLOG`/`LOG` to stderr is `/dev/null`
  in production unless `--enable-logging` points to a passed file.
- `sysctl`: `base::SysInfo`, process metrics and thread utilities read
  `hw.*`, `kern.*`, `vm.*` sysctls; in capability mode `__sysctl` is permitted
  only for nodes flagged `CTLFLAG_CAPRD`, which excludes most of these (the
  2023 attempt died at `vm.stats.vm.v_page_count`). Cache in
  `PreinitializeSandbox` (the stub already warms three values), and route
  anything that must be live through `cap_sysctl` as a documented exception.
  The shkhln prototype's allowlist (`hw.machine`, `hw.ncpu`, `hw.realmem`,
  `kern.hostname`, `kern.ipc.shmmax`, `kern.osrelease`, `kern.ostype`,
  `kern.version`, `hw.dri` recursive, `kern.devname`, `net.routetable`,
  `vm.stats.vm`) is the starting inventory of what Chromium actually reads.

### 4.7 Desktop integration boundaries

The browser process talks to X11 or Wayland, D-Bus (notifications, portals),
the clipboard, `xdg-open`, CUPS and the GTK file chooser. None of these
sockets or descriptors are passed to any child; the sandbox suite checks that
no renderer can reach the display socket. The optional jail profile (Phase 4)
is where the display path is deliberately exposed, and its documentation
states that the compositor is a trust boundary, not isolation.

## 5. Status reporting architecture

`chrome://sandbox` on FreeBSD today renders no status rows at all, because
upstream's Linux status block is compiled only for `IS_LINUX`/`IS_CHROMEOS`.
Beryllium adds a FreeBSD block generated from a Beryllium-specific status
bitmask returned by `SandboxLinux::GetStatus()`:
capability mode entered, descriptor rights limited, ioctl and fcntl limits
applied, trace disabled, `RLIMIT_DATA` applied, fail-closed build, kernel
advisory preflight result. Each row says "enforced" only if the process
reporting it checked it at runtime (`cap_getmode`, `procctl` query), never
from build flags alone. The same bitmask is written to the structured startup
log line and read by the sandbox suite.
