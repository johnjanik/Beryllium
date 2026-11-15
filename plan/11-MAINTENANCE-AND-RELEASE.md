# Beryllium: Maintenance Cadence and Release Process

**Status:** Draft plan, no code written
**Date:** 18 October 2026; amended 1 November 2026 (RT-10, RT-11, owner decisions)
**Implements:** spec sections 11.3, 12 (Phase 6) and 14

---

## 1. What drives the cadence

Three upstream clocks tick independently:

| Clock | Typical rhythm | Beryllium response |
|---|---|---|
| Chromium stable releases | a major every four weeks, security point releases weekly or faster | Helium tracks these; Beryllium follows Helium |
| Helium releases | follows Chromium, a few days behind (exact lag to be measured over Phase 0 from the releases page); three tags and a Chromium major between 18 October and 1 November 2026 | move the submodule to the release tag, run the update procedure |
| FreeBSD and OpenBSD `www/chromium` updates | FreeBSD was one major behind Helium at the snapshot and on the same major (156) on 1 November; OpenBSD was level at the snapshot | determines how much BSD forward-porting Beryllium does itself |
| FreeBSD security advisories | irregular | a Capsicum or kernel advisory triggers the advisory checklist below |

The realistic steady-state commitment is one Beryllium release per Helium
release, plus out-of-band builds when a Chromium security fix is rated high
and Helium has not yet shipped it. Measuring the time between a Chromium stable
security release and a Beryllium package being published is the project's
primary health metric and is recorded in every release note.

Freshness is a security property (RT-11): a sandboxed browser on an old V8 can
be less safe than an unsandboxed current one. Therefore:

- **Turnaround target:** a package within 72 hours of a Helium tag that
  carries security fixes. Missing it is a release-gate failure that needs a
  written exception in the release notes.
- **Builder:** the owner's FreeBSD 16.0-CURRENT host (128 GB RAM, 24 cores,
  about 7 TB) is the dedicated builder; packages for users are built in
  14.x and 15.x Poudriere jails on it. A security tag triggers an immediate
  build rather than waiting for the nightly run.
- **Build-age warning:** Chromium's outdated-build detection is adapted to
  key on the build date and tell the user to run `pkg upgrade`, so stale
  installs warn their users even when the repository is not configured.
- **Fast path:** the hand forward-port path for when the BSD ports lag the pin
  (05 section 7, step 3) is rehearsed before it is needed.

## 2. Roles

Even with a single maintainer the roles are named so the handover criterion of
Phase 6 ("a maintainer other than the original author can update") is
meaningful:

- **Release maintainer**: runs the update procedure, signs packages.
- **Security reviewer**: second reader for any patch with
  `security-review: required`; can be the same person only for non-release
  work.
- **BSD patch importer**: runs the import tool and reconciles with FreeBSD
  and OpenBSD ports; files upstream bugs.

## 3. Update procedure (per Helium release)

1. Move the `helium` submodule to the new Helium release tag. Nothing inside
   `helium/` is edited, so there is nothing to merge; Beryllium patches that
   no longer apply are refreshed in step 3.
2. Run `freebsd/tools/import-bsd-patches` for the new Chromium version;
   record the FreeBSD and OpenBSD ports commits; review the diff of every
   patch under the security-relevant paths and commit a review record for each
   (RT-10, 05 section 5). Once per Chromium version, cross-check the base
   tarball against an independent source.
3. Run stages 0 to 6 locally; refresh failing patches with quilt.
4. Regenerate the patch matrix and the flag diff; review.
5. Build in Poudriere for every supported branch.
6. Run the sandbox, privacy, functional, resource and build suites.
7. Update the descriptor allowlist only with a written rationale per new
   entry; never widen rights to make a test pass.
8. Bump `revision.txt`, write the changelog entry (including the
   Chromium security notes link and any sandbox or privacy change), write the
   build manifest.
9. Tag `v<helium-version>.<platform-revision>`, publish packages to the
   signed repository, publish release notes with the sandbox status table.

## 4. Advisory checklist

When FreeBSD publishes an advisory that touches Capsicum, process control,
signals, shared memory, jails, `rctl`, the dynamic linker or the graphics
stack (the June 2026 `SA-26:28.capsicum` `sigqueue` case is the model):

