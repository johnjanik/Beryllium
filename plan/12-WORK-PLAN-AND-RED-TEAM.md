# Beryllium: Work Plan and Red-Team Review

**Status:** Review of plan documents 00 to 11 and the spec, with facts re-checked against live sources; decisions and Sprint 1 status in sections 8 and 9
**Date:** 1 November 2026
**Reads with:** [09-ROADMAP.md](09-ROADMAP.md) (phases), [06-SECURITY-MODEL.md](06-SECURITY-MODEL.md) (sandbox design), [08-TESTING-AND-VERIFICATION.md](08-TESTING-AND-VERIFICATION.md) (proof obligations)

---

## 1. Summary

The plan is sound in its structure: pinned upstreams, a mechanically imported
BSD patch set, Capsicum renderer confinement as the central milestone,
fail-closed production builds, and tests that assert real kernel behaviour.
This document does three things:

1. Records what has changed in the two weeks since the 18 October snapshot.
2. Turns the roadmap into a concrete work plan, split between what can be done
   in a cloud session (no FreeBSD kernel available) and what must run on a
   FreeBSD machine.
3. Attacks the design. Each finding comes with evidence, a recommended change,
   and the test that would catch a regression.

The five findings that change the plan the most:

| # | Finding | Why it matters |
|---|---|---|
| RT-01 | `kern.hostuuid`, `kern.hostid`, `kern.hostname` and `kern.boot_id` stay readable in capability mode (`CTLFLAG_CAPRD`) | A compromised renderer gets a permanent machine identifier and often the user's name, and can send it out through ordinary web requests. The descriptor allowlist cannot stop this. |
| RT-02 | Capsicum does not filter socket domains, `kqueue` process filters or most of the kernel surface reachable from capability mode | Gives a kernel attack surface and process-observation side channel that the plan does not inventory. A small optional MAC module can close it, which reframes Phase 5. |
| RT-07 | On X11, the GPU process holds an X connection, so a GPU-process compromise allows keystroke capture and input injection into any terminal | The GPU process is one of the most common targets for escaping the renderer in real Chrome exploit chains. On X11 it is effectively unsandboxed whatever its Capsicum policy says. |
| RT-09 | The FreeBSD GN fragment disables the allocator shim, PartitionAlloc-as-malloc and BackupRefPtr (MiraclePtr) | Removes Chromium's main use-after-free mitigation from the browser process, which is the code a sandbox escape targets. Helium on Linux has it. |
| RT-11 | Upstream already moved: Helium 0.20.3 is on Chromium 156, two weeks after the plan pinned 155 | Lag behind upstream fixes is the largest real-world risk for any downstream Chromium. Without a fast build pipeline the sandbox work protects a stale engine. |

## 2. Facts re-verified on 1 November 2026

| Item | Plan snapshot (18 Oct) | Now | Source |
|---|---|---|---|
| Helium latest tag | 0.19.4, Chromium 155.0.8059.84 | **0.20.3**, Chromium **156.0.8078.79** (tagged 30 Oct); tags 0.20.1, 0.20.2 in between | `git ls-remote` on `imputnet/helium`; `chromium_version.txt` at the tag |
| Helium `flags.gn` | 17 arguments | unchanged between 0.19.4 and 0.20.3 | `git diff 832faa78 0.20.3 -- flags.gn` |
| `helium` submodule pin | `832faa78` (0.19.4) | still `832faa78`; three releases behind | this repository |
| FreeBSD `www/chromium` | 154.0.8037.57_2 | **156.0.8078.47_1** | ports `Makefile` on `main` |
| BSD patch import | "OpenBSD 155 plus FreeBSD 154 deltas" | FreeBSD and Helium are now on the same Chromium major (156); the first import can be a straight copy of the FreeBSD set plus point-release fixes | as above |
| BSD user-agent patches | not examined | UA platform `X11; Linux x86_64`, UA client hint platform `Linux`, reduced `navigator.platform` `Linux x86_64` | ports `files/patch-components_embedder__support_user__agent__utils.cc`, `files/patch-third__party_blink_renderer_core_execution__context_navigator__base.cc` |
| `ptrace` in capability mode | "CAPENABLED, restriction unconfirmed" | on FreeBSD `main`: allowed only for self-directed requests and process descriptors (`pdptrace`), and only while `security.bsd.allow_ptrace_in_cap_mode=1` (default); **14.x and 15.x still to be measured** | `sys/kern/sys_process.c`, `ptrace_check_allowed()` |
| `procctl` in capability mode | not permitted | confirmed: `STD`, not `CAPENABLED` | `sys/kern/syscalls.master` (544) |
| `sendto` with a destination address | not stated | `ECAPMODE` | `sys/kern/uipc_syscalls.c`, `kern_sendit()` |
| `kenv`, `posix_openpt`, `thr_kill2`, `ktrace` | not stated | not `CAPENABLED` | `syscalls.master` |
| `setpriority`/`getpriority` | not stated | restricted to self in capability mode | `sys/kern/kern_resource.c` |
| `RLIMIT_NPROC` | "not per-process on FreeBSD, left to resource profiles" | **correction:** `fork` checks the per-user count against the *calling process's* `RLIMIT_NPROC`, so setting it to 1 in a renderer denies `fork` in that process only | `sys/kern/kern_fork.c`, `chgproccnt(..., lim_cur(td, RLIMIT_NPROC))` |
| Read-only shared memory by rights | design assumption | confirmed: `mmap` derives a maximum protection from `CAP_MMAP_R/W/X`, so a descriptor without `CAP_MMAP_W` cannot be mapped or later `mprotect`ed writable | `sys/vm/vm_mmap.c` (`cap_maxprot`) |
| Kernel-visible capability-mode flag | "`procstat -s` field to be confirmed" | `KI_CRF_CAPABILITY_MODE` in `kinfo_proc.ki_cr_flags`, readable by the browser through `sysctl kern.proc.pid.<pid>` | `sys/sys/user.h` |

All kernel facts above are from FreeBSD `main` as of today. The Capsicum
oracle must confirm each one on every supported branch, because older branches
may differ (the `ptrace` restriction in particular).

## 3. Work plan

### 3.1 Who does what

This cloud session runs on Linux and has no FreeBSD kernel, no FreeBSD
toolchain, and not enough disk for an 8.6 GB Chromium tree. The split is:

