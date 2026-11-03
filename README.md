<div align="center">
    <picture>
        <source media="(prefers-color-scheme: dark)"
            srcset="artwork/wordmark/beryllium-lockup-dark.png" />
        <img src="artwork/wordmark/beryllium-lockup.png"
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
> browsing, but no Beryllium process is confined: like the stock
> FreeBSD Chromium, a compromised web page has the same access to your
> files and network as you do. `beryllium://gpu` says so
> ("Sandboxed: false"). Do not rely on Beryllium to contain an attack yet.

Current release: **Beryllium 0.20.3.1**, based on Chromium 156.0.8078.79.

- **Packages:** FreeBSD 16.0-CURRENT, amd64. Other FreeBSD versions: build from source (below).
- **Checked on:** FreeBSD 16.0-CURRENT, NVIDIA GeForce RTX 5090 Laptop GPU (driver 595.99.02), KDE Plasma on Wayland.
- **Works:** browsing; video playback, including YouTube; WebGL; the toolbar in all of Helium's layouts; Beryllium's own name, icons, `beryllium://` pages and profile folder.
- **Privacy check:** a fresh browser, idle and showing a local page, contacts no outside server (test suite, `privacy` group).
- **Not yet:** any process sandbox; WebGPU (no adapter is found).

### Sandbox status of this release

Each release states what is enforced, so you can check it yourself with
`procstat -s` (a `C` in the flags column means Capsicum capability mode).

| Process | Status |
|---|---|
| Browser | not confined |
| Renderers (web pages) | not confined |
| GPU | not confined (reported honestly at `beryllium://gpu`) |
| Network, audio, other utilities | not confined |

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
  component updates, dictionaries) are off by default, because the project
  runs no servers for them yet. What that changes for each feature is in
  [the privacy plan](plan/07-PRIVACY-INVARIANTS-PLAN.md).
- Managed policies go in `/usr/local/etc/beryllium/policies/managed/`.

### Known issues

- **WebGPU** finds no adapter.
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

Open an [issue](https://github.com/johnjanik/Beryllium/issues). The browser
test suite collects most of what is needed: it runs the installed Beryllium
in throwaway profiles (your own profile is never opened) and writes a
report.

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

- Beryllium does not use Helium's service endpoints; its online services
  are off until Beryllium hosts its own instance of the open-source
  services.
- Updates come through `pkg`.
- Crash reports are never uploaded: there is no crash reporter on FreeBSD.

## What Beryllium adds

| Layer | Purpose |
|---|---|
| **Capsicum renderer sandbox** | Every renderer enters capability mode with an audited, rights-limited set of file descriptors: no path access, no direct network sockets, no access to other processes. Sandbox setup failure is fatal in production builds. This is the central milestone. |
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
| 2. Capsicum renderer | Renderers confined in capability mode and verified by tests | next |
| 3. Other processes | Utility, audio, network and GPU policies | planned |
| 4. Jail and resources | Optional jail profile and measured resource limits | planned |
| 5. MAC module study | Decision memo, prototype if justified | planned |
| 6. Release engineering | Signed packages, CI, and a maintenance process another person can follow | started (CI, installer, test suite) |

Details are in the [roadmap](plan/09-ROADMAP.md) and the rest of
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
| `artwork/` | Logo, wordmark, icons and the source art sheet (CC BY 4.0) |
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
