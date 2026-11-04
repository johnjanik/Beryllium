# Beryllium: Evaluation of the 2026 Capsicum Prototype

**Date:** 4 November 2026. **Answers:** [09-ROADMAP.md](09-ROADMAP.md)
section 4, Phase 2 item 0. **Decision for the owner:** diverge on
architecture, borrow the findings (section 4).

## 1. What was evaluated

Alex S's Capsicum sandbox for the FreeBSD Chromium port (FreeBSD bug
269234): branch `chromium-sandbox` of `shkhln/freebsd-ports`, two commits of
1 May 2026 on `www/chromium` 154.0.8037.57, "re-enable zygotes" (13 files)
and "add Capsicum sandbox" (8 files, 1,790 lines; `interceptors.cc` is
1,119). Branches `chromium-sandbox-147` to `-151` hold the same two commits
rebased onto Chromium 147 to 151, with byte-identical code: nothing has
changed in substance since 1 May. Read from the public repository; neither
the author nor Beryllium has built or run it against Beryllium's tree.

## 2. How it works

- **Zygote back on.** FreeBSD builds the Linux zygote again (plain `fork()`,
  no namespaces), so children inherit a Casper channel: the zygote forks a
  Casper `system.sysctl` service before confining anything and clones a
  channel into each child. Every renderer shares the zygote's address-space
  layout; the stack canary is re-randomised per child.
- **Lockdown point:** the end of `SandboxLinux::InitializeSandbox()`, the
  same point Beryllium chose: `caph_cache_catpages()`,
  `caph_cache_tzdata()`, `caph_limit_stdio()`, then `caph_enter_casper()`.
- **Confined:** renderer, GPU, video decode and encode, network, audio
  (PulseAudio, sndio), utility, print compositor. **Not confined:** the
  browser, the zygotes, Widevine, ALSA audio, and anything under
  `--no-sandbox`.
- **Interceptors:** 29 libc functions (`open`, `stat`, `access`, `connect`,
  `dlopen`, `sysctl`...) are replaced in the executable for every process;
  in a confined process they map absolute paths onto pre-opened directory
  descriptors and send `sysctl` reads to Casper. Renderers get four font
  directories, the XDG MIME cache and a sysctl channel (one list for all
  types: memory, `kern.version`, `kern.ipc.shmmax`, `hw.dri`,
  `kern.devname`, `net.routetable`).
- **Not addressed:** shared memory, Mojo, Wayland (`// TODO: Wayland`),
  `LOCAL_PEERCRED` (the browser trusts the zygote for child pids),
  status reporting (`GetStatus()` declared, never defined), descriptor
  audits, `closefrom`, `procctl` hardening.

## 3. Against Beryllium's design

| Beryllium rule | Prototype |
|---|---|
| No directory capabilities in renderers (06 section 3.2) | four font directories |
| No Casper channel in renderers (RT-14) | every child gets one; Casper runs unconfined |
| Committed descriptor allowlist, rights on every descriptor (06 sections 3.1 and 3.2) | rights only on what it pre-opens; inherited descriptors unlimited |
| Fail closed in production (06 section 3.4) | `ENOSYS` counts as success; no `cap_getmode` check; `--no-sandbox` honoured |
| Kernel-attested status (RT-04, RT-17) | none |
| Trace disable, no new privileges, fork and core limits (06 section 6) | none |
| Exec per child | zygote fork: shared address-space layout |

Where it is ahead: it confines GPU, network, audio and utility processes on
real hardware (NVIDIA, DRI, `/dev/pci` with an ioctl limit, Casper network
connect), and records pitfalls Beryllium has not hit yet.

## 4. Decision

**Diverge on architecture, borrow the findings.** Adopting it for renderers
would break RT-14 and plan/06 section 3.2, bring back a zygote whose main
job here is to hand out the Casper channel, and fail open; and "joint
maintenance" would mean rebasing 19 files of another design from Chromium
154 to 156. Borrowed:

- **Into the lockdown patch now**
  (`patches/security/beryllium-capsicum-renderer.patch`):
  `caph_cache_tzdata()` and `caph_cache_catpages()` in the warm-up;
  `dlopen("/lib/libgcc_s.so.1")` in the warm-up, because libthr loads it by
  path for unwinding when a thread exits, which a confined renderer cannot;
  `caph_limit_stdio()` before `cap_enter()`.
- **As a checklist, not a Casper policy:** its sysctl list. Beryllium
  caches what never changes (memory size, `kern.ipc.shmmax`, `uname()`);
  `hw.realmem`, available memory and `kern.proc.*` are checked against the
  survey's after-lockdown list.
- **Evidence for the next increments:** renderers open fontconfig files by
  path after start-up, and the XDG MIME cache; Beryllium's answer is a
  fuller font warm-up or the browser's FontService, with a read-only font
  directory only as a recorded exception.
- **Phase 3 inventories:** its GPU, audio and network rights sets and
  device lists, to start from (its read-write grant of whole profile
  directories to the network process needs review).

Not borrowed: the zygote, the interceptors, the Casper channel in
renderers, the `localtime_r` proxy bypass.

## 5. Known gap it confirms

Time zones on 14.x and 15.x: the Capsicum oracle (`misc.localtime_cached`
in `freebsd/results/oracle-14.5-*.json` and `oracle-15.1-*.json`) shows
libc local time falling back to UTC in capability mode there, with or
without caching the time-zone data first; on the owner's 16.0-CURRENT
machine `caph_cache_tzdata()` keeps it. The 14.5 and 15.1 results come from
CI virtual machines, which may have no local zone configured at all, so
this must be rechecked on a 14.x or 15.x machine with one before it counts
as a fact. Options: give
renderers local time from the browser (Chromium's Linux proxy, with the
deadlock the prototype hit as a known trap), or accept UTC in libc and rely
on ICU, which the browser keeps in sync. To decide before packages for 14.x
and 15.x carry the sandbox.

## 6. Coordination

Beryllium's findings that would help the prototype (the survey, the oracle
results, the memory and `uname()` crash paths, kernel attestation) can go
to bug 269234; per plan/09, messages to the FreeBSD tracker are written by
the maintainer personally.
