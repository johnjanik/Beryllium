# Findings in the FreeBSD `www/chromium` port, for its maintainers

## For the owner, before sending (this part is not the report)

This file is a draft for the maintainer of Beryllium to read, correct and
send. It was written with an AI assistant from the repository's records.
Nothing in it has been sent anywhere.

**What it is based on.** The port's patch set as imported on 1 November
2026: ports commit `6ad3e0c82d8b`, `www/chromium 156.0.8078.47_1`, 1696
patches (`freebsd/ports/www/beryllium/files/IMPORTED-FROM`). Each
finding below says whether it was seen on the stock package or on a
Beryllium build that carries the same port code.

**Checked against the port as it is now.** On 12 November 2026 the port
was at `156.0.8078.79_1`. The seven patch files this report names were
fetched from `cgit.freebsd.org` and compared byte for byte with the
imported copies: all seven are identical. The port still has no patch to
`base/process/launch_posix.cc` (finding 3). The manual page lines of its
`Makefile` and Chromium 156's template were read for finding 7. That is
reading, not running: nothing was installed or run from the current
port.

**Check before sending.**

1. Install the current `www/chromium` package and repeat the checks
   marked *stock* (findings 1 and 2), and try the ones marked *derived*
   (3 to 7) on it. Each has a command. A finding the current port no
   longer shows comes out.
2. Look again at the current port's copy of each patch file named below
   (`https://cgit.freebsd.org/ports/tree/www/chromium/files/`) on the
   day you send, in case one has changed since 12 November.
3. Search FreeBSD's Bugzilla for an existing report of each.
4. Finding 1 says no backtrace is attached. One would help: start the
   stock browser from a terminal with core dumps enabled, play a video,
   and take the renderer's backtrace with `lldb -c`.

**How FreeBSD takes reports.** Port bugs go to
<https://bugs.freebsd.org/bugzilla/>, product "Ports & Packages",
component "Individual Port(s)", with the summary starting
`www/chromium:`. They are assigned to `chromium@FreeBSD.org`. The custom
is one report per defect, so each numbered finding below is written to
stand alone, with a summary line to use.

**FreeBSD and AI assistance.** As far as could be found on 12 November
2026, FreeBSD has no adopted policy. Its Core Team reported in 2025 that
it was working on one, that the project tends not to use such tools to
generate code because of licence concerns, and that they can be useful
for tracking down bugs and understanding large code bases. That fits a
bug report and does not fit offering code. So this draft describes each
fix in words and offers no patch. Check the FreeBSD Contributors Guide
for a policy adopted since, and say in the report that an AI assistant
was used; a sentence for that is at the end.

**Licence.** Beryllium's patches are GPL-3.0. The port is not. The
maintainers cannot take those patches as they are, which is a second
reason to describe fixes instead of sending them. If you want to offer a
fix as code, it is yours to offer under terms they can use.

**What was left out, and why.**

- Things that are Helium's or Beryllium's own, not the port's.
- The port having no sandbox at all. It is known, and it is what
  Beryllium is building; findings 2, 5 and 8 are the parts of it that
  are defects in what is there.
- Shared memory regions as unlinked files in the temporary directory,
  and the allocator hardening options being off. Both are the port's
  choices with reasons behind them. They are worth a conversation, not a
  bug report.
- The user-agent paths that may still say FreeBSD: read from the source
  only, and the repository's own notes disagree about them.

---

## The report

### Where these come from

Beryllium is a Chromium derivative for FreeBSD built from the
`www/chromium` port's patch set (imported at ports commit
`6ad3e0c82d8b`, `www/chromium 156.0.8078.47_1`) with further patches on
top. Building it and testing it turned up the following in the port's
own patches. They are reported here because they affect, or would
affect, users of `www/chromium`.

Test machine: FreeBSD 16.0-CURRENT (`main-n290153-617c700abae7`), amd64,
NVIDIA GeForce RTX 5090 Laptop GPU with driver 595.99.02, KDE Plasma on
Wayland, `fdescfs` not mounted. "Stock" below means the `chromium`
package 156.0.8078.47 from the FreeBSD repository on that machine.
"Derived build" means Beryllium built from that port's patches for
Chromium 156.0.8078.79.

