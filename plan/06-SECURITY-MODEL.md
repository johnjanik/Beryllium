# Beryllium: Security Model and Capsicum Sandbox Design

**Status:** Draft plan, no code written
**Date:** 18 October 2026
**Implements:** spec sections 5 to 9 (process architecture, Capsicum renderer sandbox, jails, resource controls, MAC)
**Related:** [03-ARCHITECTURE.md](03-ARCHITECTURE.md) section 4 for the process map and brokered resources; [08-TESTING-AND-VERIFICATION.md](08-TESTING-AND-VERIFICATION.md) for the proof obligations

---

## 1. Layers, in the order they are built and in the order they matter

| Layer | Protects against | Status at snapshot | Phase |
|---|---|---|---|
| 1. Renderer Capsicum policy | a compromised renderer reaching files, network, devices, other processes | absent (RLIMIT_DATA only) | 2 |
| 2. Launcher descriptor hygiene and IPC validation | authority leaking into any child; confused-deputy via Mojo | partial (Chromium's own IPC checks; no descriptor closing beyond CLOEXEC) | 2 |
| 3. Per-process policies for utilities, audio, network, GPU, CDM | same as 1 for the other high-risk processes | absent | 3 |
| 4. Process-control hardening (`procctl`) | tracing, privilege gain, signal abuse within the user's session | absent | 2 |
| 5. Resource limits (`rlimit`, optional `rctl`) | denial of service | RLIMIT_DATA only | 2 (rlimit), 4 (rctl) |
| 6. Optional whole-browser jail | filesystem and device exposure of the whole browser; blast radius of a browser-process compromise | none | 4 |
| 7. MAC (study only) | residual confidentiality flows if any | none | 5 |

Layer 1 is the milestone; nothing else is allowed to stand in for it.

## 2. Capsicum facts the design relies on

To be confirmed by the standalone oracle on each supported branch (the test
suite exists precisely because these are the load-bearing assumptions):

- `cap_enter(2)` is irreversible and inherited by children; `cap_getmode(2)`
  reports it. `procctl(2)` is not permitted in capability mode, so every
  `procctl` call (trace disable, no-new-privs, `PROC_TRAPCAP_CTL`) must come
  before `cap_enter`.
- Debug aid: `procctl(PROC_TRAPCAP_CTL, PROC_TRAPCAP_CTL_ENABLE)` (or the
  `kern.trap_enotcap` sysctl) makes the kernel deliver `SIGTRAP` with
  `si_code=TRAP_CAP` on every `ECAPMODE`/`ENOTCAPABLE` failure. `beryllium-devel`
  enables it during the Phase 2 inventory so that every namespace access a
  renderer attempts after lockdown is caught with a stack trace rather than
  surfacing as a silent feature failure.
- In capability mode, system calls that name global namespaces fail with
  `ECAPMODE` (per `sys/kern/syscalls.master`, which marks each call
  CAPENABLED or not): `open`, `access`, `stat`, `readlink`, `unlink`, `mkdir`,
  `rename`, `chdir`, `execve`, `connect`, `bind`, `shm_unlink`, `procctl`,
  `chroot`, `truncate`, `statfs` and the mount, jail and kld families. `socket`
  itself succeeds; only `connect`/`bind` fail, with `connectat`/`bindat`
  relative to a directory capability (`CAP_CONNECTAT`/`CAP_BINDAT`) remaining
  available for Unix sockets, which is how a confined audio or GPU process can
  reach a pre-opened socket directory. `kill` is restricted to the caller's own
  pid. `openat` must be strictly relative to the directory descriptor; absolute
  paths and `..` escapes fail with `ENOTCAPABLE`. `__sysctl` is permitted but
  each node must carry `CTLFLAG_CAPRD`; most `kern.*` and `vm.*` reads do not,
  which is where the 2023 attempt died. `ptrace` is marked CAPENABLED and
  whether it is restricted to self in capability mode is unconfirmed, hence
  the oracle test and the `procctl` trace-disable regardless. `dlopen` by path
  fails because it opens by path.
- Operations on already-held descriptors continue to work, limited by
  `cap_rights_limit(2)`, `cap_ioctls_limit(2)` and `cap_fcntls_limit(2)`:
  reads, writes, `mmap`, `fstat`, `kqueue` on them, `recvmsg` with
  `SCM_RIGHTS` (so Mojo keeps working), `openat` beneath a directory
  capability (with `CAP_LOOKUP`), `fork`, thread creation, anonymous `mmap`
  including `PROT_EXEC` (V8 and WebAssembly need it).
- `shm_open(SHM_ANON, ...)` and `memfd_create(2)` work in capability mode.
- A descriptor passed into capability mode carries whatever authority it
  had: a connected socket still sends and receives; a directory descriptor
  with `CAP_LOOKUP` still reaches everything beneath it. This is why the
  allowlist, not `cap_enter`, is the policy.
- `FreeBSD-SA-26:28.capsicum` (9 June 2026): `sigqueue(2)` lacked the
  capability-mode restriction; fixed on supported 14.x and 15.x branches. The
  oracle tests it; the preflight warns on older kernels.
- Casper (`libcasper`) services provide brokered DNS (`cap_dns`, obsolete in
  favour of `cap_net`), network (`cap_net`: `cap_connect`, `cap_bind`,
  `cap_getaddrinfo`, with `cap_net_limit` modes and address/domain limits),
  sysctl (`cap_sysctl` with per-name read/write/recursive limits), file
  arguments (`cap_fileargs`) over a Unix socket descriptor established before
  `cap_enter`; channels can be passed over `SCM_RIGHTS`; each is a descriptor
  in the allowlist. Casper channels are reentrant but not thread-safe, which
  matters in a multithreaded renderer.
- `libcapsicum` helpers exist for the common warm-ups and are preferred over
  hand-written equivalents: `caph_cache_tzdata()` (timezone),
  `caph_cache_catpages()`, `caph_limit_stdio()`, `caph_enter_casper()`.
- Chromium's own Linux `InitializeSandbox` already performs two warm-ups
  that have FreeBSD analogues and must be kept: `InitLibcLocaltimeFunctions()`
  (timezone before lockdown) and `DiscourageGetaddrinfo()` ("no sandboxed
  process should make use of getaddrinfo()").

## 3. Renderer policy (Phase 2)

### 3.1 Lifecycle and lockdown point

```text
browser: ChildProcessLauncherHelper
   build fds_to_remap = {Mojo channel (socketpair), V8 snapshot, field-trial and
                         shared-files descriptors, log, /dev/null x3}
   for each fd: cap_rights_limit to its role            <- browser side, before fork
   fork; in child: dup2 shuffle, then base::CloseSuperfluousFds (reads /dev/fd on
         FreeBSD: only lists 0-2 unless fdescfs is mounted, so Beryllium adds
         closefrom(2) after the shuffle as the authoritative step)
   exec beryllium --type=renderer ...

renderer: ContentMainRunner -> RendererMain
   PreinitializeSandbox(kRenderer)
      warm: SysInfo values, tzset + ICU default timezone, fontconfig init,
            locale, arc4random, any dlopen'able library the renderer may need
   InitializeSandbox(kRenderer)
      IncreaseFdLimitTo(4096) as upstream does (RLIMIT_NOFILE before lockdown)
      verify every open fd is in the allowlist (kinfo_getfile(3) walk); abort on
        extras in production
      re-apply cap_rights_limit / cap_ioctls_limit / cap_fcntls_limit per role
      caph_cache_tzdata(); caph_limit_stdio()
      procctl(PROC_TRACE_CTL_DISABLE), procctl(PROC_NO_NEW_PRIVS_CTL)   <- before cap_enter, procctl is not CAPENABLED
      setrlimit(RLIMIT_DATA, policy value)
      cap_enter(); CHECK(cap_getmode() == 1)
      record status bitmask; write structured log line
      production: any failure above -> LOG + _exit(kSandboxFailed)
      devel: failure -> LOG, continue, status says "NOT SANDBOXED"
   RendererMainPlatformDelegate::EnableSandbox returns status
   ... first untrusted content only after this point
```

The lockdown point is the same `InitializeSandbox` call site the BSD stub
already has, which keeps Beryllium's change local to
`sandbox/policy/freebsd/sandbox_freebsd.cc` plus the launcher and the shared
memory primitive.

### 3.2 Expected renderer descriptor allowlist

Derived from how Chromium launches renderers on POSIX without a zygote, to be
replaced by the measured inventory in Phase 2. Rights are the maximum; the
inventory may lower them.

| Role | Opened by | Rights | Notes |
|---|---|---|---|
| stdin, stdout, stderr | browser (`/dev/null`, or the log file for stderr in devel) | stdin `CAP_READ`; stdout/stderr `CAP_WRITE` | must never be a terminal; the 2023 patch limited exactly these |
| Mojo invitation channel (socketpair) | browser | `CAP_READ CAP_WRITE CAP_EVENT CAP_RECV CAP_SEND CAP_FSTAT` plus `CAP_FCNTL` for `F_GETFL/F_SETFL` only | `SCM_RIGHTS` reception needed; no `CAP_CONNECT`/`CAP_BIND` |
| Resource paks (`resources.pak`, `chrome_100_percent.pak`, locale pak) | browser (`OpenFileToShare`) | `CAP_READ CAP_SEEK CAP_FSTAT CAP_MMAP_R` | memory-mapped read-only |
| V8 snapshot, ICU data if file-based | browser | same as paks | `icu_use_data_file=false` on FreeBSD removes the ICU one |
| Shared memory regions passed later | browser/GPU over Mojo | `CAP_READ CAP_WRITE CAP_MMAP_RW CAP_FSTAT` (`CAP_MMAP_RWX` only for the executable region type if used) | arrive after lockdown via `SCM_RIGHTS`; rights limited by the sender before sending |
| Font file descriptors | browser `FontService` over Mojo | `CAP_READ CAP_SEEK CAP_FSTAT CAP_MMAP_R` | limited by the browser before sending |
| Casper `cap_sysctl` channel | renderer, before `cap_enter`, only if caching proves insufficient | socket rights | documented exception if present |
| `kqueue` descriptors | renderer itself | created in capability mode, allowed | not inherited |

Explicitly absent: any directory descriptor; any socket other than the Mojo
channel; any profile, cache, cookie, history, local storage or download
descriptor; any device node; `/dev/urandom` (arc4random); the X11 or Wayland
socket; D-Bus; a `/proc`-like descriptor (FreeBSD has none in use).

### 3.3 Shared memory primitive

Facts from upstream: on Linux `PlatformSharedMemoryRegion::Create` uses
`memfd_create` with `F_ADD_SEALS` and opens the read-only twin through
`/proc/self/fd/N`; on every other POSIX platform, including the BSD ports, it
creates and unlinks a temporary file in the temp directory (the comment says
`shm_open` was avoided to support `--disable-dev-shm-usage`). Separately,
Mojo's broker model has non-broker processes delegate shared-memory
allocation synchronously to the broker (the browser) unless
`force_direct_shared_memory_allocation` is set, and a newer configuration flag
lets non-brokers create unsafe regions directly only if the sandbox permits
`memfd_create`, `ftruncate` and `F_ADD_SEALS`. That delegation is presumably
why OpenBSD renderers work with `unveil("/dev/null")` only; it is unconfirmed
where content sets the flag per platform, and the Phase 2 inventory settles
it by counting direct region creations in a renderer.

Design:

- The FreeBSD implementation of `Create` switches to `memfd_create` (FreeBSD
  13 and later, supports `F_ADD_SEALS`) so the Linux code path can be reused
  almost verbatim, with `shm_open(SHM_ANON)` as the fallback for older
  kernels. Both are namespace-free and permitted in capability mode. This is
  the same change the 2010 Capsicum paper's Chromium port made (SysV shm to
  POSIX shm) and it removes the only path-based operation in the primitive.
- The read-only twin: in the browser (not in capability mode) `/dev/fd/N`
  with `O_RDONLY` works like `/proc/self/fd/N`. In a confined process it does
  not; there the twin is a `dup` limited with `cap_rights_limit` to
  `CAP_READ CAP_MMAP_R CAP_FSTAT CAP_SEEK`, which is kernel-enforced
  read-only. `CheckPlatformHandlePermissionsCorrespondToMode` uses
  `fcntl(F_GETFL)`, which still reports `O_RDWR` on such a dup, so the BSD
  version of that check consults `cap_rights_get(3)` instead. Whether confined
  processes ever need to create read-only regions themselves is answered by
  the inventory; if they never do, only the browser-side path matters.
- Regardless of who creates a region, the browser applies `cap_rights_limit`
  before passing a descriptor to a child, so that a region meant to be
  read-only is read-only by kernel rights and not only by mapping convention.
  The sandbox suite checks that a renderer cannot `mmap` a passed read-only
  region writable.

### 3.4 Fail-closed and the production/devel split

- Build flag `beryllium_sandbox_required` (name provisional): true in
  `www/beryllium`, false in `www/beryllium-devel`.
- With the flag true: `--no-sandbox`, `--disable-unveil`, `--no-zygote-sandbox`
  and any switch that would skip `InitializeSandbox` are removed from the
  switch table in `sandbox/policy/switches.cc` by `#if`, so they do not exist
  rather than being ignored; `InitializeSandbox` failure calls `_exit` with a
  distinctive code; the browser shows the renderer-crashed page and
  `chrome://sandbox` shows the failure stage.
- With the flag false: switches exist, failures are logged and the status
  bitmask reports the truth; the package name makes the difference obvious.
- The wrapper script never adds switches (spec 6.1.8).

### 3.5 Diagnostics

A single structured log line per process at the lockdown point, to stderr or
the passed log descriptor, with: process type, sandbox type, stage reached
(fd-audit, rights, procctl, rlimit, cap_enter, verify), result, errno, and the
count (never the names) of unexpected descriptors found. No URLs, paths under
the home directory, or profile data. `chrome://sandbox` renders the same
fields.

## 4. Launcher hygiene and IPC (Phase 2)

- Browser side: `fds_to_remap` is the only inheritance channel. The launcher
  applies `cap_rights_limit` to each mapped descriptor before the fork so a
  bug in the child's own audit cannot widen rights.
- Child side, before `exec`: upstream `base::LaunchProcess` already runs
  `CloseSuperfluousFds` after the `dup2` shuffle by listing `/dev/fd`
  (the FreeBSD and OpenBSD `kFDDir`). On FreeBSD `/dev/fd` lists only 0, 1 and
  2 unless `fdescfs` is mounted, so the upstream step silently does nothing
  useful on a default system. Beryllium adds `closefrom(max(fds_to_remap)+1)`
  plus explicit close of any gap as the authoritative step, so inherited
  descriptors from third-party libraries in the browser (GTK, D-Bus,
  fontconfig, NSS, audio clients) cannot leak. The spec's inventory
  requirement (6.2) is what makes this safe: the child needs nothing the
  remap table does not list. Phase 0 confirms the `/dev/fd` behaviour on each
  branch and whether the BSD patch set already compensates.
- Mojo message validation is Chromium's; Beryllium adds no new browser-side
  interfaces. Every Beryllium change that adds a Mojo interface or a Casper
  channel is a `security-review: required` patch.
- Process identity: the browser must not trust the renderer's claimed site
  or process id from message contents; Chromium's `ChildProcessSecurityPolicy`
  already binds by channel. Beryllium verifies no BSD patch weakens that
  (the `render_process_host_impl` and `browser_child_process_host_impl`
  patches in the BSD set are reviewed in Phase 0).

## 5. Per-process policies (Phase 3)

Each policy is a file under `freebsd/sandbox/policies/<type>.md` with the
same four parts: pre-sandbox warm-up, descriptor allowlist with rights,
Casper channels if any, and the proof tests. Starting shapes:

| Type | Warm-up | Allowlist beyond the renderer base | Open question |
|---|---|---|---|
| PDF (`kPdfConversion`, print compositor) | fonts as renderer; PDFium font mapper | none | PDFium's own font directory scanning on BSD |
| Data decoder, image, generic utility, service with JIT | as renderer | none | |
| Audio | pre-open `/dev/dsp*` (OSS via ALSA shim) or pre-open the directory holding the sndio/PulseAudio socket with `CAP_CONNECTAT` so the service can `connectat` later (the shkhln prototype's approach) | the audio descriptor with `CAP_READ CAP_WRITE CAP_IOCTL` and an OSS ioctl allowlist, or the socket-directory capability | device hot-plug after lockdown needs a restart of the audio service, which Chromium supports; ALSA was left unsandboxed in the prototype |
| Network | NSS init, read `/etc/resolv.conf` and `/etc/hosts` (or `cap_dns`), open the profile's `Network` directory as a directory capability | sockets created on demand require either no capability mode or `cap_net`; directory capability with `CAP_LOOKUP CAP_READ CAP_WRITE CAP_CREATE CAP_FSTAT CAP_UNLINKAT` and `O_RESOLVE_BENEATH` on every open | whether `cap_net` throughput and feature coverage (QUIC/UDP, IPv6, SOCKS) are acceptable; otherwise the network service stays out of capability mode with rights-limited descriptors and restricted filesystem reach, and the matrix says so |
| GPU | existing BSD hook plus: open `/dev/dri/renderD*` and `card*`, `/dev/pci` with an ioctl allowlist (libpci), the Mesa shader cache directory as a capability with create/unlink/rename rights, `~/.Xauthority` and the `/tmp/.X11-unix` directory with `CAP_CONNECTAT` for X11, the Wayland socket directory likewise, library directories with `CAP_MMAP_RX`, load every ICD and driver, warm Vulkan instance creation (the shkhln prototype's GPU policy is the starting inventory) | DRM descriptors with `cap_ioctls_limit` on the DRM ioctl set the driver actually uses (measured), shader cache dir capability, dma-buf descriptors over Mojo | NVIDIA proprietary and VA-API paths; the Vulkan loader re-reading ICD JSON by path after startup; Wayland was a TODO in the prototype |
| CDM | load the CDM library and open its storage directory before entry | library and storage capabilities | foreign-cdm's Linux-compatibility shim may need paths; if so, unsandboxed opt-in |

The rule from the roadmap applies: a process class is either in the matrix
as kernel-enforced with tests, or in the known-limitations page with a risk
statement and an owner.

## 6. Process-control hardening (Phase 2)

Applied in every confined child at the lockdown point:

- `procctl(P_PID, getpid(), PROC_TRACE_CTL, PROC_TRACE_CTL_DISABLE)`: no
  `ptrace` attach to the process, and no core dump of its memory to disk in
  production (a compromised renderer's memory holds page content). Called
  before `cap_enter` because `procctl` is not available inside capability
  mode.
- `procctl(PROC_NO_NEW_PRIVS_CTL, PROC_NO_NEW_PRIVS_ENABLE)`: belt-and-braces
  against setuid execution should `exec` ever become possible.
- `setrlimit`: `RLIMIT_DATA` (per-type value, following OpenBSD's scaled
  table rather than the single `kDataSizeLimit` the FreeBSD stub uses),
  `RLIMIT_NOFILE` to a measured ceiling, `RLIMIT_NPROC` is not per-process
  on FreeBSD so it is left to the resource profiles.
- Signals: capability mode already restricts `kill` to self; the oracle covers
  `sigqueue` after the advisory.

## 7. Resource controls (Phase 2 rlimit, Phase 4 rctl)

Spec section 8 is adopted as written. Specifics:

- Per-process `rlimit` values live in `freebsd/sandbox/policies/limits.json`
  with the workload they were measured on (ordinary browsing, video,
  large web apps, many tabs, WebAssembly, DevTools), so a limit change is a
  reviewable data change.
- Three `rctl` profiles for jail deployments: `desktop` (generous `pcpu`,
  `memoryuse` at half of RAM, `maxproc` 512, `openfiles` 65536), `constrained`
  (laptop values), `jail` (operator-tuned). Delivered as documented rule
  files; never installed by the package.
- Exhaustion tests record which limit fires and which process dies; the
  documentation never claims that a jail-wide limit isolates one tab.

## 8. Optional whole-browser jail (Phase 4)

Spec 7.1 adopted. Design notes specific to the FreeBSD desktop:

- Filesystem: a thin jail (base read-only via `nullfs`, `/usr/local` read-only,
  a dedicated ZFS dataset for the profile and cache, `devfs` ruleset exposing
  `null`, `zero`, `random`, `urandom`, `dri/*` and the chosen audio device).
- Display: X11 by mounting the X socket directory (`/tmp/.X11-unix`) read-write
  and passing `XAUTHORITY`; Wayland by mounting the compositor socket from
  `XDG_RUNTIME_DIR`. The documentation states that X11 gives any client full
  access to input and other windows, Wayland less so but still clipboard and
  input via portals; neither is isolation.
- Network: shared stack with `pf` rules per jail user, or VNET with an
  explicit route and DNS; the renderer policy is unchanged inside the jail.
- Dedicated UID inside the jail; downloads land on a mapped directory the
  user chooses; `xdg-open` from inside the jail cannot reach the host session,
  so external-link handling is either disabled or routed through a documented
  helper outside the jail.
- The example ships as `freebsd/jail/README.md`, `jail.conf.example`,
  `devfs.rules.example`; nothing in the package touches `/etc`.

## 9. MAC study (Phase 5)

Spec section 9 adopted. The study's deliverable is a decision memo answering:
which residual threat from the Phase 2 and 3 reviews a MAC policy would
address; whether `mac_mls` labels on the profile, downloads and `~/.ssh`
give a property Capsicum and jail do not (likely answer: only for the
browser process itself, which is unconfined by design); the cost of
labelling an existing home directory; and the rollback procedure. A
prototype on a disposable system follows only if the memo says yes.

## 10. Status reporting details

Upstream's `chrome://sandbox` Linux block (`sandbox_internals_ui.cc` and the
`sandbox_internals` WebUI resources) is compiled only under `IS_LINUX` or
`IS_CHROMEOS`, so a BSD build shows a page with no status rows. Beryllium
patches the WebUI to render a FreeBSD block from a new status bitmask
(capability mode entered, rights limited, ioctl and fcntl limits applied,
trace disabled, `RLIMIT_DATA` applied, fail-closed build, Casper channels
present, kernel advisory preflight result), obtained per process type from
the browser's record of each child's startup log line rather than from
build flags. Also fixed: `Sandbox::IsProcessSandboxed()` falls through to
`false` on BSD today but returns `true` for any non-browser process started
with `--no-sandbox` (an upstream quirk), which would mislead any code that
consults it; the FreeBSD implementation returns the real capability-mode
state.

## 11. Residual risks the model does not cover

Stated plainly so release notes can copy them:

- The browser process is unconfined by design. A browser-process compromise
  (through a Mojo bug, a GTK or D-Bus bug, or a malicious extension with broad
  permissions) has the user's full authority minus whatever the optional jail
  removes.
- Kernel and driver bugs reachable from the allowed interfaces: the DRM ioctl
  set from the GPU process, the audio device, Mojo over Unix sockets, and the
  Capsicum implementation itself.
- Side channels and speculative execution are out of scope; Chromium's site
  isolation remains the mitigation.
- A renderer can still exhaust CPU and memory up to its limits.
- Anything in the "configured, untested" column of the release status table.
