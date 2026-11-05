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
- `run --browser-arg=--enable-features=BerylliumCapsicumRenderer`: the whole
  suite with renderers in Capsicum capability mode (opt-in while the
  sandbox is being built, plan/14); `sandbox` shows each renderer's mode,
  the other groups show what still breaks. `,BerylliumCapsicumTrap` stops a
  renderer at its first refused call; processes in capability mode cannot
  write core dumps, so run the `capsicum` survey with the same switch to see
  which calls they are refused.
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
| `rendering` | canvas; WebGL in a window; WebGPU; the GPU process's report | `gpu-info.json` |
| `sandbox` | every process and whether the kernel has it in Capsicum capability mode (`procstat -s`); the GPU page's "Sandboxed" equals the kernel's answer (RT-17); renderers hold no directory or writable file, and their shared memory is anonymous with limited rights (`procstat -f`, `procstat -C`) | |
| `privacy` | a fresh browser left idle for 30 s, then showing a local page, contacts no outside host (a local proxy records and refuses every connection) | `privacy-*.txt` |
| `ui` | Settings > "Show home button" gives a Home button that is visible, drawn, enabled, has an icon and is not covered, in each of Helium's layouts (classic, centered address bar, minimal URL, narrow window, compact, vertical tabs, dynamic, zen mode); `--my-settings` adds a row with a copy of your own settings | `ui-home-button.txt`, `ui-toolbar-<layout>.txt`, `.json` |
| `youtube` | with `--network`: a video plays for 60 s without a crash or player error; records the codecs YouTube chose | `youtube-samples.json` |
| `stability` | eight animated tabs at once; quick navigation through internal pages | |

## Crashes

A tab that dies shows "Aw, Snap!" with an error code. On FreeBSD that code is
the signal that killed the page's process: 11 is SIGSEGV (a memory fault),
5 is SIGTRAP (a deliberate stop on a failed check). The tests report the code,
the end of the browser's log, and the kernel's record of the crash, which you
can also read yourself:

```sh
grep 'exited on signal' /var/log/messages | tail
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
