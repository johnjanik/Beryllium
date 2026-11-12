# Security policy

Beryllium is a development-stage browser. By default no Beryllium process
is confined, which the [README](README.md#status) says first and which
`beryllium://gpu` confirms; an experimental renderer lockdown exists and
is off by default. The README's
[sandbox status table](README.md#sandbox-status-of-this-release) says,
for every release, what is enforced and what is not; the
[feature matrix](plan/13-FEATURE-MATRIX.md) says the same per feature,
with what is implemented, built and tested. Please read them before
reporting: much of what a sandbox would prevent is known, documented and
being built, and the list of what is still missing is kept current in the
README under "Still to finish".

## Supported versions

Only the latest release is supported. A fix ships as a new release; older
releases are not patched.

| Version | Supported |
|---|---|
| 0.20.3.12 (current, FreeBSD 16.0-CURRENT amd64 packages) | yes |
| earlier releases | no: update |

Packages are published for FreeBSD 16.0-CURRENT on amd64. Building from
source on other FreeBSD versions is supported on a best-effort basis.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository:
<https://github.com/johnjanik/Beryllium/security/advisories/new>. It
reaches the maintainer and nobody else, and the report can become a
published advisory later with credit to you. Do not open a public issue
for something exploitable; ordinary bugs go in
[issues](https://github.com/johnjanik/Beryllium/issues) as the README
describes.

A useful report says:

- the Beryllium version (`beryllium://version`, or `pkg info beryllium`)
  and the FreeBSD version (`freebsd-version -ku`);
- whether the renderer lockdown was switched on
  (`--enable-features=BerylliumCapsicumRenderer`);
- what you did, what happened, and what the impact is (what a page or a
  compromised process can reach that it should not);
- if the test suite is relevant, its `report.txt`
  (`freebsd/tests/browser/run`; it uses throwaway profiles and contains
  no personal data).

What to expect: an acknowledgement within 3 days and an assessment
within 7; the timeline for a fix or a mitigation is told to you after the
assessment, and the report is published 90 days after it was received
whatever the state of the fix, or earlier by agreement. Beryllium has one
volunteer maintainer, so these are targets, not guarantees; a report that
is being worked on gets an update at least every two weeks. Credit is
given in the release notes and the advisory unless you ask otherwise.

There is no separate email address or PGP key yet; when there is, it will
be listed here.

## What is in scope

- Beryllium's own patches (`patches/`), the FreeBSD port
  (`freebsd/ports/www/beryllium`), the tools (`freebsd/tools/`,
  `branding/tools/`), `install.sh`, the release process
  (`freebsd/tools/publish-release`) and the browser test suite.
- A way past the renderer lockdown when it is switched on: a confined
  renderer reaching a file, a socket, a process or a kernel service that
  the policy in [plan/06](plan/06-SECURITY-MODEL.md) says it must not.
- A false security claim: a status page, a release note, the README or a
  test saying something is confined, limited or verified when it is not.
  Beryllium's position is that an honest "not confined" is a feature and
  a false "confined" is a vulnerability.
- Anything in the build or release path that would let a package differ
  from the commit it claims to be built from (see "Verifying a release").

## What is upstream

Beryllium is Chromium, built from [Helium](https://github.com/imputnet/helium)
with Beryllium's patches on top. Most of the code is not ours.

- **Chromium** vulnerabilities (V8, Blink, the network stack, codecs...):
  report to the [Chromium security team](https://www.chromium.org/Home/chromium-security/reporting-security-bugs/).
  Beryllium follows Helium's Chromium version and rebuilds when Helium
  does ([plan/11](plan/11-MAINTENANCE-AND-RELEASE.md) section 1); the
  Chromium version of each release is in the README and in the release's
  build manifest. A Chromium security release therefore reaches Beryllium
  users with a lag, which the project treats as a security property to
  measure and shorten, not as acceptable.
- **Helium's patches**, as shipped in Beryllium (the privacy features,
  the services switch, the user interface changes): handled here, like
  Beryllium's own patches. Beryllium is independent of Helium and does
  not forward reports to it ([charter D8](plan/01-PROJECT-CHARTER.md));
  if the problem is in Helium's code and affects Helium too, you are
  welcome to tell Helium yourself.
- **FreeBSD** (the kernel, Capsicum, the ports framework): report to the
  [FreeBSD security team](https://www.freebsd.org/security/). A FreeBSD
  advisory that touches Capsicum, process control, descriptors or shared
  memory triggers the checklist in plan/11 section 4 and is recorded in
  [freebsd/ADVISORIES.md](freebsd/ADVISORIES.md).

If you are not sure where a problem belongs, send it here. If it belongs
to Chromium or FreeBSD you will be told where, and with your consent the
maintainer files it there.

## Verifying a release

- `install.sh` fetches `SHA256SUMS` and the package from the release and
  checks the digest before anything runs with privileges.
- Every package carries `/usr/local/share/beryllium/BUILD-MANIFEST.json`,
  also published with the release: the version, the Chromium and Helium
  versions, the imported FreeBSD patch set and the SHA-256 of every
  Beryllium patch. The release tool refuses a package whose manifest does
  not match the commit the release names
  (`freebsd/tools/check-provenance`). It also refuses a package built with
  a compiler cache (`compiler_cache` in the manifest, from 0.20.3.19): in a
  release, every object file came from the compiler during that build.
- Releases are not yet signed with a key separate from GitHub; the
  proposal is in [plan/16](plan/16-ADVERSARIAL-REVIEW-2026-11-07.md)
  (BER-06). Until then, the trust in a release is the trust in this
  GitHub repository and account.

## Reviews

Changes that touch process creation, IPC, file descriptors, shared memory,
the GPU process, the network service or sandbox setup are marked
`security-review: required` in their patch header and need a second
reader before they ship. External reviews are welcome: the first, an
adversarial assessment of 7 November 2026, and what changed because of it,
is recorded in [plan/16](plan/16-ADVERSARIAL-REVIEW-2026-11-07.md), and
future ones will be recorded the same way.

## Dependencies

What Beryllium is built from is pinned in the repository: the Helium
commit (the `helium` submodule, with its Chromium version), the FreeBSD
ports patch set (`freebsd/ports/www/beryllium/files/IMPORTED-FROM`) and
the GitHub Actions used by CI (by commit). Dependabot watches the Actions
(`.github/dependabot.yml`). The Python and Node tools used to generate
artwork and check the repository take their libraries from FreeBSD
packages or the developer's system and are not part of the browser.
