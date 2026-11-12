# Adversarial review of 7 November 2026: findings and answers

**Review:** an external adversarial assessment of the repository at commit
`f3edd4c` (the merge of the 0.20.3.8 inputs; two later commits on the
development branch, the kqueue `CAP_EVENT` fix and the receive-side rights
helper, were not in it). The reviewer reconstructed three Chromium files
through the patch layers, compiled the lockdown's descriptor code against
stubbed system calls, ran the suite's sandbox test methods against
controlled observations, and ran the installer and release tools in dry-run
mode. No FreeBSD machine, no built browser, no exploit. The reviewer's own
summary: no remote code execution, sandbox escape or compromised package
was demonstrated; the findings are implementation weaknesses in the
experimental lockdown, an assurance gap in its tests, and known
confinement, distribution and hardening gaps that the repository already
discloses.

This document records each finding, whether it holds, what changed because
of it (build 0.20.3.10), and what remains. The matrix rows named below
carry the status.

| ID | Finding | Holds? | Answer |
|---|---|---|---|
| BER-01 | Default child processes lack OS confinement | yes, by design for now | unchanged; the gate that must pass before default-on is now strict (BER-04) |
| BER-02 | Descriptor admission broader than intended authority | yes | fixed in 0.20.3.10: files only under the assets directory, sockets only as unnamed Mojo pairs, bounds-checked table |
| BER-03 | A failed stdio rights limit was not fatal | yes | fixed in 0.20.3.10: the lockdown fails and the renderer ends |
| BER-04 | Sandbox tests accept missing or partial confinement | yes | fixed: with the lockdown requested the tests are a gate; the three negative scenarios now fail (unit-tested) |
| BER-05 | The startup sweep is not a lifetime policy | yes | receive-side limits were already in `a253314` (defence in depth); the sender-side boundary is written for 0.20.3.13 (the browser cuts before `sendmsg`); the GPU process's sends to renderers remain receiver-limited |
| BER-06 | One release trust channel; no source binding | yes | publish-release now refuses a package whose build manifest does not match the checkout; signing written on 12 November 2026 with the owner's key (plan/18 section 5), the first signed release to be 0.20.3.19 |
| BER-07 | Assurance coverage short of a hardened-release claim | yes | documented where the observation methods stop; no claim is made beyond them |

## BER-01: default child processes lack OS confinement

Correct, and stated in the README's sandbox table. The renderer lockdown
stays opt-in until the strict gate (BER-04) passes on every run and the
remaining increments of [plan/14](14-RENDERER-SANDBOX.md) land: sender-side
rights, kernel attestation of each renderer before it gets a navigation,
then default on and fail closed. GPU, network, audio and other utility
processes get their own policies afterwards (plan/06 section 3.3) and are
not covered by "renderers confined".

## BER-02: descriptor admission

The lockdown admitted any read-only regular file with a path and any
socket, by type alone. The reviewer's stubbed harness showed a read-only
`/tmp` canary file and an unclassified socket being kept with their kind's
rights. True: `cap_rights_limit` cannot take back what an existing
connection or a readable secret already gives.

**Changed** (`patches/security/beryllium-capsicum-renderer.patch`,
`patches/security/beryllium-descriptor-rights.patch`):

- A read-only file is admitted only when the path the kernel reports for
  it is under the browser's assets directory (`base::DIR_ASSETS`,
  `/usr/local/share/beryllium/` in the package). That is every file a
  renderer legitimately holds at the lockdown point (resource paks, the V8
  snapshot, ICU data); fonts arrive later through the font service. A file
  elsewhere, or one whose path the kernel cannot give, ends the lockdown
  with its name in the log. The suite's policy
  (`berytest/capsicum.py`, `allowed_file`) demanded this already; the
  implementation now matches it.