| Work | Where | Notes |
|---|---|---|
| Tooling in Python and shell (import, GN args, patch matrix, manifests) | cloud session, with unit tests that run on Linux CI | most of Phase 0 and the port's helper scripts |
| C test programs (Capsicum oracle, red-team probes) | written in the cloud session, **compiled and run on FreeBSD** | first runs on your machine; output JSON committed back |
| Port `Makefile`, `pkg-plist`, wrapper, patches | written in the cloud session | built on FreeBSD |
| Full Chromium builds, sandbox and functional suites, privacy captures | FreeBSD machine | needs the hardware in section 8, item 1 |
| Upstream contact (imputnet, `chromium@FreeBSD.org`, bug 269234) | you, in your own words | charter D8: Helium bans AI-written contributions |

The feedback loop: I push code to `claude/admiring-wright-ddl9kd`; you pull,
run it on FreeBSD, and send back the output (or commit it under
`freebsd/results/`). Every C program prints machine-readable JSON so results
can be diffed across kernels.

### 3.2 Sprints

Each sprint ends with something you can run. Effort follows 09-ROADMAP.md;
the order changes in three ways: red-team probes join the Phase 0 oracle,
the allocator-hardening work becomes a tracked item, and the build pipeline
is treated as security infrastructure from the start.

**Sprint 1: facts and probes (Phase 0, no Chromium build yet)**

1. Move the `helium` submodule to `0.20.3`; update README and plan pins.
2. `freebsd/tools/baseline-collect.sh`: the spec section 15 commands plus a
   `procstat -f -C`, `procstat -e`, `procstat -s` and `sockstat` dump of a
   running stock `www/chromium`. You run it; output becomes
   `freebsd/BASELINE.md`.
3. `freebsd/tests/capsicum-standalone/`: the oracle from 08 section 2.1, plus
   the red-team probes in section 6.2 below (sysctl sweep, socket domains,
   `kqueue` process filter, `ptrace`, `RLIMIT_NPROC`, `mmap` maximum
   protection, `/dev/fd` listing). One `make`, one JSON file per kernel.
4. `freebsd/tools/gnargs-from-flags` and the privacy-key guard test (07
   section 2). Runs on Linux in GitHub Actions.
5. `freebsd/tools/patch-matrix` against the FreeBSD 156 `files/` set and the
   Helium 0.20.3 series. Produces `freebsd/PATCH-MATRIX.md`. Runs on Linux.

**Sprint 2: the port skeleton (Phase 1 start)**

1. `freebsd/ports/www/beryllium` and `www/beryllium-devel` (slave port), with
   the seven-stage layering from 05, generated GN args, `distinfo` for the
   Helium base tarball and the three `deps.ini` assets.
2. `freebsd/tools/import-bsd-patches` with provenance and the
   security-directory review gate from RT-10.
3. First full build on the FreeBSD builder. Classify each build break by
   layer (BSD import, Helium conflict, Beryllium platform).

**Sprint 3: Phase 1 acceptance**

1. Branding layer, crash-upload and update-check UI adjustments, profile
   directory name.
2. Functional smoke list on X11 and Wayland.
3. `freebsd/PRIVACY-INVARIANTS.md`, the first capture run, and the new OS
   fingerprint consistency test (RT-13).
4. Hardening audit of the binary (PIE, RELRO, stack protector, CFI status) and
   the allocator experiment from RT-09 recorded in the build manifest.

**Sprint 4 onward: Phase 2**

1. Evaluate the shkhln `chromium-sandbox` branch (roadmap Phase 2 item 0),
   scored against the red-team probe list, not only against "pages load".
2. Build the devel-only attacker payload hook (section 6.1) before writing
   policy, so every policy change is measured against the same attacks.
3. Inventory, allowlist, lockdown, fail-closed, kernel-attested status (RT-04),
   environment scrubbing (RT-05), browser trace-disable (RT-03).

### 3.3 Amendments to the existing plan documents

To be applied once you agree with them:

| Document | Change |
|---|---|
| 01 charter, 02 baseline, README | pin moves to 0.20.3 / Chromium 156; FreeBSD port now on 156 |
| 03 architecture 4.3 | add a fourth brokered-resource rule: no directory capability with `CAP_CONNECTAT` on a shared directory (RT-06) |
| 03 architecture 5, 06 section 10 | status comes from the kernel (`KI_CRF_CAPABILITY_MODE`), not from the child's own log line (RT-04) |
| 04 build plan 4 | allocator shim, PartitionAlloc-as-malloc, BackupRefPtr and CFI become tracked hardening items with a target phase (RT-09) |
| 06 security model 2 | replace the "unconfirmed" `ptrace` note with the measured facts; add sysctl, socket-domain and `kqueue` surface |
| 06 security model 3.1 | add environment allowlist, `RLIMIT_NPROC=1`, `RLIMIT_CORE=0`, and browser-process trace-disable |
| 06 security model 9, roadmap Phase 5 | MAC study reframed: first candidate is attack-surface reduction for capability-mode processes, not `mac_mls`/`mac_biba` (RT-02) |
| 07 privacy plan | new invariant: Beryllium presents as Linux x86_64 consistently (RT-13); hostname and host UUID are privacy-relevant (RT-01) |
| 08 testing | add the probe catalogue in 6.2 and the attacker payload hook in 6.1 |
| 11 maintenance | a published turnaround target for security releases and a build-age warning in the browser (RT-11) |

## 4. Red team: attacker model

| Attacker | Starting position | Goal |
|---|---|---|
| A1 Web attacker | native code execution in a renderer (V8, Blink, Skia, media bug) | read user files or other sites' data, persist, escape to the browser, identify the user |
| A2 Second-stage attacker | code execution in the GPU, network, audio or a utility process, reached from A1 or directly (network service parses hostile input from the network) | same as A1, with that process's authority |
| A3 Tracker | no code execution; runs script on pages | identify the user across sites and sessions; Beryllium users are a tiny population, so every FreeBSD-specific signal is close to unique |
| A4 Supply chain | controls or compromises an input: Chromium tarball host, BSD patch flow, Helium services, a GitHub tag | ship malicious code or weaken defaults without review |
| A5 Upstream lag | publishes exploits for bugs fixed upstream but not yet shipped by Beryllium | exploit Beryllium users during the lag window |

One premise drives most findings: **a compromised renderer always has a way
to send data out.** It can make ordinary web requests through the network
service to an attacker's server, and the browser will carry them. Blocking
`connect()` in the renderer stops it from reaching local services; it does
not stop exfiltration. So the renderer policy protects confidentiality only to
the extent that it limits what the renderer can *read*. Anything readable
from capability mode (sysctls, environment, inherited memory, passed
descriptors) should be treated as already sent to the attacker.

