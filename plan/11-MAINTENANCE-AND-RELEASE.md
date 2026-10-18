# Beryllium: Maintenance Cadence and Release Process

**Status:** Draft plan, no code written
**Date:** 18 October 2026
**Implements:** spec sections 11.3, 12 (Phase 6) and 14

---

## 1. What drives the cadence

Three upstream clocks tick independently:

| Clock | Typical rhythm | Beryllium response |
|---|---|---|
| Chromium stable releases | a major every four weeks, security point releases weekly or faster | Helium tracks these; Beryllium follows Helium |
| Helium releases | follows Chromium, a few days behind (exact lag to be measured over Phase 0 from the releases page) | merge the release tag, run the update procedure |
| FreeBSD and OpenBSD `www/chromium` updates | FreeBSD was one major behind Helium at the snapshot; OpenBSD was level | determines how much BSD forward-porting Beryllium does itself |
| FreeBSD security advisories | irregular | a Capsicum or kernel advisory triggers the advisory checklist below |

The realistic steady-state commitment is one Beryllium release per Helium
release, plus out-of-band builds when a Chromium security fix is rated high
and Helium has not yet shipped it. Measuring the time between a Chromium stable
security release and a Beryllium package being published is the project's
primary health metric and is recorded in every release note.

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
   record the FreeBSD and OpenBSD ports commits.
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

- Packages are built in Poudriere from a clean jail by an unprivileged build
  account and published to a repository signed with a key kept off the build
  host (`pkg` repository signing with `signing_command`).
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

`SECURITY.md` at the repository root states:

- Supported versions: the latest Beryllium release only, on the FreeBSD
  branches listed in the release notes.
- Reporting channel: a dedicated email with a published PGP key, and the
  policy that Chromium or Helium engine bugs are redirected to those projects
  while sandbox, packaging and FreeBSD-specific issues are handled here.
- Response targets: acknowledgement in 3 days, assessment in 7, fix or
  mitigation timeline communicated after assessment.
- The sandbox status table (what is enforced, what is configured but not
  tested, what is aspirational) is published with every release and linked
  from `SECURITY.md`, so that the project never overstates its protection.

## 7. Handover test

Before the first public release, a person other than the original author
follows `freebsd/UPDATING.md` from a clean machine to update to a newer Helium
tag, build, test and produce a signed package, with the author only answering
questions in writing. Every question asked becomes a documentation fix. This is
the Phase 6 exit criterion made concrete.
