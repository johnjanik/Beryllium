<div align="center">
    <picture>
        <source media="(prefers-color-scheme: dark)"
            srcset="branding/kit/masters/lockup-color-dark.png" />
        <img src="branding/kit/masters/lockup-color.png"
            title="Beryllium Browser" alt="Beryllium Browser" width="420" />
    </picture>
    <p>
        A privacy-focused browser for FreeBSD.
        <br>
        Built natively, confined with FreeBSD's own security primitives.
    </p>
</div>

## Goal

**The goal of this project is to create Beryllium: a privacy-focused,
Chromium-based browser built natively for FreeBSD.**

Beryllium is built from source as a native FreeBSD application and ships as
an ordinary `pkg` package. Its privacy patch set is derived from the GPL-3.0
code of the Helium browser, and it replaces the missing Chromium sandbox on
FreeBSD with one built on FreeBSD's own security primitives. Beryllium is an
independent project; see [Origin and independence](#origin-and-independence).

## Status

> [!WARNING]
> Beryllium is in **Phase 0**. There is no browser build, no package, and
> no sandbox code yet. Nothing in this repository should be used as a
> browser on FreeBSD today.

What exists so far:

- [`freebsd/tests/capsicum-standalone/`](freebsd/tests/capsicum-standalone/README.md):
  a Capsicum kernel oracle and red-team probe set. Run
  `sh freebsd/tests/capsicum-standalone/run-oracle.sh` as an ordinary user.
- [`freebsd/tools/baseline-collect.sh`](freebsd/tools/baseline-collect.sh):
  records the machine, kernel and a running stock Chromium for the Phase 0
  baseline.
- [`freebsd/tools/gnargs-from-flags`](freebsd/tools/gnargs-from-flags) and
  [`flags.freebsd.gn`](flags.freebsd.gn): generated GN arguments with a
  privacy-key guard.
- [`freebsd/ports/www/beryllium`](freebsd/ports/README.md): the Poudriere
  port (untested skeleton) with the imported FreeBSD patch set and
  Beryllium's first patches (`beryllium://`, own profile and paths).
- [`freebsd/PATCH-MATRIX.md`](freebsd/PATCH-MATRIX.md): where the FreeBSD,
  Helium and Beryllium patch layers touch the same files.

The design is written up in [`plan/`](plan/00-INDEX.md). Start with the
[index](plan/00-INDEX.md), then the [project charter](plan/01-PROJECT-CHARTER.md)
and the [roadmap](plan/09-ROADMAP.md). The engineering specification the plan
implements is [helium-freebsd-security-port-spec.md](helium-freebsd-security-port-spec.md).

## Why Beryllium exists

Chromium already runs on FreeBSD through the `www/chromium` port, but it runs
without kernel-enforced process confinement. The port's FreeBSD sandbox code
lowers one memory limit and returns. There is no zygote, no seccomp
equivalent and no Capsicum. A compromised renderer has the same access to
files, sockets and processes as the user who started the browser.

No privacy-focused Chromium derivative offers a FreeBSD build. Beryllium is
an independent project that fills that gap.

## Privacy features from the code base

Beryllium's code base is derived from Helium's open-source patch set. From it,
Beryllium keeps:

- The patch set, defaults and build flags, including the ungoogled-chromium
  base.
- The bundled uBlock Origin fork, its filter defaults and CNAME uncloaking.
- Native `!bangs`, the onboarding page, fingerprinting noise, and the rest of
  the privacy customizations.

Things that differ:

- Beryllium does not use Helium's service endpoints. The services switch
  (extension proxy, `!bangs` list, filter-list updates, dictionaries,
  component updates) is off by default until Beryllium hosts its own instance
  of the open-source services. The consequences per feature are listed in
  [the privacy invariants plan](plan/07-PRIVACY-INVARIANTS-PLAN.md).
- Browser updates arrive through `pkg`, not an in-app updater.
- Crash reports are not uploaded, because the crash handler does not run on
  FreeBSD.

## What Beryllium adds

| Layer | Purpose |
|---|---|
| **Capsicum renderer sandbox** | Every renderer enters capability mode with an audited, rights-limited set of file descriptors. No path access, no direct network sockets, no access to other processes. Sandbox setup failure is fatal in production builds. This is the central milestone. |
| **Per-process policies** | Separate confinement for PDF, print, audio, network, GPU and media utility processes, each with its own tests or a published risk statement. |
| **Process hardening** | Tracing disabled, no privilege gain, calibrated resource limits per process type. |
| **Optional jail profile** | An administrator-managed whole-browser jail as an outer perimeter. Never a substitute for the renderer sandbox and never installed automatically. |
| **Resource profiles** | Measured `rctl` rule sets for jail deployments. |
| **Kernel-attested status** | The sandbox status page reports what the kernel says about each process, which users can check themselves with `procstat`. |
| **MAC module study** | An optional, administrator-loaded policy that narrows what sandboxed processes can reach in the kernel (sockets, sysctls, process visibility). Not required for a first release. |

Every release will publish a table stating what is enforced and tested, what
is configured but untested, and what is planned.

## Roadmap

| Phase | Outcome |
|---|---|
| 0. Baseline | Reproduce the current FreeBSD Chromium build and record what is actually sandboxed |
| 1. Native build | `www/beryllium` builds and runs on FreeBSD with the inherited privacy behaviour preserved and no sandbox claims |
| 2. Capsicum renderer | Renderers confined in capability mode and verified by tests |
| 3. Other processes | Utility, audio, network and GPU policies |
| 4. Jail and resources | Optional jail profile and measured resource limits |
| 5. MAC module study | Decision memo, prototype if justified |
| 6. Release engineering | Signed packages, CI, and a maintenance process another person can follow |

Details, effort estimates and the first-release definition are in the
[roadmap](plan/09-ROADMAP.md).

## Targets

- FreeBSD `amd64` on the supported stable branches (currently 14.x and 15.x),
  with kernels patched for FreeBSD-SA-26:28.capsicum. Development happens on
  16.0-CURRENT; stable branches are built in Poudriere jails and tested in
  bhyve guests.
- Wayland (recommended) and X11. On X11 any client can read input from and
  inject input into other windows, which weakens every sandbox layer.
- `aarch64` later, once CI covers it.

## Repository layout

Beryllium is structured as a platform repository around a pinned copy of
the upstream patch set it is derived from. That code is included as a git
submodule pinned at a release tag. Nothing inside it is edited, so moving the
pin never causes merge conflicts.

| Path | Contents |
|---|---|
| `helium/` | Submodule: [imputnet/helium](https://github.com/imputnet/helium) at release tag `0.20.3`, commit `2f81b9ca` (Chromium 156.0.8078.79) |
| `patches/` | Beryllium patches for FreeBSD platform, branding and security, applied after the upstream series (planned) |
| `flags.freebsd.gn` | FreeBSD build flags appended to the upstream `flags.gn`, combined by `freebsd/tools/gnargs-from-flags` |
| `freebsd/` | FreeBSD port, sandbox policies, test suites, tooling and branding |
| `plan/` | Planning documents |

Clone with the submodule:

```bash
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

Beryllium is at the planning stage. Issues that discuss the plan are welcome.
Changes that touch process creation, IPC, file descriptors, shared memory,
the GPU process, the network service or sandbox setup require a security
review before merging.

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

Helium, included as a submodule, is under its own licenses: GPL-3.0 for
Helium's code, with imported content keeping its original license. For
example, original unmodified code imported from ungoogled-chromium remains
under its
[BSD 3-Clause license](https://github.com/imputnet/helium/blob/main/LICENSE.ungoogled_chromium).