## 5. Red-team findings

Severity is for the shipped design if the finding were left unaddressed.

| ID | Sev | Finding | Change | Test |
|---|---|---|---|---|
| RT-01 | High | Machine identifiers readable in capability mode | jail profile sets per-jail `host.hostuuid` and `host.hostname`; optional MAC sysctl filter; reviewed allowlist of capability-mode-readable sysctls | oracle sysctl sweep; attacker hook reads `kern.hostuuid` |
| RT-02 | High | Kernel surface and side channels not covered by Capsicum | optional `mac_beryllium` module; oracle inventory; kernel fuzzing in capability mode | oracle socket-domain and `kqueue` probes |
| RT-03 | Critical if open | Renderer could `ptrace` the unconfined browser on kernels that allow it | `PROC_TRACE_CTL_DISABLE` on the browser too; per-branch oracle; preflight | oracle; attacker hook attaches to the browser pid |
| RT-04 | Medium | Sandbox status is self-reported by the child | browser checks `KI_CRF_CAPABILITY_MODE` for each child pid before committing a navigation | kill the lockdown in a devel build, assert no navigation commits |
| RT-05 | High | Children inherit the browser's environment | environment allowlist at launch | canary variable absent in `procstat -e` of every child |
| RT-06 | High | Directory capabilities with `CAP_CONNECTAT` reach unrelated sockets (`/tmp`, `$XDG_RUNTIME_DIR`) | pre-connect before `cap_enter`; broker reconnection; no shared directories | attacker hook in GPU/audio tries `ssh-agent`, D-Bus, singleton sockets |
| RT-07 | Critical on X11 | GPU process with an X connection can read keys, screenshots, inject input | Wayland recommended; measure whether the GPU process needs X; publish X11 limitation | attacker hook in GPU process sends XTEST events in a test session |
| RT-08 | Medium | Writable caches as persistence (Mesa shader cache) | per-session cache dir owned by the browser, or disabled in hardened mode | poison cache in one run, check next run |
| RT-09 | High | Allocator hardening disabled in the FreeBSD fragment | port the allocator shim; enable PartitionAlloc-as-malloc, BackupRefPtr; then CFI | GN args check plus a runtime check in `chrome://version` |
| RT-10 | High | 1,650 imported BSD patches are never reviewed; base tarball pinned on first fetch, unsigned | review gate on security-relevant paths per import; independent tarball cross-check | CI fails if a gated path changed without a review record |
| RT-11 | Critical | Lag behind upstream security fixes | turnaround target, dedicated builder, build-age warning | lag metric in every release note |
| RT-12 | Medium | Escape hatches other than `--no-sandbox` | production switch allowlist (`--renderer-cmd-prefix`, `--utility-cmd-prefix`, `--gpu-launcher`, `--js-flags`, site-isolation switches) | production binary switch-table diff |
| RT-13 | Medium | OS fingerprint leaks and inconsistencies | "presents as Linux x86_64" invariant with tests; document TCP/IP stack signature | fingerprint test page in window and worker contexts |
| RT-14 | Medium | Casper services are unconfined parsers reachable from confined processes | no Casper channel in renderers; fuzz `libnv` and `cap_net` request handling | fuzz target in CI |
| RT-15 | Low | Fork and core-dump abuse from a renderer | `RLIMIT_NPROC=1`, `RLIMIT_CORE=0` at lockdown | oracle fork probe; attacker hook forks |
| RT-17 | Medium | Chromium's own pages claim confinement FreeBSD does not enforce: `chrome://gpu` shows "Sandboxed: true" for a GPU process the kernel shows is not in capability mode | every "sandboxed" field Beryllium shows is driven by the kernel-attested status (RT-04); no upstream status string is shown on BSD without that check | functional test compares `chrome://gpu` and `chrome://sandbox` with `procstat` for each process |
| RT-16 | Medium (opportunity) | W^X is not enforced by default (`kern.elf64.allow_wx=1`); a renderer can create write-and-execute memory | launcher sets `PROC_WX_MAPPINGS_DISALLOW_EXEC` between fork and exec so W^X is enforced in each child, if V8 works under it | oracle `hard.wxorx_after_exec`; V8 and WebAssembly test pages under enforcement |

### RT-01: machine identifiers survive capability mode

**Evidence.** FreeBSD `sys/kern/kern_mib.c` declares `kern.hostname`,
`kern.domainname`, `kern.hostuuid`, `kern.hostid`, `kern.boot_id`,
`kern.osrelease` and `kern.build_id` with `CTLFLAG_CAPRD`. The sysctl
dispatcher (`sys/kern/kern_sysctl.c`) only refuses reads in capability mode
for nodes without that flag. `kern.hostuuid` is usually the SMBIOS system
UUID: stable across reinstalls of the browser, profiles and private windows.
Hostnames often contain the user's name.

**Impact.** After a renderer compromise, the attacker sends one request and
has a permanent identifier for the machine. This defeats Helium's profile and
private-browsing separation for that user against that attacker. The 06
allowlist is about descriptors and does not cover it.

**Change.**
- The oracle enumerates every sysctl node (the enumeration nodes
  `sysctl.next` and `sysctl.name` are themselves `CAPRD`), records which are
  readable after `cap_enter`, and the result becomes a reviewed list in
  `freebsd/sandbox/caprd-sysctls.json`. New readable nodes in a kernel update
  fail the diff.
- The jail profile (Phase 4) gains a privacy purpose: `host.hostuuid` and
  `host.hostname` are per-jail (`CTLFLAG_PRISON`), so a jail with randomised
  values hides the real ones from everything inside it. Document this as the
  only fix available without a kernel module.
- The MAC module in RT-02 can refuse these reads for capability-mode
  credentials.

### RT-02: what Capsicum leaves reachable

Capsicum restricts global namespaces. It is not a system call filter, and the
following remain reachable from a capability-mode process (all from FreeBSD
`main` source, to be measured by the oracle):

- `socket()` for any domain. `connect`, `bind` and `sendto` with an address
  fail, but socket creation still reaches protocol code (`AF_INET` UDP and
  TCP, `AF_INET6`, `PF_ROUTE`, `AF_NETLINK` on 14.x and later). Routing
  sockets broadcast address and route changes to listeners, which may leak
  local addresses. Netlink is new kernel code (2023).
