# Beryllium: Security Model and Capsicum Sandbox Design

**Status:** Draft plan, no code written
**Date:** 18 October 2026; amended 1 November 2026 from the red-team review ([12-WORK-PLAN-AND-RED-TEAM.md](12-WORK-PLAN-AND-RED-TEAM.md), findings RT-01 to RT-15)
**Implements:** spec sections 5 to 9 (process architecture, Capsicum renderer sandbox, jails, resource controls, MAC)
**Related:** [03-ARCHITECTURE.md](03-ARCHITECTURE.md) section 4 for the process map and brokered resources; [08-TESTING-AND-VERIFICATION.md](08-TESTING-AND-VERIFICATION.md) for the proof obligations

---

## 1. Layers, in the order they are built and in the order they matter

| Layer | Protects against | Status at snapshot | Phase |
|---|---|---|---|
| 1. Renderer Capsicum policy | a compromised renderer reaching files, network, devices, other processes | absent (RLIMIT_DATA only) | 2 |
| 2. Launcher descriptor and environment hygiene, IPC validation | authority or secrets leaking into any child (RT-05); confused-deputy via Mojo | partial (Chromium's own IPC checks; no descriptor closing beyond CLOEXEC; full environment inherited) | 2 |
| 3. Per-process policies for utilities, audio, network, GPU, CDM | same as 1 for the other high-risk processes | absent | 3 |
| 4. Process-control hardening (`procctl`, including trace-disable on the browser process, RT-03) | tracing, privilege gain, signal abuse within the user's session | absent | 2 |
| 5. Resource limits (`rlimit`, optional `rctl`) | denial of service | RLIMIT_DATA only | 2 (rlimit), 4 (rctl) |
| 6. Optional whole-browser jail | filesystem and device exposure of the whole browser; blast radius of a browser-process compromise | none | 4 |
| 7. MAC module for capability-mode processes (study, RT-02) | kernel surface, machine identifiers and process visibility that Capsicum leaves reachable | none | 5 |

Layer 1 is the milestone; nothing else is allowed to stand in for it.

## 2. Capsicum facts the design relies on

To be confirmed by the standalone oracle on each supported branch (the test
suite exists because the design depends on these assumptions). Items marked
"main" were read from FreeBSD `main` source on 1 November 2026 and still need
the oracle run on 14.x, 15.x and the 16-CURRENT development host:

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
  which is where the 2023 attempt died. `ptrace` is marked CAPENABLED; on
  main, `ptrace_check_allowed()` (`sys/kern/sys_process.c`) limits a
  capability-mode caller to self-directed requests and process descriptors
  (`pdptrace`), and only while `security.bsd.allow_ptrace_in_cap_mode=1` (the
  default). Older branches are unmeasured, so the oracle tests it per branch
  and the browser process disables tracing of itself regardless (RT-03).
  `dlopen` by path fails because it opens by path.
- Also confirmed on main: `sendto` with a destination address fails with
  `ECAPMODE`; `kenv`, `posix_openpt`, `thr_kill2` and `ktrace` are not
  CAPENABLED; `setpriority`/`getpriority` are limited to self; `fork` checks
  the user's process count against the *caller's own* `RLIMIT_NPROC`
  (`sys/kern/kern_fork.c`), so `RLIMIT_NPROC=1` in a renderer denies `fork` in
  that process only (RT-15).
- What capability mode leaves reachable (RT-01, RT-02): sysctl nodes flagged
  `CTLFLAG_CAPRD` include machine identifiers (`kern.hostuuid`,
  `kern.hostid`, `kern.hostname`, `kern.boot_id`) as well as `kern.osrelease`
  and `kern.build_id`; `socket()` succeeds for any domain (`AF_INET`,
  `AF_INET6`, `PF_ROUTE`, `AF_NETLINK`), reaching protocol code even though
  `connect`/`bind` fail; `kevent(EVFILT_PROC)` checks only `p_cansee()`
  (`sys/kern/kern_event.c`), so a confined process can probe for any visible
  pid and watch other processes fork, exec and exit. Because a compromised
  renderer can always send data out through ordinary web requests, anything
  readable here is treated as disclosed.
- The kernel exposes capability mode per process as `KI_CRF_CAPABILITY_MODE`
  in `kinfo_proc.ki_cr_flags` (`sys/sys/user.h`), readable by the browser
  through `sysctl kern.proc.pid.<pid>`; this is what the status page and the
  navigation gate use (RT-04).
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
   env = allowlist (locale, TZ; display variables only for types that need
         them); LD_* dropped in production                  <- RT-05
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
      setrlimit(RLIMIT_DATA, policy value); RLIMIT_NPROC = 1; RLIMIT_CORE = 0   <- RT-15
      cap_enter(); CHECK(cap_getmode() == 1)
      record status bitmask; write structured log line
      production: any failure above -> LOG + _exit(kSandboxFailed)
      devel: failure -> LOG, continue, status says "NOT SANDBOXED"
   RendererMainPlatformDelegate::EnableSandbox returns status
browser: read kinfo_proc(pid); KI_CRF_CAPABILITY_MODE set?          <- RT-04
      no -> production: no navigation commit, terminate the renderer
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
| (no Casper channel) | | | renderers get no Casper channel; sysctl values are cached before entry. Casper services run outside capability mode and parse requests from the client, so a channel is an unconfined parser within an attacker's reach (RT-14) |
| `kqueue` descriptors | renderer itself | created in capability mode, allowed | not inherited |

Explicitly absent: any directory descriptor; any socket other than the Mojo
channel; any profile, cache, cookie, history, local storage or download
descriptor; any device node; `/dev/urandom` (arc4random); the X11 or Wayland
socket; D-Bus; a `/proc`-like descriptor (FreeBSD has none in use); any
Casper channel. Not a descriptor but treated the same way: the environment
carries no secrets or socket paths (`SSH_AUTH_SOCK`, `DBUS_SESSION_BUS_ADDRESS`,
tokens), because anything readable in the renderer is assumed disclosed
(RT-05).

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
- Removing `--no-sandbox` is not enough (RT-12). Production builds also
  remove, or ignore with a log line, switches that change the security model
  of a running browser: `--renderer-cmd-prefix`, `--utility-cmd-prefix`,
  `--gpu-launcher`, `--js-flags` (V8 flags can switch off mitigations),
  `--disable-site-isolation-trials`, `--disable-web-security`, and any
  later addition to that list. The production switch table is diffed against
  a committed list in the sandbox suite.
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
- Environment (RT-05): the launcher builds each child's environment from an
  allowlist per process type instead of passing the browser's. `LD_PRELOAD`,
  `LD_LIBRARY_PATH` and other `LD_*` variables are dropped for children in
  production, since they change what runs before the sandbox.
- Browser self-protection (RT-03): production builds call
  `procctl(PROC_TRACE_CTL, PROC_TRACE_CTL_DISABLE)` in the browser process
  itself, so neither a compromised child on a kernel that allows
  cross-process `ptrace` from capability mode nor unrelated same-user
  software can attach to the unconfined browser. `beryllium-devel` leaves it
  off for debugging.
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
| Audio | pre-open `/dev/dsp*` (OSS via ALSA shim) or pre-connect the sndio/PulseAudio socket; a reconnect goes through the browser, which connects and passes the new descriptor over Mojo. The shkhln prototype's socket-directory capability is not adopted, because `$XDG_RUNTIME_DIR` also holds the Wayland, D-Bus and `gpg-agent` sockets (RT-06) | the audio descriptor with `CAP_READ CAP_WRITE CAP_IOCTL` and an OSS ioctl allowlist, or the connected socket | device hot-plug after lockdown needs a restart of the audio service, which Chromium supports; ALSA was left unsandboxed in the prototype |
| Network | NSS init, read `/etc/resolv.conf` and `/etc/hosts` (or `cap_dns`), open the profile's `Network` directory as a directory capability | sockets created on demand require either no capability mode or `cap_net`; directory capability with `CAP_LOOKUP CAP_READ CAP_WRITE CAP_CREATE CAP_FSTAT CAP_UNLINKAT` and `O_RESOLVE_BENEATH` on every open | whether `cap_net` throughput and feature coverage (QUIC/UDP, IPv6, SOCKS) are acceptable; otherwise the network service stays out of capability mode with rights-limited descriptors and restricted filesystem reach, and the matrix says so. If `cap_net` is used, its request handling (`libnv`) gets a fuzz target in CI, and the non-thread-safe channel is serialised (RT-14) |
| GPU | existing BSD hook plus: open `/dev/dri/renderD*` and `card*` (and for NVIDIA's proprietary driver `/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-modeset`, with `/dev/dri` provided by `nvidia-drm`), `/dev/pci` with an ioctl allowlist (libpci), a per-session shader cache directory the browser creates and deletes (RT-08), the display connection made before entry (Wayland socket, or the X11 socket after reading `~/.Xauthority`), never a `/tmp`, `/tmp/.X11-unix` or `$XDG_RUNTIME_DIR` directory capability (RT-06), library directories with `CAP_MMAP_RX`, load every ICD and driver, warm Vulkan instance creation (the shkhln prototype's GPU policy is the starting inventory) | DRM and NVIDIA descriptors with `cap_ioctls_limit` on the ioctl set the driver actually uses (measured), the per-session cache directory, dma-buf descriptors over Mojo, the connected display socket | NVIDIA proprietary driver first (owner's hardware: RTX 5090, driver 595.99.02, Wayland); VA-API paths; the Vulkan loader re-reading ICD JSON by path after startup; Wayland was a TODO in the prototype |
| CDM | load the CDM library and open its storage directory before entry | library and storage capabilities | foreign-cdm's Linux-compatibility shim may need paths; if so, unsandboxed opt-in |

The rule from the roadmap applies: a process class is either in the matrix
as kernel-enforced with tests, or in the known-limitations page with a risk
statement and an owner.

GPU notes from the red-team review and the owner's hardware:

- **NVIDIA proprietary driver.** The first GPU target is the NVIDIA
  proprietary driver on Wayland through `nvidia-drm`. Its device nodes take a
  large, undocumented ioctl interface, so an ioctl allowlist is hard to derive
  and the residual kernel attack surface is large and closed-source. Phase 3
  measures the ioctls the GPU process actually issues (ktrace on the GPU
  pid across the workload set), applies `cap_ioctls_limit` if the set is
  stable, and otherwise documents the gap. The hardened software-rendering
  option below is the fallback.
- **X11 (RT-07).** Under X11 any client can capture other windows and inject
  input with XTEST, and injecting input into a terminal is a sandbox escape.
  A GPU process holding an X connection therefore has desktop-level
  authority whatever this policy says. Wayland is recommended. Phase 3
  measures whether the GPU process can present through the browser on X11
  without its own X connection; if not, "GPU process on X11: effectively
  unsandboxed" is a published limitation. The owner's setup is Wayland, so
  this is lower priority for development but still part of the release table.
- **Hardened option.** WebGPU disabled and software rendering only: the GPU
  process then needs no device node and can be confined like a utility.
  Measure the performance cost before offering it.
- **Caches (RT-08).** A cache written by one confined process and read by the
  next one, without the browser in between, turns a one-time compromise into
  a persistent one. `MESA_SHADER_CACHE_DIR` points at a per-session directory
  the browser creates and deletes (or the Mesa cache is disabled in hardened
  mode); Chromium's own GPU program cache stays browser-mediated.

## 6. Process-control hardening (Phase 2)

Applied in every confined child at the lockdown point (and, for trace
disable, in the production browser process too, RT-03):

- `procctl(P_PID, getpid(), PROC_TRACE_CTL, PROC_TRACE_CTL_DISABLE)`: no
  `ptrace` attach to the process, and no core dump of its memory to disk in
  production (a compromised renderer's memory holds page content). Called
  before `cap_enter` because `procctl` is not available inside capability
  mode.
- `procctl(PROC_NO_NEW_PRIVS_CTL, PROC_NO_NEW_PRIVS_ENABLE)`: belt-and-braces
  against setuid execution should `exec` ever become possible.
- `setrlimit`: `RLIMIT_DATA` (per-type value, following OpenBSD's scaled
  table rather than the single `kDataSizeLimit` the FreeBSD stub uses),
  `RLIMIT_NOFILE` to a measured ceiling, `RLIMIT_NPROC=1` (fork checks the
  user's process count against the caller's own limit, so this denies `fork`
  in the renderer without affecting the rest of the session; corrected from
  the 18 October draft, RT-15), `RLIMIT_CORE=0` (renderer memory holds page
  content and cookies).
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
- Host identifiers (RT-01): `host.hostuuid` and `host.hostname` are per-jail
  values (`CTLFLAG_PRISON`), so the profile sets random ones. This is the
  only way to hide the real machine UUID and hostname from a compromised
  confined process without a kernel module, which gives the jail a privacy
  purpose in addition to its perimeter role. A jail also hides processes
  outside it from `kevent(EVFILT_PROC)` probes (RT-02).
- Dedicated UID inside the jail; downloads land on a mapped directory the
  user chooses; `xdg-open` from inside the jail cannot reach the host session,
  so external-link handling is either disabled or routed through a documented
  helper outside the jail.
- The example ships as `freebsd/jail/README.md`, `jail.conf.example`,
  `devfs.rules.example`; nothing in the package touches `/etc`.

## 9. MAC study (Phase 5), reframed by RT-02

Spec section 9 adopted, with the first candidate changed. `mac_mls` and
`mac_biba` model labels on subjects and objects across the system; the likely
answer for them was always "only for the browser process itself". The
red-team review found a more specific gap: Capsicum is not a system call
filter, and capability-mode processes can still create sockets of any
domain, read `CTLFLAG_CAPRD` identifiers and observe other processes.

The first candidate is therefore a small policy module, provisionally
`mac_beryllium.ko`, that applies only to credentials in capability mode and
uses existing MAC hooks:

| Hook | Policy for capability-mode credentials |
|---|---|
| `mpo_socket_check_create` | allow `AF_UNIX` only |
| `mpo_system_check_sysctl` | allowlist of nodes (the oracle's reviewed list minus identifiers) |
| `mpo_cred_check_visible` | other processes invisible (covers `EVFILT_PROC` probes) |

It is optional and loaded by an administrator, has no effect on processes
outside capability mode, never ships enabled by the package, and needs a
kernel-side review before anyone depends on it. The study's deliverable stays
a decision memo (threat addressed, maintenance cost across kernel versions,
rollback), followed by a prototype on a disposable system if the memo says
yes. `mac_mls` for the profile and `~/.ssh` remains a secondary question in
the same memo.

## 10. Status reporting details

Upstream's `chrome://sandbox` Linux block (`sandbox_internals_ui.cc` and the
`sandbox_internals` WebUI resources) is compiled only under `IS_LINUX` or
`IS_CHROMEOS`, so a BSD build shows a page with no status rows. Beryllium
patches the WebUI to render a FreeBSD block from a new status bitmask
(capability mode entered, rights limited, ioctl and fcntl limits applied,
trace disabled, `RLIMIT_DATA` applied, fail-closed build, Casper channels
present, kernel advisory preflight result). The capability-mode row comes
from the kernel: the browser reads `KI_CRF_CAPABILITY_MODE` from each child's
`kinfo_proc`, because a child's own report can be made to lie by code that
runs before its check (RT-04); users can confirm the same flag with
`procstat`. The other rows come from the browser's record of each child's
startup log line, never from build flags. Also fixed: `Sandbox::IsProcessSandboxed()` falls through to
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
  set from the GPU process (and the closed-source NVIDIA driver's interface),
  the audio device, Mojo over Unix sockets, socket creation of any domain and
  other CAPENABLED system calls (RT-02), and the Capsicum implementation
  itself.
- Without the jail profile or the MAC module, a compromised renderer can read
  the machine UUID and hostname (RT-01).
- On X11, a compromised GPU process (and the browser process) has
  desktop-level authority (RT-07).
- Until the allocator shim, BackupRefPtr and CFI are enabled on FreeBSD, the
  browser process has weaker use-after-free and control-flow hardening than
  Helium on Linux (RT-09).
- Side channels and speculative execution are out of scope; Chromium's site
  isolation remains the mitigation.
- A renderer can still exhaust CPU and memory up to its limits.
- Anything in the "configured, untested" column of the release status table.
