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
3. **Descriptor hygiene and allowlist:** `closefrom` in the launcher, the
   committed renderer allowlist from the survey, rights limits per
   descriptor, environment allowlist.
4. **Shared memory without a namespace:** `memfd_create` with seals for
   regions renderers create.
5. **Attestation and status:** the browser checks each renderer's
   capability mode with the kernel and refuses an unconfined one;
   `beryllium://sandbox` shows the kernel's answer; the release's sandbox
   table changes from "not confined".
6. **Default on, fail closed** in the production package; the devel package
   keeps the switch.

## 4. Open items

- **Prototype evaluation (plan/09 Phase 2 item 0).** Alex S's
  `chromium-sandbox` branch (`shkhln/freebsd-ports`, FreeBSD bug 269234)
  has not been read: attaching that repository to the cloud session was
  refused by the session's permission check on 4 November 2026. The owner
  can allow it, or read it on the FreeBSD machine. Its sysctl and time-zone
  findings and its known gaps should feed increment 2.
- **Kernel facts** come from the Capsicum oracle results in
  `freebsd/results/` (126 sysctls readable in capability mode on
  16.0-CURRENT); the survey marks each sysctl a process reads against that
  list.