- `kevent(EVFILT_PROC)` on any process the caller can see
  (`sys/kern/kern_event.c`, `filt_procattach()` checks only `p_cansee()`).
  With the default `security.bsd.see_other_uids=1`, a renderer can probe for
  any pid on the system and watch other processes fork, exec and exit.
- The full set of `CAPENABLED` system calls, each a kernel attack surface for
  privilege escalation that bypasses every user-space layer.

**Change.**
- Oracle probes for each item above, so the real behaviour per branch is
  recorded.
- Reframe the Phase 5 MAC study. `mac_mls` and `mac_biba` are a poor fit
  (06 section 9 already suspects this). A small policy module, provisionally
  `mac_beryllium.ko`, that applies only to credentials in capability mode
  would act as the system call filter Capsicum lacks, using existing MAC
  hooks: `mpo_socket_check_create` (allow `AF_UNIX` only),
  `mpo_system_check_sysctl` (allowlist), `mpo_cred_check_visible` (hide other
  processes). It is optional, loaded by an administrator, does nothing to
  processes outside capability mode, and needs a kernel review before anyone
  depends on it. It would be a FreeBSD feature with no equivalent in
  Helium on Linux.
- Kernel fuzzing: syzkaller supports FreeBSD. Running it with an executor
  that calls `cap_enter()` first measures exactly the surface a compromised
  renderer has. Results go to FreeBSD security, not to Beryllium.

### RT-03: `ptrace` from renderer to browser

The browser process is unconfined and runs as the same user. If a renderer in
capability mode can `ptrace(PT_ATTACH)` the browser, the sandbox is escaped in
one call. On FreeBSD `main`, `ptrace_check_allowed()` in
`sys/kern/sys_process.c` restricts capability-mode callers to self-directed
requests and process descriptors. Older branches are unknown.

**Change.** Run the oracle probe on 14.x and 15.x first; this is the highest
priority oracle result. Regardless of the answer, call
`procctl(PROC_TRACE_CTL, PROC_TRACE_CTL_DISABLE)` in the **browser** process
of production builds too, so no same-user process (a compromised child or
unrelated malware) can attach to it. The preflight warns if a kernel allows
cross-process `ptrace` from capability mode.

### RT-04: trust the kernel, not the child

06 section 10 builds `chrome://sandbox` from each child's startup log line. A
child reports its own state, and anything that runs in the child before the
check (an `LD_PRELOAD` library, a patched `libc` wrapper for `cap_getmode`)
can make it lie.

**Change.** The browser reads `kinfo_proc` for each child pid
(`sysctl kern.proc.pid.<pid>`) and checks `KI_CRF_CAPABILITY_MODE` in
`ki_cr_flags`. In production, a renderer that is not in capability mode by
the kernel's own account receives no navigation commit and is killed. The
status page shows the kernel's answer. This is a check users can repeat
themselves with `procstat`, which makes the claim verifiable from outside the
browser.

### RT-05: environment inheritance

Chromium passes the browser's environment to children. Desktop sessions put
secrets and capability paths there: `SSH_AUTH_SOCK`, `DBUS_SESSION_BUS_ADDRESS`,
`GNUPGHOME`, proxy URLs with credentials, cloud and Git tokens. Per section 4,
anything a renderer can read is gone. Also, `LD_PRELOAD` and `LD_LIBRARY_PATH`
in the environment change what runs before the sandbox.

**Change.** The launcher builds each child's environment from an allowlist
(locale, timezone, display variables only where the process type needs them).
`LD_*` variables are dropped for children in production builds. Test: start
the browser with a canary variable and assert it is absent from
`procstat -e` of every child.

### RT-06: directory capabilities that reach too far

03 and 06 propose giving the GPU and audio processes a directory capability
with `CAP_CONNECTAT` for the X11, Wayland, sndio or PulseAudio socket
directory, and the OpenBSD policy the plan cites unveils all of `/tmp` for the
GPU process. A directory capability reaches every socket beneath it:
`/tmp` holds `ssh-agent` sockets and the browser's own process-singleton
socket; `$XDG_RUNTIME_DIR` holds the Wayland, D-Bus, PulseAudio, PipeWire and
`gpg-agent` sockets. A compromised GPU process could ask `ssh-agent` to sign,
send D-Bus calls, or hand the running browser a new command line.

**Change.** Connect before `cap_enter` and keep only the connected socket.
When a reconnect is needed (audio device change, compositor restart), the
browser reconnects and passes the new descriptor over Mojo. A directory
capability is allowed only for a directory Beryllium created and in which it
controls every entry. Test: the attacker hook in each process tries the known
socket paths.

### RT-07: X11 and the GPU process

Under X11, any client can read keystrokes, capture other windows and inject
input with XTEST. Injecting input into a terminal is a sandbox escape. On
X11 the GPU process normally holds an X connection to present frames, and it
is reachable from the renderer through WebGL and WebGPU command buffers. A
GPU-process compromise on X11 therefore has desktop-level authority whatever
its Capsicum policy is. The browser process has the same exposure, as the
plan already states.

**Change.**
- Make Wayland the recommended configuration and say so in `pkg-message` and
  the status page.
- Phase 3 measures whether the GPU process can run without an X connection
  on X11 (presenting through the browser process with shared memory or
  dma-buf). If it cannot, the status table lists "GPU process on X11:
  effectively unsandboxed" as a known limitation.
- A hardened option that disables WebGPU and uses software rendering removes
  device access entirely and lets the GPU process be confined like a utility.
  Measure the cost before offering it.

### RT-08: caches as persistence

The GPU policy gives the GPU process a writable Mesa shader cache directory
that the next GPU process reads. A compromised GPU process can write entries
crafted to exploit the driver or compiler of the next run, which turns a
one-time compromise into a persistent one. The same reasoning applies to any
cache written by one confined process and read by another without the browser
in between.

**Change.** Point `MESA_SHADER_CACHE_DIR` at a per-session directory the
browser creates and deletes, or disable the Mesa cache in hardened mode.
Chromium's own GPU program cache already goes through the browser; keep it
that way. Test: write a marker into the cache in one session, check it is
gone or not loaded in the next.

### RT-09: allocator hardening

The expected FreeBSD fragment in 04 section 4 sets `use_allocator_shim=false`,
`use_partition_alloc_as_malloc=false` and
`enable_backup_ref_ptr_support=false`. BackupRefPtr (MiraclePtr) is
Chromium's main mitigation for use-after-free bugs in the browser process,
which is where the Mojo bugs used for sandbox escapes live. CFI status on the
FreeBSD toolchain is unknown. A security-focused fork shipping weaker
browser-process hardening than Helium on Linux undercuts its own claim.

