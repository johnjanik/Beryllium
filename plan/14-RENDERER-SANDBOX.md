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
- **Renderers never call it.** On FreeBSD a renderer runs `PreSandboxInit()`
  (`content/app/content_main_runner_impl.cc`: system values, BoringSSL,
  rust_png CPU features, WebRTC, WebNN), then `RendererMain()` calls
  `RendererMainPlatformDelegate::EnableSandbox()`, which the FreeBSD patch
  reduces to `return true`. Only the browser (as "no sandbox"), the GPU
  process (`StartSandboxLinux` in `content/gpu/gpu_main.cc`) and utility
  processes (`sandbox::policy::Sandbox::Initialize`) reach
  `InitializeSandbox()`. So renderers do not even get the `RLIMIT_DATA`
  limit the others get.
- There is no zygote on FreeBSD: each renderer is launched from the
  browser, inherits its Mojo channel as a descriptor, and initialises Mojo
  after `EnableSandbox()`.

## 2. The lockdown point

`RendererMainPlatformDelegate::EnableSandbox()`
(`content/renderer/renderer_main_platform_delegate_linux.cc`). It runs:

- after `PreSandboxInit()`, so the existing warm-up has happened;
- before `RenderProcessImpl` and `RenderThreadImpl` exist, so before any
  page content is handled and before most threads start;
- with the Mojo channel already an inherited socket descriptor, which keeps
  working in capability mode (`sendmsg`/`recvmsg` with `SCM_RIGHTS` are
  allowed).

Beryllium's change calls into `sandbox_freebsd.cc` from there for
`kRenderer`: finish the warm-up, limit and close descriptors, harden
(`procctl`), `cap_enter`, check `cap_getmode`, log one line, and on failure
end the process in a production build.

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
2. **Opt-in lockdown** (next build): the code in section 2, enabled only by
   a Beryllium switch, so daily use is unaffected while it is tested; plus a
   diagnostic mode that sets `PROC_TRAPCAP_CTL`, so the first refused call
   ends the renderer with a backtrace instead of failing quietly. Warm-up
   moves are taken from the survey, starting with the known ones:
   `vm.stats.vm.v_page_count` (the 2023 attempt's first failure), time-zone
   data, fonts.
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