Findings 1 and 2 were seen on the stock package. Findings 3 to 6 were
measured on derived builds and are in code the port leaves as it is, so
they should show on the stock package too; that has not been measured.
Finding 7 was seen on a derived build and read in the port's `Makefile`.
Finding 8 and the notes after it are read from the source.

The port's patch files named below were compared with the port at
`156.0.8078.79_1` on 12 November 2026 and are unchanged.

### 1. Every video crashes its tab with the NVIDIA driver on Wayland

*Suggested summary:* `www/chromium: video playback crashes the renderer (SIGSEGV) with NVIDIA on Wayland; --disable-gpu-memory-buffer-video-frames avoids it`

*Seen on:* the stock package and derived builds.

Any video ends the tab with "Error code 11" as soon as playback begins:
H.264, VP9 and AV1, as files and through Media Source, on YouTube and on
local files. Audio alone plays.

A test replayed four clips under switches that each turn one part of the
video path off. On 3 November 2026 the stock browser and the derived
build gave the same table (two runs; the reports of that day did not
record which binary each was):

```text
switches                                h264_aac.mp4       mse_vp9.webm       mse_av1.mp4        mse_opus.webm
as normally run                         CRASH (code 11)    CRASH (code 11)    CRASH (code 11)    plays
one decode thread (--video-threads=1)   CRASH (code 11)    CRASH (code 11)    CRASH (code 11)    plays
no GPU at all (--disable-gpu)           plays (51 frames)  plays (49 frames)  plays (49 frames)  plays
no hardware video decode                CRASH (code 11)    CRASH (code 11)    CRASH (code 11)    plays
no GPU memory buffers for video frames  plays (51 frames)  plays (49 frames)  plays (50 frames)  plays
no VA-API decoders                      CRASH (code 11)    CRASH (code 11)    CRASH (code 11)    plays
software GL (SwiftShader)               plays (51 frames)  plays (49 frames)  plays (49 frames)  plays
X11 instead of Wayland                  plays (52 frames)  plays (49 frames)  plays (50 frames)  plays
headless                                plays (52 frames)  plays (49 frames)  plays (50 frames)  plays
```

So the renderer faults while writing decoded frames into GPU memory
buffers, which the NVIDIA driver allocates and the renderer maps. The
port enables that path on BSD in
`files/patch-media_gfx_mappable__shared__image__video__frame__pool.cc`
(`|| BUILDFLAG(IS_BSD)`). Hardware decode, VA-API and the number of
decode threads make no difference.

On 12 November 2026 a derived build that keeps frames out of GPU memory
buffers on NVIDIA played every clip under every switch, and crashed the
three video clips again when the path was forced back on
(`--enable-gpu-memory-buffer-video-frames`).

*To check:* on NVIDIA and Wayland, play any video; then start the
browser with `--disable-gpu-memory-buffer-video-frames` and play it
again.

*Not established:* whether the fault is in the driver or in how the port
uses it. No backtrace is attached. Other GPU drivers were not tried.

*What Beryllium does:* on FreeBSD, when the GL vendor string names
NVIDIA, the renderer copies frames through shared memory, as with the
switch above. A workaround for users of the port today is that switch.

### 2. `chrome://gpu` says "Sandboxed: true" and no process is confined

*Suggested summary:* `www/chromium: chrome://gpu reports "Sandboxed: true" though no process is sandboxed on FreeBSD`

*Seen on:* the stock package.

On the stock package, 1 November 2026, `chrome://gpu` shows:

```text
Sandboxed                       : true
```

and `procstat -s` shows no process of the browser in capability mode:
not the browser, the GPU process, the network, storage or audio
services, nor any renderer.

The cause is in `files/patch-sandbox_policy_freebsd_sandbox__freebsd.cc`.
`SandboxLinux::InitializeSandbox()` there lowers a resource limit, runs
the pre-sandbox hook and ends with `return true;`. It confines nothing.
The GPU process reports that return value as its sandbox status.

A status page that claims a sandbox misleads users and anyone reviewing
the port.

*To check:* open `chrome://gpu` and read "Sandboxed"; then, with the
browser running:

```sh
procstat -s $(pgrep -f -- --type=gpu-process)
```

A `C` in the flags column would mean capability mode. There is none.

*What Beryllium does:* the GPU process reports itself sandboxed only if
`cap_getmode(2)` says it is in capability mode.

### 3. Child processes inherit every descriptor the browser has open