**Change.** Track as Phase 2 items with a status row in the release table:
(1) record CFI and the allocator flags in the build manifest from the first
build; (2) port the allocator shim to FreeBSD (libc `malloc` interposition;
feasibility to be confirmed), then enable PartitionAlloc-as-malloc and
BackupRefPtr in `beryllium-devel`, measure, then promote; (3) attempt CFI.
None of this blocks the first build; all of it is visible in the status
table.

### RT-10: supply chain

- The BSD set is "never hand-edited" by design, which also means never read.
  It is about 1,650 patches from a maintainer's private tree. A malicious or
  simply wrong change to `sandbox/`, `base/process/`, `base/memory/`,
  `mojo/`, `ipc/`, `content/browser/child_process_*`,
  `content/browser/renderer_host/`, `services/network/` or
  `third_party/boringssl/` would land in Beryllium unseen.
- Helium's base tarball is unsigned. `distinfo` pins whatever was downloaded
  the first time. GitHub tags can be moved.

**Change.** `import-bsd-patches` emits a diff of every patch touching the
gated paths since the last import; CI refuses the import until a review record
(reviewer, date, notes) exists for each. Cross-check the base tarball against
an independent source once per Chromium version (Google's official tarball or
a `gclient` checkout, compared file by file for the overlapping tree). Pin
by commit hash everywhere a tag is used.

### RT-11: freshness

In two weeks Helium released three tags and moved a Chromium major. Chromium
security releases sometimes fix bugs already exploited in the wild. The
window between a public fix and a Beryllium package is when users are most
exposed, and a sandboxed browser running an old V8 can be less safe than an
unsandboxed current one.

**Change.**
- A published target: a package within 72 hours of a Helium tag that carries
  security fixes. The 11 document's lag metric becomes a release gate with a
  documented exception process.
- A dedicated builder (section 8, item 1). A Chromium build takes hours; a laptop
  that is also the test machine will not meet the target.
- Chromium's outdated-build detection keyed on build date, adapted to say
  "run `pkg upgrade`", so stale installs warn their users.
- The fast path in 05 section 7 step 3 (hand-forward-port when BSD ports lag)
  needs rehearsing before it is needed.

### RT-12: other escape hatches

Removing `--no-sandbox` is not enough. Switches such as
`--renderer-cmd-prefix`, `--utility-cmd-prefix`, `--gpu-launcher`,
`--js-flags` (V8 flags can turn off mitigations),
`--disable-site-isolation-trials` and `--disable-web-security` change the
security model of a running browser.

**Change.** Production builds use an explicit allowlist review of
security-relevant switches: removed, or ignored with a log line. Test: the
production binary's switch table is diffed against a committed list.

### RT-13: looking like Linux, consistently

The BSD patches already present the browser as Linux: UA platform
`X11; Linux x86_64`, client hint platform `Linux`, reduced
`navigator.platform` `Linux x86_64`. That is the right choice for privacy,
since FreeBSD users are a small population. Remaining leaks found in source:

- `NavigatorBase::platform()` falls back to `NavigatorID::platform()`, which
  calls `uname()` and returns `FreeBSD amd64`, whenever the
  `ReduceUserAgentMinorVersion` runtime feature is off.
- `BuildOSCpuInfoFromOSVersionAndCpuType()` in the BSD patch formats
  `Linux x86_64; <sysname> <cpu>`, which places `FreeBSD` in any full user
  agent string that is built from it.
- Installed fonts differ from common Linux distributions.
- The TCP/IP stack's SYN signature identifies FreeBSD to passive
  fingerprinting tools. A Linux user agent over a FreeBSD TCP signature is a
  known bot-detection signal, which can mean more CAPTCHAs.
- WebRTC: Helium sets `enable_mdns=false`. Whether host ICE candidates are
  still hidden behind mDNS names needs a test, or local addresses may leak.

**Change.** A privacy invariant: "Beryllium presents as Linux x86_64 in every
script-visible and header-visible surface." A fixed test page records UA,
all client hints, `navigator.platform` in window and worker contexts, ICE
candidates and a font probe, and the privacy suite diffs it against the
stored baseline. The `uname` fallback is patched to return the reduced
value. The TCP signature is documented with optional `pf` `scrub` settings
and not presented as solved.

### RT-14: Casper services

`cap_net` and `cap_sysctl` run as helper processes that are not in capability
mode and parse requests (`libnv` lists) from the confined client. A
compromised confined process can send them anything. They are therefore part
of the attack surface, and Casper channels are not thread-safe, which matters
in Chromium's multithreaded processes.

**Change.** No Casper channel in renderers (06 already prefers this; make it
a rule). For the network service, a fuzz target that sends hostile `libnv`
lists to `cap_net` limits and requests, run in CI.

### RT-15: fork and core dumps

Corrected fact from section 2: setting `RLIMIT_NPROC` to 1 in a renderer
makes `fork` fail in that process without affecting the rest of the session,
because the limit is checked against the caller's own `rlimit`. Set it at
lockdown together with `RLIMIT_CORE=0` (renderer memory holds page content
and cookies). `PROC_TRACE_CTL_DISABLE` also suppresses core dumps; the
explicit limit documents the intent.

### RT-16: enforce W^X in children (added after the first oracle run)

The first oracle run showed `kern.elf64.allow_wx=1` and an anonymous mapping
with write and execute permission at once succeeding inside capability
mode. W+X memory is what an exploit wants for shellcode. FreeBSD can switch
this off per process: `procctl(PROC_WXMAP_CTL, PROC_WX_MAPPINGS_DISALLOW_EXEC)`
makes the address space created by the next `execve` refuse W+X mappings.
The browser's launcher can set it in the child between `fork` and `exec`,
so every renderer and utility starts with W^X enforced, with no kernel
change and no system setting. Linux has no per-process equivalent without
an LSM policy.

V8 changes code pages between RW and RX rather than mapping them W+X on
most paths, but WebAssembly code space and some JIT tiers may still ask for
W+X. Phase 2 measures it: the oracle probe `hard.wxorx_after_exec` checks
the kernel side (W+X refused, RW-to-RX still allowed); test pages with
JavaScript and WebAssembly check V8. If V8 needs W+X, the V8 flags that
avoid it are evaluated before giving up.

## 6. Red-team test programme

### 6.1 The attacker payload hook