- A socket is admitted only in the shape of a Mojo transport: AF_UNIX,
  stream or seqpacket, not listening, bound to no path and connected to no
  path, read from `kinfo_file` at the lockdown (`kf_sock_domain`,
  `kf_sock_type`, `kf_sa_local`, `kf_sa_peer`) and from `SO_DOMAIN`,
  `SO_TYPE`, `SO_ACCEPTCONN`, `getsockname` and `getpeername` for a socket
  received afterwards. A network socket or one connected to a named
  service (a display, a daemon) ends the lockdown or, received later,
  loses every right. (The kernel puts the domain's name, `local`, in a
  socket's `kf_path`; it is not a path and is not used.)
- Each `kinfo_file` record is bounds-checked (at least up to `kf_path`,
  within the buffer); a malformed table ends the lockdown. The data comes
  from the kernel, so this guards against an ABI mismatch, not an attacker.

**Still open:** this is admission by place and shape, not a manifest of
expected descriptors with purpose and provenance (S-REN-04's "committed
allowlist"), and a trusted resource's path alone does not prove the object
behind it. Checking file identity (device and inode of the installed
resources, recorded at build time) is a candidate for the allowlist
increment. The reviewer's native acceptance test, a canary file, a
connected loopback socket and an unrelated unix socket injected into a
renderer before the lockdown, needs an instrumented build and is listed in
plan/14 for the FreeBSD machine.

## BER-03: a failed stdio rights limit was not fatal

`caph_limit_stdio()` failing was logged and the lockdown went on. Fixed:
it is now a violation ("the standard streams could not be limited"); the
renderer ends like any other lockdown failure. The helper ignores closed
streams (`CAPH_IGNORE_EBADF`), so a renderer started with a stream closed
still locks down. The launcher gives renderers `/dev/null` as standard
input; standard output and error are the browser's log or terminal, which
keep write access to that one object, as the reviewer notes. A dedicated
bounded logging pipe per child is a later refinement, not planned for a
specific build.

## BER-04: sandbox tests accepted missing or partial confinement

Reproduced by the reviewer with the suite's own methods: the capability
mode test passed with every process unconfined; the policy test skipped
with no renderer confined and passed with one renderer confined and one
not; an unreadable renderer was skipped while another passed.

**Changed** (`freebsd/tests/browser/tests/test_50_sandbox.py`,
`berytest/capsicum.py`): the tests have two modes, decided by the run's
arguments. With the lockdown requested
(`--browser-arg=--enable-features=BerylliumCapsicumRenderer`) they are a
gate: every renderer must be in capability mode by the kernel's answer,
every renderer's descriptors and rights must be readable, and any
unconfined, unreadable or out-of-policy renderer fails the test. Without
it they survey: they record what the kernel says and skip what they cannot
observe, as before. The suite README says which mode a run is in, and that
the gate needs `security.bsd.unprivileged_proc_debug=1`.

`freebsd/tools/tests/test_sandbox_gate.py` runs the suite's methods
against controlled observations, including the reviewer's three
scenarios, and checks that each fails under the gate and behaves as
before without it. CI runs it on every push.

**Still open:** the gate covers renderers present when the test runs; the
reviewer's repetition across renderer creation, cross-site navigation and
process replacement, and per-descriptor fcntl and ioctl assertions, are
for the native suite on the FreeBSD machine (R-TST-02).

## BER-05: the startup sweep is not a lifetime policy

Correct for the assessed commit. `a253314` (in 0.20.3.9, before the
review was received) added `base/posix/capsicum_rights`: the message pump
cuts its kqueue and eventfd at creation, and a process in capability mode
cuts every descriptor it receives over Mojo to its kind's rights, removing
every right from one outside the policy. As the patch header says, that is
defence in depth: a compromised renderer can call `recvmsg` itself. The
boundary is the sender: the browser limiting what it sends to a renderer
before sending, which is increment 5 in plan/14 (S-IPC-01). The reviewer's
inventory of browser, GPU and network to renderer transfers, and the
negative cases (unsolicited directories, over-privileged files and
sockets, unsealed or wrong-type shared memory, inconsistent lengths), are
the test plan for that increment.

**Done for 0.20.3.13 (9 November 2026):** the browser registers each
renderer it launches with the lockdown on as a confined peer and Mojo's
transport cuts every descriptor bound for one to its kind's rights before
`sendmsg()` (`patches/security/beryllium-sender-side-rights.patch`;
plan/14 increment 5). A writable file handed over on purpose (a File
System Access sync access handle) gets a kind of its own on both sides
instead of losing every right. Still receiver-limited only: what the GPU
process sends a renderer over the transport the browser introduced
between them. Still to do: a verification that the sender alone suffices,
with the receiver's limit switched off in a development build.

## BER-06: one release trust channel, no source binding

Two parts.

**Source binding, fixed.** `publish-release` created a release at the
current commit for whatever package it was given. Every package carries
`BUILD-MANIFEST.json`, written by the port when it was built: the version,
the Chromium and Helium versions, the imported BSD patch set and the
SHA-256 of every Beryllium patch. `freebsd/tools/check-provenance` now
compares that manifest with the checkout (and with the package's own
version from `pkg query`), and `publish-release` refuses a package that
was not built from the commit it is about to name, or that carries no
manifest. The manifests are published with the release as
`BUILD-MANIFEST-FreeBSD-<version>-amd64.json`, so anyone can compare a
package's digest, inputs and the named commit. Tests:
`freebsd/tools/tests/test_install_sh.py` (`CheckProvenanceTests`,
`PublishReleaseTests`).

**Publisher authentication, written 12 November 2026.** What follows is
the proposal as first made. What was built differs where
[plan/18](18-REMAINING-WORK.md) section 5 found it short: the signed file
is a manifest, `RELEASE`, that names the release as well as listing the
digests, so that an old signed release cannot be passed off as another;
the installer checks the tag, the version and against a downgrade; and
`publish-release` verifies its own work with the installer before and
after uploading. The keys are in `freebsd/release-keys`. The first signed
release is to be 0.20.3.19.

`install.sh` fetches `SHA256SUMS`
and the package from the same release; an actor able to replace release
assets can replace both. A signature over `SHA256SUMS` with a key that is
not on GitHub changes that. Proposal, pending the owner's decision on the
key:

```sh
# Once, on the owner's machine (not the build jail, not GitHub), with a
# passphrase:
ssh-keygen -t ed25519 -f ~/.ssh/beryllium-release -C "Beryllium release signing"

# In the repository: the public key, and an allowed_signers line
#   release@beryllium namespaces="beryllium-release" ssh-ed25519 AAAA...

# At each release, publish-release signs the checksum list:
ssh-keygen -Y sign -f ~/.ssh/beryllium-release -n beryllium-release SHA256SUMS
#   -> SHA256SUMS.sig, uploaded with the release

# install.sh, which users fetch from the repository, verifies before
# checking the package's digest:
ssh-keygen -Y verify -f allowed_signers -I release@beryllium \
    -n beryllium-release -s SHA256SUMS.sig < SHA256SUMS
```

`ssh-keygen` is in the FreeBSD base system, so the installer needs nothing
new. Trust bootstrap: the key reaches users through the repository (a
commit in visible history), the package through the release assets;
replacing the assets alone no longer suffices, and replacing the key is a
visible commit. An attacker with write access to the repository could do
both, which is why the key must not be a secret of the repository or of
CI, and why the destination remains a signed `pkg` repository with the
key off the build host (B-PKG-07, plan/11 section 5). Rotation: a new
`allowed_signers` line with a validity window, the old key kept for the
releases it signed. Rollback policy (an old release installed on purpose
against a newer one) is separate and not yet written.

## BER-07: assurance coverage

Each point is correct about what the evidence covers; the repository
should say so where the evidence is cited, and now does.

- **CI** runs the Capsicum oracle on FreeBSD, not a Beryllium build, and
  the browser harness on Linux against the runner's Chrome with
  `--no-sandbox` (a harness setting for that runner, not the launcher).
  Native results come from the owner's machine and are recorded per
  build in the matrix with "owner, <build>, <date>". A FreeBSD test
  machine is R-TST-06.
- **Imported BSD patches:** 217 of 1,696 touch security paths and none has
  a review record; `import-bsd-patches check` reports this without
  failing (S-SUP-01). Launch, IPC, file system, shared memory and sandbox
  paths first, recorded against content hashes, is the order to take.
- **Privacy tests** observe a local recording proxy: HTTP(S) that the
  browser sends through the proxy it was given. They do not see DNS, UDP
  (QUIC) or anything that bypasses the proxy. The suite README and the
  matrix rows now say so. Capture at an isolated network boundary is the
  stronger test and belongs with the FreeBSD test machine.
- **First run:** the harness starts with `--no-first-run` and sets
  consent preferences directly; the onboarding flow itself is not
  replayed.
- **Allocator hardening** (`use_allocator_shim=false`,
  `use_partition_alloc_as_malloc=false`, `enable_backup_ref_ptr_support=false`
  in `flags.freebsd.gn`, inherited from the FreeBSD port): recorded in
  every build manifest, not enabled; the review names it the main
  hardening deficit. Feasibility and performance on FreeBSD are to be
  measured before changing (S-SUP-02).

## Observations the reviewer listed as worth keeping

Closed inherited descriptors (S-IPC-01), sealed anonymous shared memory
with limited twins (S-SHM-01, S-SHM-02), the honest GPU sandbox status,
commit-pinned CI actions with read-only permissions, and services off by
default. Two of the reviewer's smaller notes are also answered in
0.20.3.10: the descriptor table walk now checks record sizes (BER-02),
and the sweep's tolerance of `EBADF` stays, with the comment that the
lockdown runs on the main thread before the renderer's other threads
start; a stress test of descriptor churn during the sweep is for the
native suite.

## First build with the answers: 0.20.3.10 (7 November 2026)

The owner built 0.20.3.10 and ran the suite without the lockdown, with
it, and the Capsicum survey with it, all with
`security.bsd.unprivileged_proc_debug=1`.

- **BER-02, admission:** every renderer locked down with the tighter
  rules (no file outside the assets directory was in the way, as the
  0.20.3.8 survey predicted), every kind in the survey is allowed, and the
  received sockets are cut. Two sockets per renderer kept every right.
  The first explanation given here, that the IO thread was already
  receiving Mojo messages during the sweep, was wrong: `RendererMain()`
  enables the sandbox before `RenderThreadImpl` exists, so the reviewer's
  question "is startup single-threaded?" is answered yes by Chromium's
  ordering, and from 0.20.3.13 the lockdown logs the thread count at that
  point and the gate requires one. (Until 12 November 2026 the gate read
  the last 200 lines of that log, so it required one of the three or four
  renderers whose reports stood there, not of all: plan/14 has the
  account.) The two sockets were pairs the renderer
  made itself after the lockdown (0.20.3.11, 0.20.3.12). For 0.20.3.11 the
  lockdown turns the receive-path limits on before the snapshot
  (`ExpectConfinement()`) as a precaution, and `base::UnixDomainSocket`'s
  receive path (sandbox IPC replies carrying font files) is limited like
  Mojo's.
  0.20.3.11 (8 November 2026) confirmed the window closed and showed the
  two remaining sockets to be ones the renderer creates itself with
  `socketpair()`, one end sent to the browser (unix stream, one blocking
  and one not, as `base::SyncSocket` and `mojo::PlatformChannel` make
  them). A new socket has every right; from 0.20.3.12 every socket pair a
  confined process creates is cut to a transport's rights at creation,
  and 0.20.3.12 (released 8 November 2026) shows them cut, made on the
  renderer's main and compositor threads. With `unprivileged_proc_debug=1`
  the same day, every renderer the suite could read held no descriptor
  outside the policy.
- **BER-03, stdio:** no failure; every renderer locked down.
- **BER-04, the gate:** it worked as intended once and once too well: the
  policy test failed on a renderer the browser had just launched and that
  had not yet reached its lockdown point. A renderer is listed by the
  browser before it is confined, so the tests now give a listed renderer
  five seconds to get there; one that is still unconfined after that, or
  alive and unreadable, fails the gate, one that ended is not counted.
  The unit tests cover these cases.
- **New observation, closed:** the rendering test's default canvas read
  back `18,52,87` for `#123456` under the lockdown (86 expected; 86 in
  0.20.3.8 under the lockdown). The lockdown's log showed no refused
  descriptor and the GPU process's report was identical; with 0.20.3.11
  (8 November 2026) three rendering runs, with and without the lockdown
  and with the 2D canvas forced onto the CPU, all read 86 on both the
  default and a CPU-side canvas. The 87 was a one-off in the GPU readback;
  the test keeps the CPU canvas exact and allows the GPU canvas one level,
  recording the value.

## What this review did not establish, and we do not claim

No exploit, escape or compromised package was demonstrated, and none is
disproved by this document. The lockdown is still experimental and off
by default; the README's sandbox table is unchanged. The changes above
are inputs to build 0.20.3.10 and are not compiled or run until the
owner builds it; the matrix rows will carry the results.
