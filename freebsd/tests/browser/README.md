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

It prints a summary and writes everything to
`~/beryllium-test-results/<date-time>/`: `report.txt` (send this one),
`report.json`, the browser's log for each group (`*.stderr.log`), and the
files named below.

## Groups

| Group | Checks | Files |
|---|---|---|
| `startup` | starts; beryllium://version says Beryllium, not Helium; profile in `~/.config/beryllium`, nothing in Chromium's or Helium's folders | |
| `pages` | 20 internal pages load without a crash or error page, and none says "Helium" (except the credits) | |
| `media` | codec support (VP9, AV1, Opus, H.264, AAC); H.264, VP9 and AV1 clips play; AV1, VP9 and Opus through Media Source Extensions, the way YouTube streams | `media-codecs.json` |
| `rendering` | canvas; WebGL in a window; WebGPU; the GPU process's report | `gpu-info.json` |
| `sandbox` | every process and whether the kernel has it in Capsicum capability mode (`procstat -s`); the GPU page's "Sandboxed" equals the kernel's answer (RT-17) | |
| `privacy` | a fresh browser left idle for 30 s, then showing a local page, contacts no outside host (a local proxy records and refuses every connection) | `privacy-*.txt` |
| `ui` | Settings > "Show home button" gives a Home button that is visible, drawn, enabled, has an icon and is not covered | `ui-toolbar-*.txt`, `.json` |
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

## Validating the harness elsewhere

The suite also drives a stock Chromium, which is how CI keeps the harness
working: `run --scheme chrome --browser /path/to/chrome`. On a stock Chromium
the Beryllium-specific checks (names, profile folder, privacy) fail, as they
should.