A devel-only switch that, after sandbox initialisation, runs a fixed list of
attacker actions in the renderer (and later in each confined process type)
and writes JSON results to a descriptor passed at launch. It extends 08
section 2.2 from "forbidden operations" to "everything an attacker with code
execution would try first". It is compiled only into `beryllium-devel`; a
build test proves it is absent from production binaries.

### 6.2 Probe catalogue

Each probe runs in the standalone oracle (kernel facts, no Chromium) and in
the attacker hook (Beryllium's actual policy). Expected results come from
the oracle table for that kernel.

| Area | Probes |
|---|---|
| Files | absolute and relative opens of canaries (`~/.ssh/id_canary`, profile cookie DB); `openat` escape with `..`, absolute paths and symlinks; `/dev/*` opens |
| Descriptors | walk 0 to `RLIMIT_NOFILE`: `fstat`, `cap_rights_get`, `cap_ioctls_get`, socket type; compare with allowlist |
| Network | `socket()` per domain (`AF_INET`, `AF_INET6`, `AF_UNIX`, `PF_ROUTE`, `AF_NETLINK`); `connect`, `bind`, `sendto` with address; `connectat` without a directory capability; read from a routing socket |
| Identity | sysctl sweep with the identifier list (`kern.hostuuid`, `kern.hostid`, `kern.hostname`, `kern.boot_id`, `hw.*` serial-like nodes); `kenv` read; `uname` |
| Processes | `ptrace` attach to the browser and to an unrelated same-user sleeper; `kill`, `sigqueue`, `thr_kill2`; `kevent(EVFILT_PROC)` on the browser and on pid 1; `setpriority` on others; `procctl`; `fork` with `RLIMIT_NPROC=1` |
| Memory | map a read-only shared region writable; `mprotect` upgrade; `PROT_EXEC` on a `CAP_MMAP_R` descriptor; anonymous `PROT_EXEC` still works |
| Shared memory | `shm_open(SHM_ANON)`, `memfd_create`, named `shm_open`, SysV `shmget` |
| Environment | read `environ`; look for canary variables and `LD_*` |
| Desktop | connect to X11, Wayland, D-Bus, `ssh-agent` and singleton socket paths |
| Escape hatches | production binary launched with each switch in RT-12 |
| Persistence | write into any reachable cache; check effect on next start |

### 6.3 Fuzzing

- Mojo interfaces that a renderer can reach and that have BSD-specific
  implementations in the browser or utilities (HID through `uhid`, USB,
  serial, gamepad, audio and video device enumeration, process metrics).
  These are code paths Google's fuzzing infrastructure never ran on BSD.
  MojoLPM fuzzers built on FreeBSD are the tool.
- `libnv` and Casper request handling (RT-14).
- syzkaller with a capability-mode executor (RT-02).

### 6.4 Privacy red team

- The capture suite from 07 section 6, plus a hostile services origin: a mock
  `services.helium.imput.net` that serves stale, malformed or substituted
  extension packages and filter lists. The browser must reject packages that
  fail CRX3 signature checks and must not downgrade extensions.
- The fingerprint page from RT-13, run on every release.

### 6.5 Process

1. A finding is written as a failing test first.
2. The fix lands with the test passing.
3. The test joins the release gate, so a later Chromium update cannot quietly
   reopen it.
4. Before each public release, someone who did not write the policy gets a
   week with the attacker hook and the probe list and tries to find what the
   list misses.

## 7. What would make people switch

These are worth building only after freshness (RT-11) and the Phase 2
renderer sandbox are solid. Each one uses a FreeBSD facility that Linux
browsers cannot use in the same way:

- **Verifiable sandbox status.** Every claim on the status page can be
  checked by the user with `procstat` (RT-04). No mainstream browser offers
  that.
- **A confined network service.** The network service parses hostile input
  straight from the network. Capability mode with pre-opened directories and
  `cap_net`, if measurements show it is workable, would confine a process
  that stock Chromium on Linux does not sandbox by default.
- **`mac_beryllium`.** The system call filter that Capsicum lacks, scoped to
  confined processes only (RT-02).
- **Disposable sessions.** A jail with a ZFS clone of a template profile,
  randomised host identifiers (RT-01) and its own network path, destroyed on
  exit. FreeBSD makes this cheap and fast.

## 8. Decisions recorded on 1 November 2026

| Item | Answer | Effect |
|---|---|---|
| Build and test host | amd64, 128 GB RAM, 24 cores, about 7 TB disk | meets the dedicated-builder requirement in RT-11; stable branches built in Poudriere jails and tested in bhyve guests on the same host |
| FreeBSD version | 16.0-CURRENT (installed after June 2026) | primary development host; release targets stay 14.x and 15.x; the `SA-26:28` fix is confirmed by the oracle's `proc.sigqueue_other` probe, not by version number |
| Display and GPU | Wayland; NVIDIA RTX 5090, proprietary driver 595.99.02 | RT-07 is lower priority on this host but stays a published limitation; the first GPU policy targets NVIDIA on Wayland, whose closed driver and large ioctl surface are a new risk (R23 in 10) |
| Q1 name | Beryllium only; no association with Helium | charter D2 and D8, README rewritten; GPL attribution kept |
| Q2 services | Helium endpoints not used; services off until Beryllium self-hosts | charter D3, 07 section 3; component updates going stale is a release blocker (R13); hosting is new open question Q10 |
| Section 3.3 amendments | agreed | applied to documents 01 to 11 |

New open questions: Q10 (who hosts Beryllium services, under which domain)
and Q11 (rename the user-visible `helium://` scheme to `beryllium://`).

## 9. Sprint 1 status

| Item | Status | Where |
|---|---|---|
| 1. Submodule to 0.20.3 | done | `helium` at `2f81b9ca`, Chromium 156.0.8078.79 |
| 2. Baseline collection | machine part recorded (`freebsd/results/baseline-16.0-CURRENT-20261101.md`); **per-process part still to run with Chromium open**, against the official `chromium` 156.0.8078.47_1 package (`FreeBSD:16:amd64/latest`; a host ports build failed in `www/node24`, see 09 Phase 0 item 3) | `freebsd/tools/baseline-collect.sh` |
| 3. Capsicum oracle and red-team probes | **run on 16.0-CURRENT** (section 10); version 2 fixes two probe bugs and adds `setpriority`, `dlopen` control and W^X-after-exec probes (89 probes) | `freebsd/tests/capsicum-standalone/`, `freebsd/results/` |
| 3a. Oracle on 14.x and 15.x | ran on 14.5 and 15.1; results copy-back fixed so the JSON is uploaded as artifacts | `.github/workflows/freebsd-checks.yml` |
| 4. GN args generator and privacy guard | done, 13 unit tests, passes against Helium 0.20.3 | `freebsd/tools/gnargs-from-flags`, `flags.freebsd.gn`, `freebsd/privacy/gn-privacy-keys.json` |
| 5. Patch matrix | done: 168 shared files, 37 overlapping, 19 adjacent; every overlapping or adjacent security-path row has a resolution and a test | `freebsd/tools/patch-matrix`, `freebsd/PATCH-MATRIX.md`, `freebsd/patch-matrix-notes.json` |

## 11. Sprint 2 status (1 November 2026)

| Item | Status | Where |
|---|---|---|
| `beryllium://` scheme (Q11) | patch applies after Helium's series; not compiled yet | `patches/branding/beryllium-webui-scheme.patch` |
| Name substitution | Helium's pass, then Helium's translations, then Beryllium's rename (Helium to Beryllium, `helium://` to `beryllium://`) | `freebsd/tools/beryllium-name-substitution` |
| Own profile, branding, FreeBSD paths | `~/.config/beryllium`, `/usr/local/{share,etc}/beryllium`, Beryllium BRANDING; applies on the real post-stage-3 files | `patches/platform/beryllium-paths-and-branding.patch` |
| BSD patch import | 1,696 patches from ports `6ad3e0c8`; 217 on security-review paths, review debt tracked | `freebsd/tools/import-bsd-patches`, `freebsd/ports/www/beryllium/BSD-PATCH-REVIEW.md` |
| Port skeleton | written, **not yet built**; Google `-lite` tarball (04 section 2.1); one `distinfo` line (Helium archive) recorded by `make makesum` on the build host | `freebsd/ports/www/beryllium`, `freebsd/ports/README.md` |
| Patch workbench | builds any file in its post-stage-4 state for writing new patches | `freebsd/tools/patch-workbench` |
| First Poudriere builds (2 November) | build 1: fetch, checksums and extract pass; patch stage lacked Python (fixed). Build 2: all 1,696 BSD patches apply to `.79`, pruning complete, Helium's `disable-ai.patch` fails on BSD-changed context. Build 3: all patches and substitutions apply; onboarding i18n generator rejected an XML declaration added by the rename (fixed). Build 4: `gn gen` passes (35,209 targets), compile reaches 89% (49,179 of 54,881) and stops in Helium's importer, which takes the Windows/macOS branch on BSD (fixed, next row). Build 5: all 54,881 steps compile (2 h 39 min); linking `chrome` fails on four Crashpad functions Helium's crash reporting calls (fixed, Crashpad row). Build 6 (3 November, with branding): compiles and links all 54,882 steps (2 h 44 min) and stages the browser and icons; `stage` stops on `chromedriver.unstripped`, which this tree never builds because Helium's `fix-building-with-prunned-binaries.patch` turns off chromedriver's Linux strip step; the port now installs `chromedriver` as `www/ungoogled-chromium` does, and a unit test ties the two together | `freebsd/results/` (logs with the owner) |
| Helium `IS_LINUX` conditions | all 9 conditions Helium adds (importer, keyboard shortcut label, zen mode window decorations) now include BSD; CI fails when Helium adds or changes one | `patches/platform/beryllium-bsd-helium-linux-conditions.patch`, `freebsd/tools/helium-linux-conditions`, `freebsd/helium-linux-conditions.json` |
| BSD/Helium conflicts | all 13 failing sections refreshed (10 Helium patches), 449 sections verified to apply; procedure in 05 section 7a | `freebsd/tools/patch-conflicts`, `patches/helium-refresh/` |
| Crashpad on FreeBSD | FreeBSD has no Crashpad and the port drops `crashpad.cc`; `crashpad_bsd.cc` defines the four functions Helium calls as "no reports, no uploads", so the crash dialog never appears; CI fails when Helium calls another one. Follow-up: Helium's crash reporting setting is still shown on FreeBSD and does nothing | `patches/platform/beryllium-bsd-no-crashpad.patch`, `freebsd/tools/helium-bsd-crashpad-calls` |
| Hard-coded Helium hosts | three in Helium's code, none reachable from a FreeBSD build: `crash.helium.computer` (Crashpad upload URL, no Crashpad on FreeBSD), `updates.helium.computer` (browser updater, compiled only for macOS and Windows), `helium.computer` as the extension-update ping domain (a filter, sends nothing by itself). Confirm with the runtime privacy regression test (07 section 6) once the browser runs | Q2, Q10 |
| Branding | art set v2 (owner, 3 November 2026) in place of every Helium logo and of art set v1, whose horned emblem resembled the FreeBSD logo (removed from the tree, including the README logo). Masters cut from the supplied sheet by `branding/tools/extract-art-sheet` (painted checkerboard removed); colour emblem (orb, "Be", two orbits) for icons from 48 px, lockups, `product_logo.svg` and the onboarding page; plain orb for icons at 16 to 32 px and for the vector glyph in Chromium's `.icon` slots. Checked with Chromium's own icon aggregator and in Chromium. The sheet's three-orbit app icons are not used. Open: vector master, artwork licence | `branding/`, `branding/README.md`, `branding/kit/README.md` |
| Onboarding links to Helium | the onboarding Welcome page links to Helium's privacy policy and terms (`helium.computer/privacy`, `/terms`); Beryllium needs its own or none (Q1, Q2) | follow-up, `components/helium_onboarding` |


## 10. First oracle results (1 November 2026)

Sources: the owner's 16.0-CURRENT host (`main-n290153-617c700abae7`,
`freebsd/results/oracle-16.0-CURRENT-20261101.json`), and FreeBSD
14.5-RELEASE and 15.1-RELEASE-p3 in the CI VMs (oracle version 2,
`freebsd/results/oracle-14.5-RELEASE-20261101.json` and
`oracle-15.1-RELEASE-p3-20261101.json`). The owner's host has
already set `security.bsd.see_other_uids=0`, `see_other_gids=0` and
`unprivileged_proc_debug=0`; the VMs use defaults.

