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
   **Adversarial review, 7 November 2026 (build 0.20.3.10;
   [plan/16](16-ADVERSARIAL-REVIEW-2026-11-07.md)):** an external review
   of the 0.20.3.8 inputs showed, with the lockdown code compiled against
   stubbed system calls, that admission by kernel type kept a read-only
   file anywhere and any socket, and that a failed `caph_limit_stdio()`
   was only logged. From 0.20.3.10 a read-only file is admitted only
   under `base::DIR_ASSETS` (the installed resources; fonts come later
   through the font service), a socket only as an unnamed AF_UNIX stream
   or seqpacket pair bound and connected to no path (also for sockets
   received after the lockdown), each `kinfo_file` record is
   bounds-checked, and a failed stdio limit ends the lockdown. The suite's
   sandbox tests become a gate when the lockdown is requested (BER-04):
   any renderer not in capability mode, unreadable, or outside the policy
   fails them; `freebsd/tools/tests/test_sandbox_gate.py` holds the
   reviewer's negative scenarios. Expected on the owner's machine: the
   same results as 0.20.3.9 (every renderer confined, policy test passing,
   idle CPU low), unless a renderer holds a read-only file outside
   `/usr/local/share/beryllium/` at its lockdown point, in which case the
   browser log names it ("fd N: read-only file ... is not under ...") and
   the renderer ends; that file would then need a decision, not a wider
   rule.
   **Results, 0.20.3.10 (7 November 2026, three runs with
   `unprivileged_proc_debug=1`):** without the lockdown the whole suite
   passes. With it, every renderer the browser listed was in capability
   mode, idle CPU was 0.00 s, fonts matched, and the survey's descriptor
   list of a blank-page renderer shows every kqueue, eventfd, shared memory
   object, resource file and received socket cut to the policy, with two
   exceptions: fd 13 (a blocking unix socket) and fd 18 (non-blocking),
   both with every right, both unnamed. They were neither in the table the
   sweep read nor seen by the receive path. The explanation written here
   at the time, that the IO thread was already receiving Mojo messages
   during the sweep, was wrong: `RendererMain()` enables the sandbox before
   `RenderProcessImpl` and `RenderThreadImpl` exist (the early path every
   platform but Windows and macOS takes; startup tracing and the hang
   watcher wait for the sandbox on Linux and BSD), so no IO thread runs
   during the sweep. The two sockets were pairs the renderer made itself
   after the lockdown, as 0.20.3.11 and 0.20.3.12 showed below. For
   0.20.3.11 the lockdown calls `base::freebsd::ExpectConfinement()`
   before the snapshot, which makes both receive paths (Mojo's
   `SocketRecvmsg` and `base::UnixDomainSocket::RecvMsgWithFlags`, the
   latter newly hooked; it carries the sandbox IPC replies with font files)
   limit from that moment; that stays as a precaution against any thread
   that does run. The survey and the
   policy test now say where each socket's other end is (`fstat -p` pcb
   matching across the browser's processes), so a socket outside the
   policy is named by its peer next time. Two more results: the gate
   failed once on a renderer the browser had just launched and that had
   not yet reached its lockdown point (`capability_modes` now gives a
   listed renderer five seconds), and the rendering test's canvas read
   back `18,52,87` for `#123456` under the lockdown (86 without it, and
   86 under the lockdown in 0.20.3.8). The lockdown's log lines (now
   reported by `test_lockdown_log`; a received descriptor the policy has
   no kind for is logged as its rights are removed) showed no refusal and
   the GPU report was identical; 0.20.3.11's rendering runs with and
   without the lockdown, and with the canvas forced onto the CPU, all read
   86: a one-off in the GPU readback, so the test allows the GPU canvas
   one level and keeps a CPU-side canvas exact.
   **Results, 0.20.3.11 (8 November 2026, three runs):** the receive
   window is closed: every socket a renderer receives is cut, the log test
   shows no refused descriptor, every listed renderer is in capability
   mode and the idle-CPU test passes. Two sockets per renderer still have
   every right, and the survey can now say what they are: unix stream
   sockets, one blocking and one not, each with its other end in the
   browser, present in blank-page renderers. Not received (the receive
   paths would have cut them) and not in the table at the snapshot (the
   sweep would have): the renderer makes them itself with `socketpair()`
   and sends one end to the browser, and a new socket has every right.
   Chromium makes socket pairs in three places (`base::CreateSocketPair`,
   seqpacket, the sandbox IPC request pairs; `base::SyncSocket::CreatePair`,
   stream, blocking; `mojo::PlatformChannel`, stream, non-blocking), which
   match the two shapes seen. For 0.20.3.12 all three call
   `base::freebsd::LimitCreatedSocket()` on both ends, so a socket a
   confined process creates has a transport's rights from birth, whoever
   it is for, and logs each pair with the thread that made it, since the
   0.20.3.11 survey shows the same blocking socket to the browser in the
   GPU, network and storage processes too: a Chromium pattern to name, not
   a renderer oddity. The survey and the policy test also list the threads
   waiting on a socket (`procstat -t`, wchan `sbwait`), which will say
   whether a pending request holds them. The survey matches socket ends
   only within one sample now: the kernel reuses a closed socket's
   address, and matching across samples minutes apart gave wrong peers
   in the 0.20.3.11 survey (the policy test, which matches within one
   moment, was right).
   **Results, 0.20.3.12 (8 November 2026, released as v0.20.3.12 with its
   build manifest; three runs, `unprivileged_proc_debug=0` this time):**
   every listed renderer in capability mode, the receive path refused
   nothing, idle CPU zero, and the creation hook's log names the two socket
   pairs: one made on `CrRendererMain` right after the lockdown (its kept
   end blocking, so `base::SyncSocket::CreatePair` or a
   `CancelableSyncSocket`), one on `Compositor` (kept end non-blocking, so
   `mojo::PlatformChannel` or a `CancelableSyncSocket` after its first
   send), 14 pairs for 7 renderers, all cut at creation. The descriptor
   tests failed under the gate only because `procstat` could not read the
   renderers (the sysctl was 0), which is the gate working. Which Chromium
   code makes the pairs is still to be named: not the ipcz driver (only
   brokers create transports), not the thread-type switcher (stubbed on
   BSD); the browser holds the other ends. From 0.20.3.13 the log line
   names the site (`base::CreateSocketPair`, `base::SyncSocket::CreatePair`
   or `mojo::PlatformChannel`), and the lockdown line carries `threads=N`,
   the process's thread count at the lockdown point from `kern.proc.pid`,
   which the gate requires to be 1: the single-threaded sweep is then a
   checked fact, not an inference from Chromium's source. **The colour anomaly is not
   the GPU:** with the lockdown on, both the default and the CPU-drawn
   canvas read `18,53,86` for `#123456` (green one level up; 0.20.3.10
   had blue one level up on the GPU canvas), and never without the
   lockdown (0.20.3.8, 0.20.3.11 and every default run exact). The one-
   level allowance is withdrawn: the test is exact on both canvases again,
   and records the context's own `fillStyle`, a `putImageData` round trip
   and a sweep of greys and primaries on the CPU canvas, so the next
   occurrence shows whether the parser, the fill or the copy moves the
   value and which values move. Candidates: a colour transform fed by a
   failed call in capability mode, or memory the renderer reads
   uninitialised after one (`cpuset_getaffinity` is the one call refused
   after the lockdown, once per renderer; `pthread_attr_get_np` uses it,
   and V8's `Stack::GetStackStart()` calls that on FreeBSD).
   **The same three runs with `unprivileged_proc_debug=1` (16:29 to
   16:38):** the policy held on every renderer the suite could read, four
   of five, with zero descriptors outside it, the first time since the
   policy test exists; the survey's blank-page renderer shows fd 13 and
   fd 18 cut, their other ends in the browser, every received socket cut
   and its other end named (GPU, network and storage services for the
   introductions, the browser for the channel and the sandbox IPC pair),
   one pair made in-process before the lockdown (fd 19 and 23, cut by the
   sweep), and no thread waiting on a socket: the pairs are idle channels,
   not pending requests. The fifth renderer was reported unreadable: it
   had exited but not yet been reaped, and a zombie still answers
   `kill(2)` while it has no descriptor table, so `process_alive` now asks
   `ps` for the state and counts a zombie as gone. The canvas read
   `18,52,87` on both canvases again (three of six lockdown runs now; the
   owner's checkout predated the sweep, so no sweep yet). Two test corrections from the
   same runs: the five-second wait for a starting renderer applies only
   under the gate (a survey has nothing to wait for), and a confined
   renderer that exits before its descriptors are read is reported as
   ended, not as unreadable.
5. **Sender-side rights** (written 9 November 2026, build 0.20.3.13:
   `patches/security/beryllium-sender-side-rights.patch`, S-IPC-01): the
   browser cuts every descriptor it sends a confined renderer to its
   kind's rights before `sendmsg()`, so a renderer that stops running our
   receive-side code gains nothing. The hook points, read from Chromium
   156: `ChildProcessLauncherHelper::PostLaunchOnLauncherThread` knows the
   child's pid and sandbox type before it sends the Mojo invitation, and
   registers a renderer launched with the lockdown feature on as a
   confined peer (`base::freebsd::ExpectConfinedPeer`; forgotten when the
   launcher helper goes, since pids are reused);
   `mojo::core::ipcz_driver::Transport::Transmit()` is the one place a
   transport sends platform handles and knows its `remote_process_`, and
   cuts every handle bound for a confined peer
   (`base::freebsd::LimitSentDescriptor`): read-only files, writable
   files, sockets, kqueues, eventfds and pipes, shared memory by kind; a
   device, a directory or anything else loses every right and is logged.
   The feature `kBerylliumCapsicumRenderer` moved to
   `base/posix/capsicum_rights.h` so the browser reads the same switch.
   New kind `kWritableFile` (pread, pwrite, ftruncate, fsync, read-write
   mapping, fstat, F_GETFL): a File System Access sync access handle is a
   file the browser hands a renderer on purpose; the receive path admits it
   with those rights, the lockdown point still refuses any writable file,
   and the suite accepts one only under the profile's `File System`
   directory with no right beyond the kind. **Verification:** the sandbox
   class runs with `--vmodule=capsicum_rights=1`; the browser logs each cut
   at VLOG(1), and `test_lockdown_log` counts them per renderer and, on a
   build that reports the thread count, requires at least one and no
   outright refusal. **Not covered:** the transports between a renderer
   and the GPU process (introduced by the browser, they carry no remote
   process in either end's `Transport`), so what the GPU process sends a
   renderer is still limited by the receiver only; a device descriptor (a
   GPU memory buffer) would be refused on both sides today, which is where
   a `kGpuBuffer` kind would go if renderers ever receive one; and a
   verification that the sender alone suffices needs a development-only
   build switch that turns the receiver's limit off, listed in section 4.
   **Results, 0.20.3.13 (9 November 2026, three runs with
   `unprivileged_proc_debug=1`; the first build failed because the
   confined-peer member was declared inside Chromium's ChromeOS block,
   fixed the same day):** every listed renderer in capability mode; the
   policy held on all four renderers read (20 to 36 descriptors each,
   none outside it); the receive path refused nothing; the browser cut
   between 1 and 88 descriptors per renderer before sending (`cut` lines
   at VLOG(1)), none refused outright. The creation hook named both
   socket pairs: `mojo::PlatformChannel`, one on `CrRendererMain` and one
   on `Compositor` per renderer, so the earlier reading of the blocking
   one as a `SyncSocket` was wrong; the caller is still to be named, and
   0.20.3.14 logs a stack trace for the first pair at each site and
   thread (the package keeps function names). Three findings against the
   increment. (1) `threads=-1` in every renderer: `kern.proc.pid` failed
   before `cap_enter()` and the code logged nothing about why (the kernel
   answers one record per process unless `KERN_PROC_INC_THREAD` is asked,
   so it was not a size overrun). 0.20.3.14 asks with
   `KERN_PROC_INC_THREAD`, counts the records by their own
   `ki_structsize`, so a kernel whose `kinfo_proc` is not the size of the
   build's headers still counts, and logs errno or the sizes on failure.
   (2) The survey's after-lockdown list gained 242 refusals on sockets
   holding exactly the socket policy's rights, printed by kdump as
   `operation requires invalid cap_rights_t`: the receive path's own
   `getsockname()` and `getpeername()` on sockets the browser had already
   cut (the policy has neither `CAP_GETSOCKNAME` nor `CAP_GETPEERNAME`),
   two per received socket, about twelve per renderer. From 0.20.3.14 the
   receive path asks only when it holds the rights (`cap_rights_get`) and
   takes a socket its sender cut as unnamed and unconnected, which the
   sender checked. The `invalid` is kdump's, not a sign of a malformed
   check: on this CURRENT the kernel's constant rights sets
   (`CAP_RIGHTS_INITIALIZER` in `sys/capsicum.h`) leave the index bits of
   their unused word unset and `sysdecode_cap_rights` rejects the set
   instead of naming the right; a FreeBSD matter for the maintainer to
   raise if he wishes. (3) **The colour anomaly is not the lockdown's:**
   the sweep written for 0.20.3.12 ran for the first time and found, with
   the lockdown off as well as on, every fourth sampled grey (step 5, so
   a period near 20 levels) one level off in one channel, plus one or two
   of the mixed colours, on the CPU canvas; the default canvas and
   `#123456` itself were exact in both runs. The direction was +1
   throughout one run and -1 throughout the other, the channel varied,
   and the set of values differed between runs; the three-of-six count
   with the lockdown was chance in which values a run hit. Candidates
   now: a colour transform with a periodic rounding error (a lookup table
   or a display profile reaching the canvas's colour space), or a GPU
   readback despite `willReadFrequently`. The rendering test now sweeps
   all 256 greys by fill and by `putImageData` on both canvases, reads
   each twice, records the context attributes, the screen's gamut and the
   GPU page's display colour information, and when a value moves runs
   the same probe in a browser with `--force-color-profile=srgb` and in
   one with `--disable-gpu`; no build is needed for that. **Resolved the
   same evening:** six more runs (three with `unprivileged_proc_debug=0`,
   three with 1) showed every grey that moved in a run sharing one residue
   modulo 4 (3, 3, 1, 3; the run of 19:33 had 0 with -1), with the channel
   varying: a quarter of all values, selected by value, with a per-run
   seed. That is Helium's canvas fingerprinting noise
   (`helium/patches/helium/core/noise/canvas.patch`, feature
   `HeliumNoiseCanvas`, on by default under `HeliumNoise`): on every
   `getImageData`, `toDataURL` and `toBlob`, a pixel in a smooth 3x3
   neighbourhood has one RGB channel moved by one level when a hash of a
   per-session, per-origin token, its coordinates and its value selects it
   (one in four), the channel and the direction from a hash of the token
   and the content. Our probe read one fixed pixel of a flat fill, so the
   selection fell on the value alone, and `#123456` was hit only in the
   runs whose residue matched one of its channels (86 and 18 are 2 modulo
   4, 52 is 0: the `18,52,87` and `18,53,86` of 0.20.3.10 and 0.20.3.12).
   The lockdown had nothing to do with it; the three-of-six count was the
   odds. The rendering group now runs with
   `--disable-features=HeliumNoiseCanvas` and tests the rasterizer, and
   `test_60_privacy` gains a class that checks the noise itself: present
   by default on a flat fill, one level in one channel, alpha untouched,
   the same on a second read, different between `127.0.0.1` and
   `localhost`, and absent with the feature off (P-FPR-04). Fonts, from the
   same runs: with `noto-sans-sc` installed every script is drawn with a
   font that has its glyphs (Chinese and Japanese in Noto Sans SC, Korean
   in Noto Sans Mono CJK SC), with and without the lockdown.
   **Results, 0.20.3.14 (10 November 2026, three runs each with
   `unprivileged_proc_debug=0` and 1):** the rendering group is exact on
   every sweep with the canvas noise off, on both canvases, by fill and by
   copy, the first time since 0.20.3.8; the canvas noise tests pass
   (24 per cent of a flat fill's pixels moved by one level in one channel,
   the same on a second read, none with the feature off), except that in
   one of four runs the second origin's first load moved exactly the first
   origin's pixels, as if it had used the first's token (the test now
   reloads once and notes it; a Helium matter if it recurs). The survey's
   after-lockdown list is down to `cpuset_getaffinity`, 20 in 20
   renderers: the 242 refusals were the receive path's own calls, as
   diagnosed. The policy held on every renderer read, the browser cut 1 to
   93 descriptors per renderer, and both socket pairs are logged with
   stack traces, which the report did not carry (the note printed only
   lines with the marker; it now prints the trace blocks and the thread
   count's error lines). **The thread count is still -1 in every
   renderer**, by the second method as well, so `kern.proc.pid` itself
   fails for a renderer before `cap_enter()`; the reason is in the
   browser's stderr log of these runs (`kern.proc.pid` lines) and in the
   next report. **Both answered from the stderr log the same morning:**
   no `kern.proc.pid` error was logged, because the kernel had answered
   every time; `LockDownRenderer` stored the count in the `Confinement`
   that `*confinement = ConfineDescriptors()` then replaced, in 0.20.3.13
   and 0.20.3.14 alike (0.20.3.15 reads it before the sweep and assigns
   it after). And the stack traces were empty lines: the official build
   strips unwind tables and `base::debug::StackTrace` unwinds with them.
   0.20.3.15 walks the frame pointers the build keeps and logs each
   return address as module+offset on the same line; the suite names the
   offsets in the browser binary with `llvm-symbolizer` (the package keeps
   function names) and prints the chain in the lockdown-log note.
   **Results, 0.20.3.15 (10 November 2026, three runs):** everything
   passes but the thread count. The return addresses named both
   socket-pair callers, and both are Mojo's own: on `CrRendererMain`,
   `mojo::core::ipcz_driver::BaseSharedMemoryService::CreateClient()`
   while `Invitation::Accept()` takes the browser's invitation in
   `ChildThreadImpl::Init()`, one end for the browser (the blocking socket
   the survey had seen since 0.20.3.11); on `Compositor`,
   `mojo::core::ipcz_driver::Transport::CreatePair()` for
   `mojo::internal::ThreadLocalNode`, made when
   `blink::WidgetInputHandlerImpl` binds on the compositor thread, both
   ends staying in the renderer (fd 19 and 23 in the survey). Nothing to
   change: both are cut at creation. The canvas noise tests passed in both
   runs, the second origin moving other pixels on its first load. The
   survey's after-lockdown list is `cpuset_getaffinity` alone. **The
   thread count reads 2 in every renderer.** So one thread besides
   `CrRendererMain` exists at the lockdown point, against the reading of
   Chromium's ordering: `ContentMainRunnerImpl` creates the renderer's
   thread pool before `RendererMain` but does not start it, the hang
   watcher and startup tracing wait for the sandbox on Linux and BSD, and
   `PreSandboxInit` (sysinfo, BoringSSL, WebRTC, WebNN, cpuinfo) starts
   nothing visible; a candidate is a thread one of those libraries starts
   for itself. 0.20.3.16 logs the names (`thread_names=` on the lockdown
   line, from each `kinfo_proc` record's `ki_tdname`), and the suite
   prints the ones besides `CrRendererMain`. If the thread is one that
   cannot open or receive descriptors, the sweep's claim stands with that
   qualification; if not, the lockdown has to move earlier or stop that
   thread first. The gate keeps requiring one thread until then.
   **Results, 0.20.3.16 (10 November 2026, two runs, neither with the
   lockdown):** the thread names are still to come; these two runs each
   named a render node, the first since the Intel driver was loaded
   beside NVIDIA's. *On the NVIDIA node* (`renderD128`) everything passes
   but the per-site canvas noise test: both origins moved the same 982
   pixels, after the reload as well, so the first-load explanation of the
   0.20.3.14 result was wrong. The cause is in Helium's noise hash. It
   takes an FNV-1a step per value (xor, multiply) and hands out its bits
   from the low end, and the low two bits of a product depend only on the
   low two bits of its factors; in a smooth area a pixel moves when a draw
   below 4 gives 0, so two bits of the 64-bit per-site token chose the
   pixels. A flat fill moved one of four sets (1031, 998, 1085 or 982
   pixels of the probe's 4096, the only counts any report has shown), the
   same four in every browser with this code, and two sites shared a set
   in one session of four: two of the seven runs that compared two
   origins. A model of the hash (`berytest/noise.py`) reproduces the 982
   pixels the report lists, and Helium's file compiled alone gives the
   same four sets. `patches/privacy/beryllium-noise-hash-whole-token.patch`
   (build 0.20.3.17) finalizes the hash before each draw; the suite gains
   a test that the moved pixels are none of the four sets. *On the Intel
   node* (`renderD129`) the GPU process reports ANGLE on Mesa 26.2.2,
   "Intel(R) Graphics (ARL)", and then the browser process ends, about a
   second after every start: 21 errors and 2 failures of 38 tests, each a
   closed DevTools connection, and the report could not say why, because
   the suite never asked how the process ended. Tests that finished within
   that second passed, and so did the 30-second idle test, over a dead
   browser. The suite now puts the exit status or signal, the kernel's
   line and the telling lines of the log into every such error, starts a
   new browser for the next test, and fails a test whose browser died
   under it. The GPU page's device list, empty in both reports because the
   page keeps its tables in a shadow tree, is read through the shadow
   trees, so a report lists both GPUs and marks the active one. The cause
   on the Intel node is open until a run with this suite, or the browser
   started by hand with the switch, shows the log.
   **Then attestation** (next, build 0.20.3.17; 0.20.3.16 carries the
   thread names): the browser checks
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
