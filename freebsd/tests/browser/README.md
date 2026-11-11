# Beryllium browser test suite

Runs the installed Beryllium against local test pages and media and checks
what a user would notice: that it starts and names itself correctly, that
pages and media work without crashes, that it stays quiet on the network,
that its toolbar behaves, and that it tells the truth about its sandbox.

Every run uses throwaway profiles in a temporary home directory; your own
profile is never opened. Python 3 standard library only; the browser is
driven over the DevTools pipe (`--remote-debugging-pipe`), its own window
layout over UI DevTools (`--enable-ui-devtools`).

## Run it

As your normal user, in your desktop session (windows open and close while
it runs):

```sh
freebsd/tests/browser/run
```

For the media tests, install ffmpeg first (`doas pkg install ffmpeg`); without
it they are skipped. Useful options:

- `run media` or `run pages ui`: only some groups (below).
- `run --network`: also the live YouTube test (`--watch 120` to watch longer,
  `--youtube-video ID` for another video).
- `run --headless`: no windows; the toolbar test is skipped.
- `run --list`: list every test with its description.
- `run --keep-profiles`: keep the throwaway profiles for inspection.
- `run capsicum --diagnose`: run the browser under `ktrace` and record, per
  process type, every system call, path lookup and sysctl that Capsicum
  capability mode would refuse, across a set of workloads (text with CJK and
  emoji, images, WebGL, WebAssembly, workers, a service worker, storage, a
  form, a PDF, video, printing), with each process's descriptors,
  environment variable names (not values) and limits
  (`capsicum-survey.txt`). Builds from 0.20.3.3 mark each renderer's
  lockdown point, and the report then separates what happens before it
  (start-up) from what happens after (must work in capability mode).
  Nothing is confined while it runs. Descriptors and environment need
  `security.bsd.unprivileged_proc_debug=1` (the default) during the run.
- `run --lockdown` (short for
  `--browser-arg=--enable-features=BerylliumCapsicumRenderer`): the whole
  suite with renderers in Capsicum capability mode (opt-in while the
  sandbox is being built, plan/14); `sandbox` shows each renderer's mode,
  the other groups show what still breaks. With that switch the `sandbox`
  group is a gate, not a survey: it fails if any renderer is not in
  capability mode by the kernel's answer, if any renderer's descriptors or
  rights cannot be read (`security.bsd.unprivileged_proc_debug=1` is
  needed), or if any descriptor is outside the policy. Without the switch
  it records what it sees and skips what it cannot observe.
  `,BerylliumCapsicumTrap` stops a renderer at its first refused call;
  processes in capability mode cannot write core dumps, so run the
  `capsicum` survey with the same switch to see which calls they are
  refused.
- `run media videodiag --diagnose`: replay video under switches that each
  turn off one part of the video path (GPU, hardware decode, decode
  threads, Wayland...) and record which avoid a crash
  (`video-diagnosis.txt`).
- `run ui --my-settings`: also check the toolbar with a copy of your own
  settings (`Local State` and `Default/Preferences` from
  `~/.config/beryllium`, copied into a throwaway profile; history, cookies
  and passwords are in other files and are not copied).
- `run --cores`: let crashing processes write core dumps and put `lldb`
  backtraces in the report (`backtrace-*.txt`). It runs the browser binary
  directly, because the launcher turns core dumps off.

It prints a summary and writes everything to
`~/beryllium-test-results/<date-time>/`: `report.txt` (send this one),
`report.json`, the browser's log for each group (`*.stderr.log`), and the
files named below.

## Groups