1. Add the advisory to `freebsd/ADVISORIES.md` with the fixed branch
   versions.
2. Add or extend an oracle test in `capsicum-standalone/` that detects the
   unfixed kernel.
3. Update the preflight check so the browser's `chrome://sandbox` page and the
   package's `pkg-message` warn when the running kernel predates the fix.
   The browser does not refuse to run on an unpatched kernel (that would push
   users toward other browsers with no sandbox at all) but it reports the
   weakened status honestly.
4. If the advisory affects the test infrastructure, patch the test hosts
   first and re-run the oracle.

## 5. Package distribution

- Packages are built in Poudriere from a clean 14.x or 15.x jail on the
  owner's build host by an unprivileged build account and published to a
  repository signed with a key kept off the build host (`pkg` repository
  signing with `signing_command`).
- No SUID binaries, no world-writable directories, no in-browser updater.
  The `pkg-message` tells users that updates arrive through `pkg upgrade`.
- `beryllium` (production) and `beryllium-devel` (debug switches retained,
  sandbox hooks compiled in) are separate ports sharing a `Makefile` via a
  slave-port arrangement, with distinct package names and `CONFLICTS`.
- Debug symbols are produced as a separate `beryllium-dbg` package or a
  downloadable symbol archive referenced by the build manifest, so that crash
  and sandbox triage is possible without shipping 1 GB binaries by default.
- The port is offered to the FreeBSD ports tree once Phase 2 exit criteria are
  met; until then the overlay in `freebsd/ports/` is the distribution channel
  and the README explains how to use it with Poudriere (`-O` overlay).

## 6. Security policy and disclosure

`SECURITY.md` at the repository root (written 9 November 2026) states:

- Supported versions: the latest Beryllium release only, on the FreeBSD
  branches listed in the release notes.
- Reporting channel: GitHub's private vulnerability reporting for the
  repository, which reaches the maintainer alone and can become a
  published advisory with credit. The dedicated email address with a
  published PGP key that this section first called for is deferred until
  the project has a second maintainer to hold the key; `SECURITY.md` says
  there is none yet. The policy that Chromium engine bugs are redirected
  to Chromium and FreeBSD kernel bugs to FreeBSD, while bugs in the
  inherited privacy patch set, the sandbox, packaging and FreeBSD-specific
  issues are handled here (Beryllium does not forward reports to Helium,
  charter D8).
- Response targets: acknowledgement in 3 days, assessment in 7, fix or
  mitigation timeline communicated after assessment, publication 90 days
  after receipt or earlier by agreement.
- The sandbox status table (what is enforced, what is configured but not
  tested, what is aspirational) is published with every release and linked
  from `SECURITY.md`, so that the project never overstates its protection;
  a false security claim is in scope as a vulnerability.
- Dependencies: `.github/dependabot.yml` watches the commit-pinned GitHub
  Actions; the Helium submodule and the FreeBSD patch set are moved by the
  update procedure (section 3), not by Dependabot, whose submodule updates
  follow a branch head rather than releases.

## 7. Handover test

Before the first public release, a person other than the original author
follows `freebsd/UPDATING.md` from a clean machine to update to a newer Helium
tag, build, test and produce a signed package, with the author only answering
questions in writing. Every question asked becomes a documentation fix. This is
the Phase 6 exit criterion made concrete.

## 8. First rehearsal of an update: Helium 0.20.3 to 0.21.3 (15 November 2026)

Helium tagged 0.21.3 on 12 November 2026. It was the first release after
Beryllium's own, so the update procedure of section 3 was rehearsed
against it, away from the repository, to find out what an update costs.
Nothing was changed here: the pin is still 0.20.3. Numbers are from that
rehearsal; how each was obtained is in its report, which is not kept in
the repository.

**What the release is.** Chromium 156.0.8078.79 to 157.0.8103.78, a new
major. Helium's series went from 346 to 354 patches: 13 added, 5
removed, 252 files under `patches/` changed. Between 0.20.2 and 0.20.3,
a point release, 8 patch files had changed. So updates come in two
sizes, and this was the large one.

