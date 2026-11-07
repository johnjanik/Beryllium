# Beryllium: Renderer Sandbox, Phase 2 Working Notes

**Started:** 4 November 2026. **Implements:** [09-ROADMAP.md](09-ROADMAP.md)
section 4 (Phase 2), [06-SECURITY-MODEL.md](06-SECURITY-MODEL.md) section 3,
feature matrix rows `S-REN-*`, `S-SHM-*`, `S-IPC-*`, `S-HRD-*`, `S-STA-*`.

## 1. What the code does today

Read from the post-patch tree (Chromium 156.0.8078.79, Helium 0.20.3,
FreeBSD ports 6ad3e0c8) with `freebsd/tools/patch-workbench`.

- `sandbox/policy/freebsd/sandbox_freebsd.cc` (imported FreeBSD patch) is
  the whole FreeBSD sandbox. `PreinitializeSandbox()` warms up three
  `base::SysInfo` values, and for renderers `gfx::InitializeFonts()`;
  `InitializeSandbox()` lowers `RLIMIT_DATA` and returns. Nothing calls
  `cap_enter`.
- Every process type reaches it. A renderer runs `PreSandboxInit()`
  (`content/app/content_main_runner_impl.cc`: system values, BoringSSL,
  rust_png CPU features, WebRTC, WebNN), then `RendererMain()` calls
  `RendererMainPlatformDelegate::EnableSandbox()`, which calls
  `sandbox::policy::Sandbox::Initialize()` and so
  `SandboxLinux::InitializeSandbox(kRenderer)`; the FreeBSD patch only
  skips the Linux seccomp checks after it. The GPU process arrives through
  `StartSandboxLinux` (`content/gpu/gpu_main.cc`), utility processes through
  `Sandbox::Initialize`. So every child gets the warm-up and the 4 GB
  `RLIMIT_DATA` (the survey shows `datasize=4194304 KB` in all of them).
  (A first reading on 4 November 2026 said renderers never reach it; that
  was wrong: it missed the `Sandbox::Initialize()` call above the skipped
  checks.)
- There is no zygote on FreeBSD: each renderer is launched from the
  browser, inherits its Mojo channel as a descriptor, and initialises Mojo
  after `EnableSandbox()`.

## 2. The lockdown point

The end of `SandboxLinux::InitializeSandbox()` for `kRenderer`
(`sandbox/policy/freebsd/sandbox_freebsd.cc`), reached from
`RendererMainPlatformDelegate::EnableSandbox()`
(`content/renderer/renderer_main_platform_delegate_linux.cc`). It runs:

- after `PreSandboxInit()`, so the existing warm-up has happened;
- before `RenderProcessImpl` and `RenderThreadImpl` exist, so before any
  page content is handled and before most threads start;
- with the Mojo channel already an inherited socket descriptor, which keeps
  working in capability mode (`sendmsg`/`recvmsg` with `SCM_RIGHTS` are
  allowed).

Beryllium's change does, for `kRenderer` only: finish the warm-up, limit and
close descriptors, harden (`procctl`), `cap_enter`, check `cap_getmode`, log
one line, and on failure end the process in a production build.

## 3. Increments

Each increment is one Poudriere build; the owner's machine is the only
FreeBSD test bed, so an increment must be worth a build.

1. **Survey, no build needed** (done, 4 November 2026):
   `freebsd/tests/browser/run capsicum --diagnose` runs the installed browser
   under `ktrace -t pny` and lists, per process type, every system call,
   path lookup and sysctl that capability mode would refuse, across the
   plan/09 workloads, with each process's descriptors, environment variable
   names and limits. FreeBSD records these "CAPFAIL" events for processes
   that never entered capability mode (since 14.1 and 15). Its report is the
   input to increments 2 and 3.