*Suggested summary:* `www/chromium: child processes keep all of the browser's open descriptors when fdescfs is not mounted`

*Seen on:* a derived build. Not measured on the stock package.

`base::LaunchProcess()` closes what a child does not need by listing
`/dev/fd` (`CloseSuperfluousFds` in `base/process/launch_posix.cc`).
Without `fdescfs` mounted, `/dev/fd` on FreeBSD lists only 0, 1 and 2,
so nothing is closed. The port has no patch to that file.

Measured on 4 November 2026: a renderer held about 120 descriptors
inherited from the browser. Among them were the directories `/`, `/usr`,
`/usr/local` and `/usr/local/etc`, writable profile databases (Sync
Data, Local Storage, the GPU caches), log files and the DRM device. With
the children closing what they were not given, a renderer holds about
30, and no directory or profile file.

Today this hands every child process, renderers included, descriptors it
was never meant to have. For any future sandbox it decides the matter: a
process in capability mode that holds a descriptor for `/` can still
open everything beneath it.

*To check:* with `mount -t fdescfs` showing nothing, and the browser
running:

```sh
procstat -f $(pgrep -f -- --type=renderer | head -1)
```

Look for directories and for files under the profile.

*What Beryllium does:* between fork and exec the child keeps 0 to 2 and
the descriptors the launcher remapped for it, and closes the rest with
`close()` and `closefrom(2)`. That is what Chromium does on Linux through
`/proc/self/fd`.

### 4. Thread names never reach the kernel

*Suggested summary:* `www/chromium: PlatformThread::SetName() does not name the thread for the kernel; procstat -t, top -H and debuggers show the process name for every thread`

*Seen on:* a derived build. Not measured on the stock package.

`files/patch-base_threading_platform__thread__bsd.cc` gives:

```cpp
void PlatformThreadBase::SetName(const std::string& name) {
  SetNameCommon(name);
}
```

Nothing tells the kernel. `procstat -t`, `top -H`, a debugger's thread
list and core files show the process name for every thread. A derived
build of 10 November 2026 logged the kernel's names for a renderer's two
threads as the process name twice. After adding a call to
`pthread_set_name_np()` the same log reads `CrRendererMain`.

*To check:*

```sh
procstat -t $(pgrep -f -- --type=renderer | head -1)
```

*What Beryllium does:* `SetName()` also calls `pthread_set_name_np()`,
for the main thread too. The kernel keeps the first 19 bytes.

### 5. The deferral of startup tracing is in a function FreeBSD never runs

*Suggested summary:* `www/chromium: IS_BSD added to the tracing deferral in RunZygote(), which is not used on FreeBSD; children start the tracing thread before the sandbox point`

*Seen on:* derived builds. Without a sandbox it changes nothing a user
sees, so this matters to whoever adds one.

`files/patch-content_app_content__main__runner__impl.cc` adds
`|| BUILDFLAG(IS_BSD)` to the block in `RunZygote()` that delays the
tracing thread until after the sandbox. FreeBSD does not use the zygote,
so that block never runs. `ContentMainRunnerImpl::Run()`, which does
run, was left as it is, and its other branch starts tracing at once in
every child.

Measured: derived builds of 10 November 2026 found two threads in every
renderer at the point where Chromium initialises its sandbox. With the
deferral moved to `Run()` for renderers, there is one, confirmed with
`lldb`. Chromium's own comment at that place says an early tracing
thread is incompatible with platforms whose sandbox must be set up with
one thread.

*What Beryllium does:* FreeBSD gets its own branch in `Run()`; a
renderer defers tracing as on Linux.

### 6. A warning is logged for every frame on Wayland

*Suggested summary:* `www/chromium: "kSyncobj is not supported!" is logged for every frame on Wayland, also in the implicit-sync branch`

*Seen on:* a derived build. Not measured on the stock package.

`files/patch-ui_ozone_platform_wayland_host_wayland__frame__manager.cc`
adds the same line in two places: under `SyncMethod::kSyncobj`, and
under `kDMAFence` and `kImplicit`:

```cpp
LOG(WARNING) << "WaylandBufferHandle::SyncMethod::kSyncobj is not supported!";
```

The second names the wrong method, and both run once a frame. One test
run of a derived build wrote that line 6469 times and nothing else at
that level. It hides whatever else the log would say.

*To check:* start the browser from a terminal on Wayland and count the
lines.