### 10.1 Red-team predictions against measurements

| Finding | 16.0-CURRENT | 14.5 and 15.1 | Verdict |
|---|---|---|---|
| RT-01 `kern.hostuuid`, `hostid`, `hostname`, `domainname`, `boot_id` readable | readable | readable | **confirmed** |
| RT-02 `PF_ROUTE` and `AF_NETLINK` sockets, `getifaddrs()` | refused (`ECAPMODE`) | refused | **prediction wrong, good news**: local addresses are not readable from capability mode |
| RT-02 `socket()` for `AF_INET`, `AF_INET6`, `AF_UNIX` | allowed | allowed | confirmed (protocol code reachable, but `connect`, `bind` and `sendto` with an address refused) |
| RT-02 `kevent(EVFILT_PROC)` on a same-user process | allowed | allowed | **confirmed** |
| RT-02 `kevent(EVFILT_PROC)` on another user's process | refused (`ESRCH`, because of `see_other_uids=0`) | allowed | confirmed; the host setting closes it |
| `getpriority()` on other processes or the whole user | refused | **allowed** | **new**: the capability-mode check in `kern_resource.c` on `main` is not in 14.5 or 15.1 |
| `setpriority()` on another same-user process | not run (v1) | **allowed** | **new**: on the release targets a compromised renderer can push any of the user's processes, the browser included, to the lowest priority (availability, not confidentiality). Mitigations: the `mac_beryllium` scheduling hook, or the fix reaching 14.x and 15.x (an upstream report for the owner to file) |
| RT-16 W^X enforced after exec with `PROC_WX_MAPPINGS_DISALLOW_EXEC` | not run (v1) | **works**: W+X mapping refused, RW then RX still allowed | **confirmed** on the kernel side; V8 compatibility is the open part |
| RT-03 `ptrace` from capability mode | refused (`ECAPMODE`) | refused | safe on all three; the browser trace-disable stays as defence in depth |
| RT-04 kernel-attested capability mode | works | works | **confirmed**: the browser can verify children without trusting them |
| RT-15 `RLIMIT_NPROC=1` blocks `fork` | `EAGAIN` | refused | **confirmed** (corrects the original plan) |
| `FreeBSD-SA-26:28` (`sigqueue`) | refused | refused | fixed on all three |
| Read-only shared-memory twin | writable mapping refused, `mprotect` upgrade refused, exec mapping refused | same | **confirmed**; but see 10.2 |
| `/dev/fd` lists every descriptor | no (devfs, `fdescfs` not mounted) | no | **confirmed**: upstream `CloseSuperfluousFds` does nothing useful; `closefrom` is required (and works, `fd.closefrom`) |
| Errno for a refused sysctl or `uname()` | `ECAPMODE` | `EPERM` | the kind of difference the oracle exists for: policy code and tests must not assume one errno across branches |