2. **Opt-in lockdown** (written 4 November 2026, in the next build:
   `patches/security/beryllium-capsicum-renderer.patch`): warm-up, a
   `utrace` marker at the lockdown point (always, so the survey splits each
   renderer's trace into before and after), and `cap_enter` only with
   `--enable-features=BerylliumCapsicumRenderer`; with
   `BerylliumCapsicumTrap` as well, `PROC_TRAPCAP_CTL` turns the first
   refused call into SIGTRAP and a backtrace. The survey of 4 November found
   renderers reading, among others, `vm.stats.vm.v_page_count` and
   `v_page_size` about 19 times each and `kern.ipc.shmmax` and
   `kern.version` (via `uname()`) once, all refused in capability mode, where
   their FreeBSD code calls `NOTREACHED()` or `CHECK` and would end the
   renderer; `base/system` now keeps those answers once read, and the
   warm-up reads them first. Most of the survey's 18,000 refused calls
   (library loading, resource paks) are start-up, before the lockdown
   point; the marker will show which remain after it.
   **Results, 0.20.3.3 on the owner's machine (4 November 2026):** with the
   feature on, every renderer is in capability mode and the whole browser
   suite passes. After the lockdown point renderers are refused only
   `cpuset_getaffinity` (18 calls over 20 renderers) and one `open`; trap
   mode stops them at the first of these. Core dumps cannot be written from
   capability mode ("no core dump - other error"), so the survey run with
   the feature on, not `--cores`, shows what a confined renderer is refused.
   **But it is not yet a sandbox:** the survey's descriptor list shows a
   renderer holding about 120 descriptors inherited from the browser,
   among them directories (`/`, `/usr`, `/usr/local`, `/usr/local/etc`) and
   writable profile databases, which capability mode leaves usable.
   **Results, 0.20.3.4 (5 November 2026):** every renderer in capability
   mode again; after the lockdown point only `cpuset_getaffinity` (18
   calls over 20 renderers) is refused, and the `open` is gone (probably
   the `libgcc_s` preload). The 18 calls are most likely libc's
   `sysconf(_SC_NPROCESSORS_ONLN)`, which asks the root cpuset first
   (refused in capability mode, which allows only `CPU_LEVEL_WHICH` for the
   process itself) and then falls back to the processor count from the ELF
   auxiliary vector, so they cost nothing. The survey also counted 40
   `kern.proc.filedesc` reads after the marker: the lockdown's own
   directory sweep, which ran after the marker and before `cap_enter`. The
   marker is now the last call before `cap_enter` (build 0.20.3.5).
3. **Descriptor hygiene and allowlist** (started in 0.20.3.4):
   `patches/security/beryllium-close-inherited-descriptors.patch`
   makes every child close what it inherits (`/dev/fd` lists only 0-2 on
   FreeBSD without fdescfs, so Chromium's own walk closed nothing), and the
   lockdown closes and counts any directory descriptor left before
   `cap_enter`. A sandbox test fails on any renderer holding a
   directory or writable file.
   **Results, 0.20.3.4:** with and without the lockdown, renderers hold
   about 30 descriptors instead of about 120, and no directory or profile
   file. Even without the lockdown's sweep (the run without the feature),
   none holds a directory, so the launcher fix alone removes them. The
   test still fails: each renderer holds five to nine writable regular
   files with no name. They are Chromium's shared memory regions, which on
   FreeBSD are unlinked files in TMPDIR (increment 4).
   Then: the committed renderer allowlist from the survey, rights limits
   per descriptor (the survey now prints each descriptor's rights),
   environment allowlist.
4. **Shared memory without a namespace** (written 5 November 2026, in
   build 0.20.3.5: `patches/security/beryllium-anonymous-shared-memory.patch`,
   S-SHM-01, S-SHM-02): every region is a `memfd_create` object sealed
   against shrinking and growing, as on Linux, instead of an unlinked file
   in `/tmp`, which put page content on a disk file system and let a
   renderer write, truncate, grow and map executable its files. The
   read-only twin is a duplicate limited to `CAP_MMAP_R`, `CAP_FSTAT` and
   `CAP_FCNTL` (`F_GETFL` only), and the writable descriptor to
   `CAP_MMAP_RW`, `CAP_FSTAT` and `CAP_FCNTL`; Chromium's access-mode check
   reads the rights. The Capsicum oracle had already shown on 14.5, 15.1
   and 16.0-CURRENT that such a twin cannot be mapped writable or
   executable or upgraded with `mprotect`. Renderers do not create regions
   themselves (Mojo's broker asks the browser; the survey finds no
   creation attempt after the lockdown), and with memfd they could. New
   test: `test_renderer_shared_memory_is_anonymous_and_limited`.
   **Results, 0.20.3.6 (5 November 2026), with and without the lockdown:**
   the whole suite passes (video, WebGL, many busy tabs, the toolbar) apart
   from the descriptor test. Renderers hold their shared memory as memfd
   objects with exactly the intended rights: writable regions read, write,
   seek, map read-write, fstat and F_GETFL (no ftruncate, no executable
   mapping, no chmod or chown); read-only twins read, seek, map read-only,
   fstat and F_GETFL. Of the five to nine unnamed writable files per
   renderer in 0.20.3.4, one remains in every renderer, so something other
   than `PlatformSharedMemoryRegion` makes it. The FreeBSD port also lets
   renderers and the GPU process create unsafe regions themselves
   (`patch-content_app_initialize__mojo__core.cc`), which memfd now allows
   in capability mode too. To identify the remaining file without a
   rebuild, the descriptor test now reports its file system, inode, size
   and mode and every other Beryllium process holding it (`fstat`), and the
   survey lists the files each process type, the browser included, looks
   up directly in a temporary directory.
   The survey of 0.20.3.6 (lockdown on, before those diagnostics) narrows
   it down: after the lockdown point renderers are refused only
   `cpuset_getaffinity` and read only `hw.ncpu`, so the moved marker works;
   the GPU process now holds about 40 memfd regions and no unnamed file,
   and the network, storage and audio processes none either. Only
   renderers hold the remaining file, and it has every Capsicum right, so
   it does not come from the memfd path, which limits rights at creation.
   **Identified** with the new diagnostics (same day): 0 bytes, mode
   `-rw-------`, held by no other process; renderers look nothing up in
   `/tmp`, the browser looks up `/tmp/.org.chromium.Chromium.XXXXXX` 63
   times for about 21 renderers, three lookups each (create, open,
   unlink). That is `RenderProcessHostImpl::ProvideSwapFileForRenderer()`:
   a swap file for Blink's `DiskDataAllocator`, which writes compressed
   parked strings (scripts of background tabs; on by default on Linux and
   FreeBSD) and images into it. Every normal renderer gets one, Incognito
   renderers none. `patches/security/beryllium-no-renderer-swap-file.patch`
   (build 0.20.3.7) skips it unless `BerylliumRendererSwapFile` is
   enabled, so parked data stays compressed in memory, as in Incognito.
   **Results, 0.20.3.7 (5 November 2026), with and without the
   lockdown:** the whole suite passes, the descriptor test included: no
   renderer holds a directory or a writable file, and with the lockdown
   every renderer is in capability mode.
   **Policy and least rights (written 7 November 2026, build 0.20.3.8):**
   the lockdown now judges every descriptor from 3 up by the type the
   kernel reports and cuts it to that type's rights: read-only resource
   files (read, seek, read-only mapping, fstat, F_GETFL), sockets (send,
   receive, event, fstat, shutdown, get/setsockopt, F_GETFL/F_SETFL; never
   connect, bind, listen, accept), kqueues (kevent), eventfds and pipes
   (read, write, event, fstat, F_GETFL/F_SETFL), shared memory (what its
   creator gave it, less truncation, executable mapping and ownership
   changes); no ioctls anywhere; directories closed; anything else ends
   the renderer, naming the descriptor. The suite checks the same policy
   from outside (`test_confined_renderer_descriptors_follow_the_policy`:
   `procstat -f` and `-C` per renderer, including that every file is a
   read-only resource file under `/usr/local/share/beryllium/`), and
   `test_45_fonts` checks that a confined renderer sets nine scripts in
   the same platform fonts as an unconfined one (fonts reach renderers
   through the browser's font service; the survey saw no font file access
   after the lockdown, this makes it a test). Still open in this
   increment: rights on what the browser passes later over Mojo (it
   carries the sender's rights; S-IPC-01), and the environment allowlist.
   **Results, 0.20.3.8 (7 November 2026):** the suite passes with and
   without the lockdown, and the fonts test passes, so the rights limits
   broke nothing visible. But the survey shows 6.1 million refusals after
   the lockdown point, all "operation requires invalid cap_rights_t,
   descriptor holds CAP_KQUEUE": Chromium's epoll message pump runs on
   epoll-shim on FreeBSD, and epoll-shim's `epoll_wait()` polls its kqueue
   with `poll()` before each `kevent()`; `poll()` needs CAP_EVENT, which
   the kqueue policy did not grant, so every poll failed at once and every
   renderer spun instead of sleeping. (kdump prints the needed rights as
   "invalid" because the kernel's static `cap_event_rights` initialiser
   leaves word 0 without index bits; CAP_EVENT is an index-1 right.) The
   suite passed because it never looks at CPU time. For 0.20.3.9: kqueues
   keep event and fstat as well; eventfds and pipes keep the ioctl
   FIONREAD, which epoll-shim uses at registration to tell them from
   kqueues (without it an eventfd is treated as a pipe, which happens to
   work); and a new test fails on a renderer that uses more than a second
   of CPU in five idle seconds.
   **Policy test, 0.20.3.8 with `unprivileged_proc_debug=1` (same day):**
   it fails as it should, and the survey's descriptor list shows why:
   everything that existed at the lockdown point is cut (stdio, the
   resource paks, the V8 snapshot, the first socket pair, the main
   thread's kqueue and eventfd, the shared memory), and everything that
   appears afterwards has every right: a kqueue and an eventfd per thread
   that starts its message pump after the lockdown, every socket the
   browser sends for a transport, and one read-only file (a font, from
   the font service). Capsicum has no default rights for new descriptors.
   `patches/security/beryllium-descriptor-rights.patch` (build 0.20.3.9)
   puts the policy in `base/posix/capsicum_rights.h`, cuts the message
   pump's kqueue and eventfd at creation, and in a process in capability
   mode cuts every descriptor received over Mojo to its kind (classified
   with `fstat`, an empty `kevent` and `F_GET_SEALS`, since
   `kern.proc.filedesc` and `F_KINFO` are refused there), removing every
   right from one the policy has no kind for. That is defence in depth,
   not the boundary: a compromised renderer can `recvmsg` for itself. The
   boundary is the browser limiting what it sends (S-IPC-01, next).
5. **Sender-side rights and attestation** (next, build 0.20.3.10): the
   browser cuts every descriptor it sends to a renderer to its kind's
   rights before sending (the transport must know it leads to a renderer);
   then attestation: the browser checks
   each renderer's capability mode with the kernel (`kern.proc.pid`,
   `KI_CRF_CAPABILITY_MODE`) once the renderer reports its lockdown, and
   ends an unconfined one before it gets a navigation; `beryllium://sandbox`
   shows the kernel's answer per process; the release's sandbox table
   changes from "not confined".
6. **Default on, fail closed** in the production package; the devel package
   keeps the switch.

## 4. Open items

- **Prototype evaluation (plan/09 Phase 2 item 0):** done 4 November 2026,
  [15-CAPSICUM-PROTOTYPE-EVALUATION.md](15-CAPSICUM-PROTOTYPE-EVALUATION.md).
  Decision: diverge on architecture, borrow the findings; its time-zone and
  message-catalogue caching, the `libgcc_s` preload and `caph_limit_stdio()`
  are in the lockdown patch for the build after 0.20.3.3.
- **Time zones on 14.x and 15.x** may fall back to UTC in capability mode
  (oracle results from CI machines, to recheck; plan/15 section 5).
- **Kernel facts** come from the Capsicum oracle results in
  `freebsd/results/` (126 sysctls readable in capability mode on
  16.0-CURRENT); the survey marks each sysctl a process reads against that
  list.