**The BSD patch set is the deciding fact.** On 15 November FreeBSD's
`www/chromium` was still at 156.0.8078.79_1. OpenBSD's was at
157.0.8103.78 since 13 November. FreeBSD's port has taken 151, 152, 154
and 156 this autumn and skipped 153 and 155; OpenBSD took every version
within two days of Helium's tag since 21 October. So on a new Chromium
major the set has to come from OpenBSD (05 section 5), and Beryllium is
then ahead of the FreeBSD port, building what nobody has built on
FreeBSD.

| Step | Result |
|---|---|
| The current 1,696 FreeBSD patches applied to Chromium 157 | 1,309 clean, 280 with a line offset, 40 with fuzz, 67 failed |
| FreeBSD's and OpenBSD's sets compared at 156 | the same 1,696 files, 1,695 identical and 1 differing in a line number; OpenBSD has 8 more. No FreeBSD-only patch, so nothing to merge by hand |
| OpenBSD's 157 set, renamed to FreeBSD's form (1,676 patches), applied to Chromium 157 | 1,675 clean, 1 with an offset, 0 failed |
| Of the 217 patches on security paths (RT-10) | 202 unchanged, 12 changed, 3 new: 15 to read |
| Helium 0.21.3 on that set | 11 failing sections in 9 patches of 2,561; `patch-conflicts` wrote 7 refreshes by three-way merge, 0 by hand; then no failure |
| The 10 existing refreshes | 1 still matched its original; 9 had to be deleted first, or the tool applies them in place of Helium's changed patches |
| Beryllium's 20 patches | all apply: 9 clean, 11 with a line offset |
| The repository's checks with the pin moved | `helium-linux-conditions`, `helium-bsd-crashpad-calls` and the GN argument check pass unchanged; the matrix names a patch Helium removed (`prefer-https-by-default`, which Chromium 157 makes unnecessary) |
| Machine time for all of the above | about 17 minutes |

**What is real work.**

1. *A second built-in server.* Helium 0.21.3 adds web push with its own
   default server (`wss://push.helium.computer/`). It is behind a feature
   that is off and behind the services switch that Beryllium keeps off,
   so a new profile still contacts nobody. But a user who turns services
   on with a server of their own would reach Helium's push server once
   Helium enables the feature. `beryllium-services-off-by-default.patch`
   has to empty that default as it did the first, with a test.
2. *Fifteen changed patches on security paths to read,* among them
   `sandbox/policy/sandbox_type.cc`, `content/utility/utility_main.cc`
   and `chrome/app/chrome_main_delegate.cc`, which Beryllium's own
   patches sit beside.
3. *A Rust tool the port must build.* OpenBSD's 157 port builds
   `cc_bindings_from_rs` (crubit) inside the port: a new distfile, 94
   crates, and two GN arguments. It took OpenBSD three commits over six
   days. Whether FreeBSD's `lang/rust` can build it is not known.
4. *The build.* Nobody has compiled Chromium 157 with this set on
   FreeBSD as far as the ports tree shows. Each failed attempt costs
   hours on the build machine.

**What the tools lack.** `import-bsd-patches` takes a FreeBSD ports
checkout only: it needs an OpenBSD mode (the renaming, the header line,
the OpenBSD commit in `IMPORTED-FROM`). Its review record is keyed by a
file's SHA-256 and would list 214 of 217 patches as changed where 15
are; it should compare hunks. `patch-conflicts` should ignore a refresh
whose `Original sha256` no longer matches. `distinfo` for the Helium
tarball has to be made on the build machine.

**What this says about cadence.** Helium made 16 tags in nine weeks,
with a new Chromium major about every two weeks. The patch work of an
update is small and mostly done by the tools. The cost is the build and,
on a new major, being ahead of FreeBSD's port. Two ways to keep up
follow from that, and the choice is the owner's:

- *Follow FreeBSD's port.* Update when `www/chromium` reaches Helium's
  Chromium version. The patch set has then been built on FreeBSD by its
  maintainers. Beryllium is as current as FreeBSD's own Chromium and no
  more, and waits when the port skips a major.
- *Follow Helium, from OpenBSD's set.* Update within days of each tag.
  Beryllium carries every Chromium security fix sooner, and pays for it
  in failed builds and in port work the FreeBSD maintainers have not
  done yet (the Rust tool is this release's example).

The 72-hour target of section 1 assumes the second. It has not been met
for 0.21.1 (4 November), 0.21.2 (10 November) or 0.21.3.