| Group | Checks | Files |
|---|---|---|
| `startup` | starts; beryllium://version says Beryllium, not Helium; profile in `~/.config/beryllium`, nothing in Chromium's or Helium's folders | |
| `pages` | 20 internal pages load without a crash or error page, and none says "Helium" (except the credits) | |
| `videodiag` | with `--diagnose`: video playback under ten switch sets, as a table (the last forces the GPU memory buffer path Beryllium turns off with NVIDIA) | `video-diagnosis.txt` |
| `media` | codec support (VP9, AV1, Opus, H.264, AAC); H.264, VP9 and AV1 clips play; AV1, VP9 and Opus through Media Source Extensions, the way YouTube streams | `media-codecs.json` |
| `capsicum` | with `--diagnose`: what capability mode would refuse, per process type, and each process's descriptors with their Capsicum rights (the input to the renderer sandbox) | `capsicum-survey.txt`, `.json`, `capsicum-kdump.txt.gz` |
| `rendering` | with Helium's canvas noise switched off (`--disable-features=HeliumNoiseCanvas`), every grey and a set of colours read back from a canvas as drawn, on a CPU canvas and the default one, by fill and by putImageData (what moves, in which channel, how far apart; when something moves, the same probe runs again with the display profile forced to sRGB, with the GPU off and with Skia's baseline CPU code); WebGL in a window; WebGPU; the GPU process's report, and from the GPU page the DRM render node in use and whether the run named it or the browser chose it, every GPU (the one in use marked `*ACTIVE*`) and the displays' colour information | `gpu-info.json` |
| `fonts` | text in eleven scripts (Latin, Greek, Cyrillic, Chinese, Japanese, Korean, Arabic, Hebrew, Devanagari, Thai, emoji) is drawn with a font that has its glyphs, by fontconfig's own account (`fc-list` by charset), so a script that would show as boxes or blanks fails and the test names the package that brings a font for it; and each script is set in the same platform fonts by a renderer in capability mode as by one that is not: two browsers, the lockdown switched on and off explicitly | |
| `sandbox` | every process and whether the kernel has it in Capsicum capability mode (`procstat -s`; a renderer the browser has just launched gets five seconds to reach its lockdown point); the GPU page's "Sandboxed" equals the kernel's answer (RT-17); renderers hold no directory or writable file, their shared memory is anonymous with limited rights, and with the lockdown on every renderer descriptor has an allowed type and no more rights than the policy gives it (`procstat -f`, `procstat -C`; a socket outside the policy is named by the process holding its other end, from `fstat`), and the browser log shows no received descriptor the policy refused, a single thread at each lockdown, and the browser cutting what it sent each renderer; and which threads a renderer has at its lockdown point, from their stacks: a renderer paused by `--renderer-startup-dialog` is run on to the lockdown under `lldb`, and each thread is listed with what it waits in and where it was started (a record; needs `lldb`, which FreeBSD's base system has) | `threads-at-lockdown.txt` |
| `privacy` | a fresh browser left idle for 30 s, then showing a local page, contacts no outside host, as seen by a local proxy that records and refuses every connection: HTTP(S) the browser sends through the proxy it was given, not DNS, UDP (QUIC) or anything that bypasses a proxy; Helium's canvas noise is there by default (a flat fill reads back with about one pixel in four one level off in one channel, the same twice, differently on another origin), the moved pixels are none of the four sets that the noise hash before 0.20.3.17 chose from by two bits of the site's token, and the noise is gone with the feature off | `privacy-*.txt` |
| `ui` | Settings > "Show home button" gives a Home button that is visible, drawn, enabled, has an icon and is not covered, in each of Helium's layouts (classic, centered address bar, minimal URL, narrow window, compact, vertical tabs, dynamic, zen mode); `--my-settings` adds a row with a copy of your own settings | `ui-home-button.txt`, `ui-toolbar-<layout>.txt`, `.json` |
| `youtube` | with `--network`: a video plays for 60 s without a crash or player error; records the codecs YouTube chose. When it does not play, the report gives YouTube's own answer for the video (its playability status), the player's error fields, the requests that failed and the responses with an error status, by host (`net::ERR_BLOCKED_BY_CLIENT` is the content blocker), and the console errors. A session YouTube refuses outright (it asks a new profile driven over DevTools to sign in, for one) is skipped, since that says nothing about the browser. YouTube's streaming server also ends a session it will not attest after a while, with "Something went wrong" and error code `ump.spsrejectfailure` (after about 45 s on 0.20.3.17, while the same video played on in an ordinary session): playback is judged up to that point, and the rejection is noted | `youtube-samples.json` |
| `stability` | eight animated tabs at once; quick navigation through internal pages; a renderer showing a static page uses almost no CPU over five seconds | |

## Crashes

A tab that dies shows "Aw, Snap!" with an error code. On FreeBSD that code is
the signal that killed the page's process: 11 is SIGSEGV (a memory fault),
5 is SIGTRAP (a deliberate stop on a failed check). The tests report the code,
the end of the browser's log, and the kernel's record of the crash, which you
can also read yourself:

```sh
grep 'exited on signal' /var/log/messages | tail
```

When the browser process itself ends under a test (a crash, a fatal error, or
an exit), every command to it fails with "browser connection closed". The
error then says how the process ended (its exit status, or the signal that
killed it), gives the kernel's line about it and the lines of its log that
say something about a failure, and names the log file in the results
directory. The next test of the class gets a new browser with a log of its
own (`<Class>-2.stderr.log`, and so on), and a test that would have passed
over a dead browser, such as the idle privacy test, fails instead.

Where the cause of a death is known from an earlier report, the error names
it. So far that is one: `importing the supplied dmabufs failed`, the Wayland
compositor refusing a buffer from a GPU it cannot take buffers from, which is
what `--render-node-override` naming the wrong GPU produces (signal 5).

One line fills these logs on Wayland and means nothing: `WaylandBufferHandle::
SyncMethod::kSyncobj is not supported!`. The FreeBSD port's patch to
Chromium's `wayland_frame_manager.cc` writes it as a warning for every frame
shown, with any GPU (6469 times in one run of 0.20.3.16). The suite leaves it
out of its excerpts; when reading a log yourself, filter it:

```sh
grep -v kSyncobj ~/beryllium-test-results/<run>/Startup.stderr.log | tail -30
```

## Getting a backtrace

Core dumps go to `kern.corefile` (default `%N.core` in the crashing
process's directory). Point it somewhere writable for the run, then put it
back:

```sh
doas sysctl kern.corefile=/var/tmp/%N.%P.core
```

```sh
freebsd/tests/browser/run media --cores
```

The backtraces are in the results directory. The cores themselves can be
large; delete them afterwards (`doas rm /var/tmp/beryllium.*.core`) and
restore the setting (`doas sysctl kern.corefile=%N.core`).

## Internal pages and beryllium://

The tests open internal pages as `chrome://`. Beryllium shows them as
`beryllium://` and maps that back to `chrome://` in the browser's own
navigation (address bar, bookmarks, menus, new tabs), which DevTools'
`Page.navigate` does not go through (it returns `ERR_ABORTED` for
`beryllium://`). The `startup` group checks `beryllium://version` through
the new-tab path instead.

## Validating the harness elsewhere

The suite also drives a stock Chromium, which is how CI keeps the harness
working: `run --scheme chrome --browser /path/to/chrome`. On a stock Chromium
the Beryllium-specific checks (names, profile folder, privacy) fail, as they
should.