### 10.2 What Phase 2 has to handle (measured, not predicted)

A renderer that calls any of these after `cap_enter()` fails, so each one is
cached in `PreinitializeSandbox` or its caller is patched:

- `uname()` fails with `ECAPMODE`, because `kern.version` is not readable in
  capability mode. Callers include Blink's `navigator.platform` fallback
  (RT-13) and `base::SysInfo`.
- `hw.physmem`, `vm.stats.vm.v_page_count` (the 2023 attempt's failure
  point) and `kern.proc.pid.<self>` are refused: physical memory, memory
  pressure and Chromium's own process metrics.
- `localtime()` falls back to UTC unless `caph_cache_tzdata()` runs first:
  pages would see the wrong local time.
- `dlopen()` of anything not already loaded fails.
- Shared memory: `fcntl(F_GETFL)` on the rights-limited read-only twin is
  refused without `CAP_FCNTL`, and with `CAP_FCNTL_GETFL` it reports
  `O_RDWR` even though the twin cannot be mapped writable. Chromium's
  permission check on handles therefore has to use `cap_rights_get()` on
  FreeBSD; `F_GETFL` gives the wrong answer (06 section 3.3).

Readable and harmless: `hw.ncpu`, `hw.pagesize`, `kern.osrelease`,
`kern.arandom`.

### 10.3 Fingerprinting surface after a renderer compromise

The sweep found 126 readable sysctl leaves on 16.0-CURRENT (113 on 14.5, 115
on 15.1). Besides the five identifiers of RT-01: about 70 `kern.features.*`
booleans (kernel configuration), `hw.model` (exact CPU model) and
`kern.build_id` (identifies the kernel build). Low severity on their own;
the `mac_beryllium` sysctl filter (RT-02) would cover them, and a jail does
not.

### 10.4 Facts about the owner's host

- **GPU actually used: the NVIDIA RTX 5090** (`chrome://gpu`, committed as
  `freebsd/results/chrome-gpu-16.0-CURRENT-20261101.txt`): ANGLE on NVIDIA's
  OpenGL ES 3.2 driver 595.99.02 through EGL, ozone Wayland,
  `--render-node-override=/dev/dri/renderD128`, Vulkan off, WebGL and
  WebGPU hardware-accelerated (Dawn on ANGLE GLES). The laptop also has an
  Intel Arrow Lake GPU (`i915kms`), but Chromium does not use it here. So
  the first GPU policy is the NVIDIA one after all (charter D6 stands),
  with the closed driver's ioctl surface (R23) as its main residual risk.
  WebGPU on this path is extra attack surface reachable from every page; a
  hardened profile that disables it is cheap to offer.
- **No Chromium process is confined today**, by observation: the per-process
  baseline shows no capability-mode flag on the browser, GPU, network,
  storage, audio, data-decoder or any renderer process
  (`freebsd/results/baseline-16.0-CURRENT-20261101.md`). Yet `chrome://gpu`
  reports "Sandboxed: true" (RT-17).
- The baseline's descriptor, rlimit and environment columns are empty
  because `security.bsd.unprivileged_proc_debug=0` stops `procstat` reading
  even the user's own processes; the script now has a root mode
  (`-u <user>`) for that case.
- XWayland is running (`DISPLAY` is set alongside `WAYLAND_DISPLAY`), so X11
  clients exist in the session even under Wayland.
- The host's own hardening sysctls blocked two attacks even outside
  capability mode. They go into `pkg-message` as optional hardening, noting
  that `unprivileged_proc_debug=0` stops users debugging their own
  programs.
- Kernel `osreldate` 1600028; the chromium package was built for 1600029.
  Updating the base system to match the packages avoids ABI surprises on
  CURRENT.
- Oracle version 2 on this host: 60 ok, 6 exposed (the RT-01 identifiers and
  same-user `EVFILT_PROC`), 0 broken, 0 errors; W^X after exec works and
  `setpriority` on other processes is refused.