### 7. The installed manual page keeps Chromium's placeholders

*Suggested summary:* `www/chromium: chrome.1 is installed with @@PACKAGE and @@MENUNAME unreplaced`

*Seen on:* a derived build that installed the page the same way; read in
the port's `Makefile` as of 12 November 2026.

The port installs `chrome/app/resources/manpage.1.in` as `chrome.1` and
then runs:

```make
@${SED} -i "" -e 's,\@\@PACKAGE\@\@,chromium,g;s,\@\@MENUNAME\@\@,Chromium Web Browser,g' \
```

Chromium's template no longer closes its placeholders with `@@`. In
156.0.8078.79 it reads:

```text
.TH @@PACKAGE 1 "" "" "USER COMMANDS"
@@PACKAGE \- the web browser from Google
```

So nothing is replaced, and `man chrome` opens with "@@PACKAGE - the web
browser from Google".

*To check:* `man chrome` on a machine with the package.

*Fix:* match `@@PACKAGE` and `@@MENUNAME` without the closing pair.

### 8. A question: the network service sandbox is on by default on BSD

`files/patch-sandbox_policy_features.cc` turns `kNetworkServiceSandbox`
on by default for every BSD:

```cpp
#if BUILDFLAG(IS_BSD)
BASE_FEATURE(kNetworkServiceSandbox, base::FEATURE_ENABLED_BY_DEFAULT);
```

On OpenBSD there is a sandbox behind it. On FreeBSD nothing enforces
one: the network service opens its cache by path and makes its own
connections. Chromium then treats the network service as sandboxed. What
the browser does differently for a sandboxed network service has not
been read through, so this is a question and not a finding: should the
default be OpenBSD's only?

### Smaller things

- `files/patch-sandbox_policy_freebsd_sandbox__freebsd.h` is the OpenBSD
  header: its guard is `SANDBOX_POLICY_LINUX_SANDBOX_OPENBSD_H_`, and it
  declares `SetPledge()`, `SetUnveil()` and `GetStatus()`, which nothing
  defines on FreeBSD.
- On the stock package `chrome://gpu` shows the GPU as
  `VENDOR= 0x0000, DEVICE=0x0000`. Chromium's GPU blocklist and driver
  workarounds are keyed on those numbers, so none can match. Why the
  identification fails has not been found.
- Read from the source and not looked at in a running browser:
  `chrome://sandbox` is registered on BSD, and the code that fills it is
  built for Linux and ChromeOS only.

### How this was found

These came out of building a derived browser and testing it with a suite
that compares what the browser says with what the kernel says
(`procstat`, `ktrace`). The work was done with the help of an AI
assistant; the tests were run, and the results read, by a person on the
machine described above. The fixes mentioned are in a public repository
under the GPL and are described here, not offered as patches.

---

## Evidence in this repository

| Finding | Where |
|---|---|
| The imported port revision | `freebsd/ports/www/beryllium/files/IMPORTED-FROM` |
| 1 | `patches/platform/beryllium-bsd-nvidia-video-frames.patch` (header); `freebsd/tests/browser/tests/test_35_videodiag.py`; `plan/12-WORK-PLAN-AND-RED-TEAM.md` section 11; `plan/14-RENDERER-SANDBOX.md` (runs of 12 November 2026) |
| 2 | `freebsd/results/chrome-gpu-16.0-CURRENT-20261101.txt`; `freebsd/results/baseline-16.0-CURRENT-20261101.md`; `patches/security/beryllium-honest-gpu-sandbox-status.patch` |
| 3 | `patches/security/beryllium-close-inherited-descriptors.patch` (header); `plan/14-RENDERER-SANDBOX.md` |
| 4 | `patches/platform/beryllium-bsd-kernel-thread-names.patch` |
| 5 | `patches/security/beryllium-renderer-tracing-after-lockdown.patch`; `plan/14-RENDERER-SANDBOX.md` |
| 6 | `freebsd/tests/browser/README.md`; `plan/14-RENDERER-SANDBOX.md` |
| 7 | `plan/17-DOCUMENTATION.md` |
| 8 and the smaller things | `plan/18-REMAINING-WORK.md` sections 2.1, 4.2 and 7.1; `plan/02-BASELINE-FINDINGS.md` |

The port's patch files named in the report are under
`freebsd/ports/www/beryllium/files/`, as imported.
