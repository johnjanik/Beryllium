<div align="center">
    <picture>
        <source media="(prefers-color-scheme: dark)"
            srcset="artwork/wordmark/beryllium-wordmark-on-dark.svg" />
        <img src="artwork/wordmark/beryllium-wordmark-on-light.svg"
            title="Beryllium Browser" alt="Beryllium Browser" width="420" />
    </picture>
    <p>
        A privacy-focused browser for FreeBSD.
        <br>
        Built natively, to be confined with FreeBSD's own security primitives.
    </p>
</div>

Beryllium is a Chromium-based browser built from source as a native FreeBSD
application and installed as an ordinary `pkg` package. Its privacy patch
set is derived from the GPL-3.0 code of the Helium browser. Its goal is to
give Chromium on FreeBSD the process sandbox it lacks today, built on
Capsicum. Beryllium is an independent project; see
[Origin and independence](#origin-and-independence).

## Status

> [!WARNING]
> **Development build, no sandbox yet.** Beryllium works for everyday
> browsing, but by default no Beryllium process is confined: like the
> stock FreeBSD Chromium, a compromised web page has the same access to
> your files and network as you do. `beryllium://gpu` says so
> ("Sandboxed: false"). An experimental renderer lockdown can be switched
> on ([below](#experimental-renderer-lockdown)); it is not yet a complete
> sandbox. Do not rely on Beryllium to contain an attack yet.

Current release: **Beryllium 0.20.3.12**, based on Chromium 156.0.8078.79
and Helium 0.20.3.

- **Packages:** FreeBSD 16.0-CURRENT, amd64. Other FreeBSD versions: build from source (below).
- **Checked on:** FreeBSD 16.0-CURRENT, NVIDIA GeForce RTX 5090 Laptop GPU (driver 595.99.02), KDE Plasma on Wayland.
- **Works:** browsing; video playback, including YouTube; WebGL; the toolbar in all of Helium's layouts; Beryllium's own name, logo and icons, `beryllium://` pages and profile folder.
- **Privacy check:** a fresh browser, idle and showing a local page, contacts no outside server; online services are off in a new profile, and even when switched on, with consent given, they contact nothing until a server is entered (test suite, `privacy` group).
- **Not yet:** a sandbox on by default; WebGPU (no adapter is found).

### New in 0.20.3.12 (since 0.20.3.7)

Everything in this release is about the renderer lockdown and about being
able to check it. Nothing changes for everyday browsing unless you switch
the lockdown on.

- **Least rights on every descriptor.** With the lockdown on, every file,
  socket, kqueue, eventfd and shared memory object a renderer holds is
  cut to the rights its kind needs, with Capsicum: at the lockdown point
  for what the renderer already has, at creation for what it makes
  afterwards (the message pump's kqueue and eventfd, shared memory), and
  on arrival for what the browser passes it over Mojo.
- **Admission by place and shape.** At the lockdown a read-only file is
  accepted only under `/usr/local/share/beryllium/` (the browser's own
  resources); a socket only as an unnamed Mojo socket pair, bound and
  connected to no path; a directory is closed; anything else ends the
  renderer instead of running unconfined. A failure to limit the standard
  streams ends it too. These came out of an external adversarial review of
  the code ([plan/16](plan/16-ADVERSARIAL-REVIEW-2026-11-07.md)), which
  also found that the test suite could pass with no renderer confined.
- **The sandbox tests are a gate.** Run with the lockdown switched on, the
  suite fails if any renderer is not in capability mode by the kernel's
  answer, if its descriptors cannot be read, if any descriptor is outside
  the policy, or if the lockdown's own log shows a refused descriptor.
  Without the switch it surveys and skips, as before.
- **Release provenance.** Every package carries a build manifest (version,
  Chromium and Helium versions, the imported FreeBSD patch set, the SHA-256
  of every Beryllium patch). The release tool refuses a package that was
  not built from the commit it names, and publishes the manifest with the
  release as `BUILD-MANIFEST-FreeBSD-16-amd64.json`.
- **No renderer spins on its kqueue.** 0.20.3.8 withheld one right from
  the message pump's kqueue and every confined renderer polled instead of
  sleeping; a test now watches idle CPU.

### New since 0.20.3.1 (releases 0.20.3.2 to 0.20.3.7)

- **New logo and icons.** The logo is rebuilt as vector artwork from the
  same design, and the 16, 22, 24 and 32 px icons are drawn pixel by pixel
  so they stay sharp in panels and menus.
- **Online services off by default.** No server is built in, and nothing
  is sent to Helium's servers unless you enter their address yourself (see
  [Using Beryllium](#using-beryllium)).
- **Beryllium's name throughout.** The flags page and the services
  settings say Beryllium instead of Helium.
- **Child processes start clean.** Chromium's launcher on FreeBSD closed
  nothing, so every child process inherited the browser's open files and
  directories, including `/` and the profile databases. Each child now
  keeps only what is passed to it on purpose: about 30 descriptors in a
  renderer instead of about 120.
- **Shared memory without files.** Chromium kept the memory its processes
  share as deleted files in `/tmp`, so page content could reach the disk
  and any process holding one could rewrite or resize it. It is now
  anonymous memory, sealed against resizing, and read-only where it should
  be, enforced by Capsicum rights.
- **No page data in `/tmp`.** Chromium gives each renderer a file in
  `/tmp`, deleted as soon as it is created, where the renderer stores
  compressed page data, such as the scripts of tabs that have been in the
  background for a while. Beryllium hands out no such file: that data
  stays compressed in memory, as Chromium already does in Incognito
  windows. `--enable-features=BerylliumRendererSwapFile` brings the file
  back.
- **Experimental renderer lockdown**, off by default (below).

### Sandbox status of this release

Each release states what is enforced, so you can check it yourself with
`procstat -s` (a `C` in the flags column means Capsicum capability mode).

| Process | Status |
|---|---|
| Browser | not confined |
| Renderers (web pages) | not confined by default; experimental lockdown below |
| GPU | not confined (reported honestly at `beryllium://gpu`) |
| Network, audio, other utilities | not confined |

In every process, inherited descriptors are closed at launch, and shared
memory is anonymous, with its size sealed and read-only regions enforced
by Capsicum rights. These limit what a compromised process can reach, but
they do not confine it.

#### Experimental renderer lockdown

Start Beryllium with

```sh
beryllium --enable-features=BerylliumCapsicumRenderer
```

and every renderer enters Capsicum capability mode before it handles a
web page: it can no longer open files by path, open new network
connections or signal other processes, and it holds no directory and no
writable file.
If the lockdown fails, the renderer ends instead of running unconfined. To check it while pages are open:

```sh
procstat -s $(pgrep -f -- --type=renderer)
```

It is off by default because it is not yet a complete sandbox. What it
does today: every descriptor a confined renderer holds is cut to the
rights its kind needs, a renderer that cannot be confined ends, and the
suite checks all of it from outside with `procstat`. What is still
missing is listed under [Still to finish](#still-to-finish). An external
adversarial review of the lockdown, its tests and the release tools
(7 November 2026), and what changed because of it, is recorded in
[plan/16](plan/16-ADVERSARIAL-REVIEW-2026-11-07.md). Reports of anything
that breaks with it on are welcome; the test suite runs with it on through
`--browser-arg=--enable-features=BerylliumCapsicumRenderer`, which also
turns its sandbox tests into a gate that fails on any unconfined renderer.

#### Still to finish

In the order they are planned ([plan/14](plan/14-RENDERER-SANDBOX.md)
has the detail and the results of each build):

1. **Two sockets per renderer, to be named.** Each confined renderer makes
   one socket pair on its main thread and one on its compositor thread,
   one end of which goes to the browser. 0.20.3.12 cuts them at creation,
   and with that every descriptor of every renderer the suite could read
   was within the policy for the first time. Which Chromium code makes
   them is still to be named.
2. **A colour off by one.** In three of six runs with the lockdown on, a
   canvas colour read back one level off in one channel (`18,52,87` twice
   and `18,53,86` for `#123456`), on a CPU-drawn canvas as well as a GPU
   one and the same on both, never without the lockdown. Not understood
   yet; the rendering test now records a colour sweep to find the pattern.
3. **The browser cuts before it sends.** Today the renderer limits what it
   receives, which a compromised renderer could skip; the browser must
   limit every descriptor before sending it (S-IPC-01).
4. **The kernel's word on each renderer.** The browser checks each
   renderer's capability mode with the kernel before it gets a page, and
   a `beryllium://sandbox` page shows the answer per process.
5. **Single-threaded lockdown, verified.** Chromium orders the renderer's
   sandbox before its other threads exist, so the descriptor sweep should
   see every descriptor; the next build records the thread count at that
   point and the gate requires it to be one.
6. **On by default, fail closed.** When the suite passes the gate on every
   run, the production package turns the lockdown on.
7. **The other processes.** GPU, network, audio and utility processes get
   their own policies, or an explicit statement that they have none.
8. **Signed releases.** Signing `SHA256SUMS` with a key kept off GitHub,
   verified by `install.sh`; the proposal is in plan/16.
9. **Assurance.** A FreeBSD test machine for CI, review records for the
   217 imported FreeBSD patches on security paths, and the allocator
   hardening flags the review named as the main deficit.
10. **WebGPU** finds no adapter.

## Install

On FreeBSD 16 (amd64), download the installer, read it, then run it as your
normal user. It asks for root through `doas` or `sudo` only for the steps
that need it.

```sh
fetch -o install.sh https://raw.githubusercontent.com/johnjanik/Beryllium/main/install.sh
```

```sh
sh install.sh
```

(`curl -fsSL -o install.sh` with the same URL works too.)

The installer downloads the package for your FreeBSD version from this
repository's [releases](https://github.com/johnjanik/Beryllium/releases),
checks it against the release's `SHA256SUMS`, installs its dependencies
from the official FreeBSD package repository, and installs it.

| Command | What it does |
|---|---|
| `sh install.sh` | install or update to the latest release |
| `sh install.sh --build` | build from source with Poudriere and install (several hours, about 100 GB of disk); for FreeBSD versions without a package |
| `sh install.sh --uninstall` | remove Beryllium; your profile stays |
| `sh install.sh --dry-run` | show every command that would change the system, and change nothing |

`sh install.sh --help` lists the other options. To update, run
`sh install.sh` again when a new release is out; there is no in-browser
updater.

Beryllium needs `kern.ipc.shm_allow_removed=1`. The installer offers to
set it, and the launcher will not start the browser without it.

## Using Beryllium

- Start it from your desktop menu, or run `beryllium`.
- Internal pages use the `beryllium://` scheme: `beryllium://settings`,
  `beryllium://version`, `beryllium://gpu`.
- Your profile is in `~/.config/beryllium` (set `BERYLLIUM_CONFIG_HOME` to
  use another folder), separate from Chromium's and Helium's.
- Wayland is recommended. Under X11, any program in your session can read
  input from and inject input into other windows.
- Online services (extension proxy, `!bangs` list, filter-list and
  component updates, dictionaries) need a server, and Beryllium runs none
  of its own yet. They are off in a new profile, and no server is built
  in: they work only after you turn them on and enter a server at
  `beryllium://settings/privacy/services`, either your own instance of the
  open-source services (HTTPS, or `http://localhost` for a test server on
  your machine) or, as a deliberate choice, Helium's
  (`https://services.helium.imput.net`). Allowing them on the setup page
  alone contacts nothing. After an update from 0.20.3.1, a profile that
  never changed the setting has services off; one that turned them on
  keeps them on, with no server until you enter one. What each service
  does is in [the privacy plan](plan/07-PRIVACY-INVARIANTS-PLAN.md).
- Managed policies go in `/usr/local/etc/beryllium/policies/managed/`.

### Known issues

- **WebGPU** finds no adapter.
- **With the experimental lockdown on,** a canvas colour has read back one
  level off in one channel in three of six runs (see
  [Still to finish](#still-to-finish)); the lockdown is off by default.
- **NVIDIA graphics.** NVIDIA's FreeBSD driver handles two parts of
  Chromium's graphics path differently from the Intel and AMD drivers, and
  Beryllium works around both when it detects an NVIDIA driver:
  - Video frames are not written into GPU memory buffers, which crashed
    every video tab ("Error code 11"). The stock FreeBSD Chromium has the
    same crash; to avoid it there, start it with
    `--disable-gpu-memory-buffer-video-frames`.
  - On Wayland, the window flickered when the mouse moved, because the
    desktop could show a frame the GPU was still drawing. Beryllium now
    waits for the GPU to finish each frame first, which ended the flicker
    on the test machine.
    `--disable-features=BerylliumWaylandWaitForGpu` turns the wait off.

## Reporting a problem

Open an [issue](https://github.com/johnjanik/Beryllium/issues). For a
security problem, something exploitable or a false security claim, use
private reporting instead, as [SECURITY.md](SECURITY.md) describes. The
browser test suite collects most of what is needed: it runs the installed
Beryllium in throwaway profiles (your own profile is never opened) and
writes a report.

```sh
freebsd/tests/browser/run
```

Attach `report.txt` from the results directory it prints. `run --list`
shows every test; [its README](freebsd/tests/browser/README.md) explains
the options, such as `--my-settings` to check the toolbar with a copy of
your own settings and `--cores` to get backtraces from a crash.

## Build from source

Beryllium builds in a [Poudriere](https://github.com/freebsd/poudriere) jail
from this repository's port, `freebsd/ports/www/beryllium`. The full
walkthrough, from installing Poudriere to installing the package, is
[freebsd/ports/README.md](freebsd/ports/README.md); `sh install.sh --build`
follows it for you. With the jail and ports trees set up as described
there, a build is:

```sh
doas poudriere bulk -j 160amd64 -p default -O beryllium -b latest www/beryllium
```

Build in a jail of the same FreeBSD major version as the machine that will
run the package (`160amd64` for 16.0-CURRENT, `151amd64` for 15.1).

## Why Beryllium exists

Chromium already runs on FreeBSD through the `www/chromium` port, but
without kernel-enforced process confinement. The port's FreeBSD sandbox
code lowers one memory limit and returns. There is no zygote, no seccomp
equivalent and no Capsicum, so a compromised renderer has the same access
to files, sockets and processes as the user who started the browser.

No privacy-focused Chromium derivative offered a FreeBSD build. Beryllium
fills that gap first, and then works on the sandbox.

## Privacy features

From Helium's open-source patch set, Beryllium keeps:

- the patch set, defaults and build flags, including the ungoogled-chromium
  base;
- the bundled uBlock Origin, its filter defaults and CNAME uncloaking;
- native `!bangs`, fingerprinting noise, and the other privacy settings.

What differs:

- Beryllium does not use Helium's service endpoints: online services are
  off in a new profile and no server is built in. Beryllium will host its
  own instance of the open-source services; until then you can enter a
  server yourself (see [Using Beryllium](#using-beryllium)).
- Updates come through `pkg`.
- Crash reports are never uploaded: there is no crash reporter on FreeBSD.

## What Beryllium adds

| Layer | Purpose |
|---|---|
| **Capsicum renderer sandbox** | Every renderer enters capability mode with an audited, rights-limited set of file descriptors: no path access, no direct network sockets, no access to other processes. Sandbox setup failure is fatal in production builds. This is the central milestone; 0.20.3.7 has the first steps, with the lockdown itself still opt-in. |
| **Per-process policies** | Separate confinement for PDF, print, audio, network, GPU and media utility processes, each with its own tests or a published risk statement. |
| **Process hardening** | Tracing disabled, no privilege gain, calibrated resource limits per process type. |
| **Optional jail profile** | An administrator-managed whole-browser jail as an outer perimeter. Never a substitute for the renderer sandbox and never installed automatically. |
| **Resource profiles** | Measured `rctl` rule sets for jail deployments. |
| **Kernel-attested status** | Status pages report what the kernel says about each process, which you can check yourself with `procstat`. The first step is in this release: `beryllium://gpu` reports the GPU process's real state. |
| **MAC module study** | An optional, administrator-loaded policy that narrows what sandboxed processes can reach in the kernel. Not required for a first release. |

## Roadmap

| Phase | Outcome | Status |
|---|---|---|
| 0. Baseline | Reproduce the FreeBSD Chromium build and record what is actually sandboxed | mostly done; the per-process baseline of the stock Chromium remains |
| 1. Native build | `www/beryllium` builds and runs on FreeBSD with the inherited privacy behaviour and no false sandbox claims | in progress: packages build and run |
| 2. Capsicum renderer | Renderers confined in capability mode and verified by tests | in progress: in 0.20.3.12, clean descriptors at launch, anonymous shared memory, no swap file, an opt-in lockdown with least rights on every descriptor, admission by place and shape, and a test suite that is a gate; still to come, the browser cutting what it sends, the kernel check, the lockdown before the renderer's threads start and then on by default |
| 3. Other processes | Utility, audio, network and GPU policies | planned |
| 4. Jail and resources | Optional jail profile and measured resource limits | planned |
| 5. MAC module study | Decision memo, prototype if justified | planned |
| 6. Release engineering | Signed packages, CI, and a maintenance process another person can follow | started (CI, installer, test suite, build manifests checked before publishing); signing proposed |

Every feature the project must implement, build and test, with its status,
is in the [feature matrix](plan/13-FEATURE-MATRIX.md). Details are in the
[roadmap](plan/09-ROADMAP.md) and the rest of
[`plan/`](plan/00-INDEX.md); the engineering specification is
[helium-freebsd-security-port-spec.md](helium-freebsd-security-port-spec.md).

## Targets

- FreeBSD amd64: 16.0-CURRENT (where development happens) and the supported
  stable branches (14.x and 15.x), with kernels patched for
  FreeBSD-SA-26:28.capsicum. Packages are published for the versions the
  project has built and checked; the others build from source.
- Wayland (recommended) and X11.
- `aarch64` later, once CI covers it.

## Repository layout

The upstream patch set is a git submodule pinned at a release tag and never
edited; Beryllium's changes are separate patches applied after it.

| Path | Contents |
|---|---|
| `helium/` | Submodule: [imputnet/helium](https://github.com/imputnet/helium) at release tag `0.20.3`, commit `2f81b9ca` (Chromium 156.0.8078.79) |
| `patches/` | Beryllium's patches, applied after the upstream series: branding, FreeBSD platform fixes, security, and interface fixes |
| `flags.freebsd.gn` | FreeBSD build flags appended to the upstream `flags.gn` |
| `freebsd/ports/` | The Poudriere port, with the imported FreeBSD Chromium patch set |
| `freebsd/tests/` | The browser test suite and the Capsicum kernel tests |
| `freebsd/tools/` | Build, patch, release and checking tools |
| `artwork/` | Vector masters of the logo and wordmark, the icons, and the source art sheet (CC BY 4.0) |
| `design-intake/` | Artwork review rounds: how the vector logo was made and approved |
| `branding/` | Tools that prepare the artwork, and the branding files the build uses |
| `install.sh` | The installer |
| `plan/` | Design and planning documents |
| `LICENSES/` | Licence texts other than the GPL-3.0 in `LICENSE` |

Clone with the submodule:

```sh
git clone --recurse-submodules https://github.com/johnjanik/Beryllium.git
```

## Origin and independence

Beryllium is an independent project. It is derived from the GPL-3.0 source
code of the Helium browser by imput, as the licence permits, but it is not
affiliated with, endorsed by, or operated together with Helium or imput, and
it does not use Helium's names, logos or online services. Report problems
with Beryllium here, not to the Helium project. Beryllium does not plan to
send changes upstream.

## Contributing

Issues and pull requests are welcome. Changes that touch process creation,
IPC, file descriptors, shared memory, the GPU process, the network service
or sandbox setup require a security review before merging. How patches are
layered is described in [the patch strategy](plan/05-PATCH-STRATEGY.md).

## Credits

- **[Helium](https://github.com/imputnet/helium)** by imput, whose GPL-3.0
  patch set and tooling Beryllium's code is derived from.
- **[The Chromium Project](https://www.chromium.org/)**, at the core of
  Helium and Beryllium.
- **[ungoogled-chromium](https://github.com/ungoogled-software/ungoogled-chromium)**,
  which Helium is based on.
- **Other Chromium browsers** whose patches the upstream set includes:
  [Inox patchset](https://github.com/gcarq/inox-patchset),
  [Debian](https://tracker.debian.org/pkg/chromium-browser),
  [Bromite](https://github.com/bromite/bromite),
  [Iridium Browser](https://iridiumbrowser.de/) and
  [Brave](https://github.com/brave/brave-core).
  These patches are sorted by vendor in [helium/patches/](https://github.com/imputnet/helium/tree/main/patches).
- **The FreeBSD and OpenBSD Chromium ports**, maintained at
  `chromium@FreeBSD.org` and in OpenBSD ports, whose BSD patch set makes a
  FreeBSD build possible.
- **Earlier Capsicum work on Chromium**: the 2010 Capsicum paper by Watson,
  Anderson, Laurie and Kennaway, and the FreeBSD Capsicum sandbox efforts
  tracked in FreeBSD bug 269234.

## License

All code, patches, modified portions of imported code or patches, and any
other content unique to Helium or Beryllium and not imported from other
repositories is licensed under GPL-3.0. See [LICENSE](LICENSE).

The exception is Beryllium's artwork: the logo, wordmark and icons in
[`artwork/`](artwork/README.md), and the branding files generated from them
in `branding/chromium/` (and their copy in the FreeBSD port), are licensed
under Creative Commons Attribution 4.0 International. See
[LICENSES/CC-BY-4.0.txt](LICENSES/CC-BY-4.0.txt).

The Beryllium name and logo identify the project; neither licence grants
trademark rights. See [TRADEMARKS.md](TRADEMARKS.md).

Helium, included as a submodule, is under its own licenses: GPL-3.0 for
Helium's code, with imported content keeping its original license. For
example, original unmodified code imported from ungoogled-chromium remains
under its
[BSD 3-Clause license](https://github.com/imputnet/helium/blob/main/LICENSE.ungoogled_chromium).
