# Beryllium: Testing and Verification Plan

**Status:** Draft plan, no code written
**Date:** 18 October 2026
**Implements:** spec section 13 (verification plan and acceptance criteria)

---

## 1. Principles

- Every claim in the security and privacy documents maps to a test that can
  fail. A restriction that is configured but not tested is listed as
  "configured, untested" in the release notes (spec 2.3.5).
- Tests assert the behaviour the FreeBSD kernel actually produces (errno
  values, signal delivery, `cap_getmode` results) on each supported branch,
  not what documentation says should happen.
- Negative tests (an action is denied) are weighted equally with positive
  tests (the browser still works).
- Nothing in CI logs may contain page content, URLs beyond the fixed test set,
  cookies or profile data.

## 2. Test suites and where they live

```text
freebsd/tests/
  capsicum-standalone/   # C programs, no Chromium: kernel behaviour oracle
  sandbox/               # drives a built Beryllium; renderer/utility confinement
  privacy/               # network capture scenarios and flag drift checks
  functional/            # browser feature smoke tests
  resources/             # exhaustion tests, run in a disposable jail
  build/                 # patch application, manifest and plist checks
```

### 2.1 Capsicum standalone oracle (`capsicum-standalone/`)

A small set of C programs built with the base toolchain, run before any
browser test, that record on the current kernel:

- `cap_enter()` succeeds and `cap_getmode()` reports 1.
- `open("/etc/passwd")`, `open("~/.ssh/...")`, `open("/tmp/x", O_CREAT)` fail
  with `ECAPMODE` in capability mode.
- `openat(dirfd, "sub/file")` works with `CAP_LOOKUP|CAP_READ`; `..` escape
  fails; `openat(dirfd, "/abs")` fails.
- `socket(AF_INET)` behaviour, `connect()` and `bind()` fail with `ECAPMODE`;
  `send`/`recv` on a pre-connected socket still work (this is the "inherited
  socket conveys authority" case the spec warns about).
- `kill()` of an unrelated pid, `kill()` of self, `sigqueue()` (the
  `FreeBSD-SA-26:28.capsicum` case), `ptrace()` of an unrelated same-user
  process (CAPENABLED in `syscalls.master`; whether it is restricted to self
  is unconfirmed and this test decides it), `procctl()` (expected `ECAPMODE`,
  which is why trace-disable must precede `cap_enter`),
  `pdfork()`/`pdkill()` behaviour.
- `/dev/fd` listing with and without `fdescfs` mounted (decides whether
  upstream `CloseSuperfluousFds` is effective on this system).
- `connectat()` to a Unix socket beneath a directory capability with
  `CAP_CONNECTAT` succeeds; `connect()` to the same path fails.
- `PROC_TRAPCAP_CTL` delivers `SIGTRAP` with `TRAP_CAP` on a denied call
  (the devel-build diagnostic).
- `shm_open(SHM_ANON)` and `memfd_create()` succeed; named `shm_open()` fails.
- `mmap` with `PROT_EXEC` on a descriptor limited to `CAP_MMAP_R` fails;
  anonymous `mmap` with `PROT_EXEC` (V8, WebAssembly) is unaffected.
- `memfd_create()` plus `F_ADD_SEALS` works; a `dup` limited to
  `CAP_READ|CAP_MMAP_R|CAP_FSTAT|CAP_SEEK` cannot be mapped writable, and
  `cap_rights_get()` reports the limited set while `fcntl(F_GETFL)` still
  reports `O_RDWR` (the check the shared-memory design depends on).
- `cap_rights_limit`, `cap_ioctls_limit`, `cap_fcntls_limit` enforcement:
  reads on a write-only capability fail with `ENOTCAPABLE`, an ioctl outside
  the allowlist fails with `ENOTCAPABLE`, `F_SETFL` outside the fcntl allowlist
  fails.
- `sysctl` read of `kern.proc.*` in capability mode (needed by Chromium's
  process metrics code; the oracle records whether it is permitted so the
  renderer policy can route it through a broker if not).
- `dlopen()` of a library by path fails in capability mode (motivates
  pre-loading in `PreinitializeSandbox`).
- `getaddrinfo()` fails without `cap_dns`; `localtime()` works only if
  `/etc/localtime` was opened before entry (motivates timezone pre-caching).

Output is a JSON table per kernel. The sandbox suite loads the table for the
running kernel and uses it as the expected-errno source, so a kernel behaviour
change surfaces as an oracle diff rather than as a mysterious browser failure.

### 2.2 Sandbox suite (`sandbox/`)

Runs against an installed Beryllium package, as an unprivileged user, in a
throwaway home directory seeded with canary files (`~/.ssh/id_canary`,
`~/Documents/canary.txt`, a canary cookie database in a second profile).

Mechanisms:

- A test-only renderer hook (compiled only into `beryllium-devel`) that, on a
  command-line switch, performs a scripted list of forbidden operations after
  sandbox initialisation and writes a structured result to a descriptor
  provided at launch. The production build does not contain the hook; the
  production build is tested by observation (below).
- Observation from outside using `procstat -f` (descriptors per process),
  `procstat -S`/`-c`, `sockstat`, `procstat -v` (mappings) and `fstat`,
  plus the kernel's capability-mode flag per process (`procstat -s` shows
  `C` in the flags column for processes in capability mode on recent
  branches; the exact field is confirmed in Phase 0).

Checks (each one is a named test with the spec requirement it covers):

| Test | Spec | Method |
|---|---|---|
| Every renderer is in capability mode after page load | 6.1.1 | `procstat` flag on every `--type=renderer` pid |
| Every utility process of a class claimed sandboxed is in capability mode | Phase 3 | same, per `--type=utility --utility-sub-type=...` |
| Renderer descriptor set equals the allowlist | 6.1.2, 6.2 | `procstat -f` output normalised and diffed against `freebsd/sandbox/renderer-fds.json` |
| No renderer holds a socket other than its Mojo channel socketpair | 6.1.5 | `procstat -f` type column; `sockstat -u` |
| No renderer holds a directory descriptor outside the allowlist | 6.1.4 | `procstat -f` |
| No renderer holds any profile, cookie, cache or downloads descriptor | 5.1 | path column of `procstat -f` |
| Rights on each retained descriptor match the policy | 6.1.3 | `procstat -f -C` capability rights column |
| Forbidden opens fail with the oracle's errno | 13.1 | devel hook |
| Socket creation and connect fail | 13.1 | devel hook |
| Signals to unrelated processes fail, including `sigqueue` | 13.1 | devel hook; target is a sleeper process owned by the same user |
| `ptrace` of the browser process fails | 13.1 | devel hook; also `procctl(PROC_TRACE_CTL)` status read from outside |
| A renderer cannot connect to the X11 or Wayland socket directly | 7.1 | devel hook attempts `connect()` to the display socket path |
| Sandbox setup failure is fatal and logged | 6.1.1, 6.1.10 | inject failure through a devel-only switch; assert process exits non-zero with the structured log line and the browser shows the sad-tab, not a working page |
| `--no-sandbox` has no effect in the production package | 6.1.8 | launch with the switch; assert renderers are still in capability mode; assert the switch is absent from `strings` output of the production binary's switch table |
| Child of a renderer stays confined | 6.1.9 | devel hook forks and checks `cap_getmode` in the child |
| New descriptor introduced by an update is caught | 6.2 | the allowlist diff test above, run in CI on every Chromium bump |
| `chrome://sandbox` reports the real status | Phase 2 | page text compared with the observed state |

### 2.3 Privacy suite (`privacy/`)

Defined in [07-PRIVACY-INVARIANTS-PLAN.md](07-PRIVACY-INVARIANTS-PLAN.md)
section 6. Infrastructure: a VNET jail for the browser, a second jail on the
same bridge running `unbound` with query logging and `tcpdump -w` on the
bridge, and a fixed local web server with the test page set. The comparison
script produces the endpoint tuple set and the diff against the baseline.
Additional static checks:

- GN args emitted by `gnargs-from-flags` contain no privacy-tagged key from
  the FreeBSD fragment.
- All Helium patch files listed in `helium/patches/series` applied (the stage 3
  log shows zero skipped); a skipped Helium patch is a privacy failure by
  definition.
- The installed uBlock component is the Helium fork at the version in
  `deps.ini`, with Helium's filter defaults and CNAME uncloaking enabled
  (read from the component's manifest and settings on first run).

### 2.4 Functional suite (`functional/`)

Driven through the DevTools protocol or chromedriver (the port already builds
`chromedriver` under the `DRIVER` option). Coverage list from spec 13.3: clean
startup, profile creation and migration from Helium Linux profile layout,
multiple tabs, site isolation (one renderer per site, verified by `procstat`),
navigation, downloads to the brokered downloads directory, user-approved file
open through the GTK chooser, cookies and site storage, fonts including CJK
and emoji fallback, audio and video playback, hardware acceleration where
available, extension install through the proxy, uBlock blocking on the test
page set, CNAME uncloaking on a crafted test domain, private browsing, printing
to PDF and to CUPS, clipboard, Wayland and X11, renderer crash recovery,
package upgrade and removal.

Each functional test runs twice when relevant: once with the sandbox and once,
in `beryllium-devel` only, with the sandbox disabled, so that a failure can be
attributed to confinement or to the port itself.

### 2.5 Resource suite (`resources/`)

Spec 13.5. Run in a disposable jail with `rctl` accounting enabled:

- CPU loop page: which limit fires (`rlimit` CPU time versus `rctl pcpu`),
  which process dies, whether the rest of the browser survives.
- Memory growth page: `RLIMIT_DATA` (already set by the BSD stub via
  `LimitAddressSpace`) versus `rctl memoryuse`; distinguish allocation failure
  from a terminated renderer; confirm the profile databases are consistent
  afterwards (`sqlite3 ... "pragma integrity_check"` on the copied profile).
- Descriptor exhaustion and process exhaustion through `window.open` storms.
- Each run records the baseline numbers the resource profiles in
  [06-SECURITY-MODEL.md](06-SECURITY-MODEL.md) are calibrated from.

### 2.6 Build suite (`build/`)

- Stages 1 to 6 apply with zero failures and a recorded fuzz count.
- `make makesum`, `make check-plist`, `portlint`, `make stage-qa` pass.
- Poudriere bulk build succeeds on every supported branch.
- The build manifest is emitted and contains: Chromium version, Helium commit,
  Beryllium commit, FreeBSD ports commit used for the BSD import, OpenBSD ports
  commit if used, GN args, compiler and linker versions, patch list with
  hashes, distfile hashes.
- Reproducibility: two builds from the same inputs on two builders are
  compared; the plan accepts that Chromium is not bit-reproducible without
  further work and records the diff size as a metric rather than a gate.

## 3. Release gates

A release is blocked if any of the following is true (spec 13.6, restated as
checks):

| Gate | Check |
|---|---|
| Chromium revision and security status known | manifest present; Chromium release notes for that version reviewed and linked |
| Renderer capability mode demonstrated | sandbox suite test 1 passes on every supported branch |
| Descriptor allowlist complete | sandbox allowlist diff test passes, and every entry in the allowlist has a rationale |
| No fallback to unrestricted renderer | failure-injection test passes |
| Privacy unchanged or reviewed | privacy diff empty or annotated |
| Kernel advisories addressed | preflight script checks `freebsd-version -k` against the advisory list in `freebsd/ADVISORIES.md` |
| Reproducible from clean source | Poudriere build from a clean jail succeeds |
| Licences and attribution present | licence manifest check passes |

## 4. Test infrastructure needed

| Item | Purpose | Notes |
|---|---|---|
| Build host: amd64, 32 GB RAM or more, 100 GB free, fast SSD | Poudriere builds; the port asks for 8 GB minimum for Release and 16 GB for LTO, but Chromium links comfortably only with more | one host suffices for Phase 0 to 2 |
| Poudriere jails for each supported branch | clean builds | `-CURRENT` jail optional |
| Test VM or bhyve guest per branch, with a desktop session (Xorg and a Wayland compositor) | sandbox and functional suites need a display | can be the same host under bhyve |
| Capture jail pair (browser VNET jail plus logging jail) | privacy suite | |
| A CI runner that can run Poudriere and bhyve | nightly builds and the per-update regression run | GitHub Actions cannot run FreeBSD natively; use a self-hosted runner or a FreeBSD VM action with a long timeout for the light checks only |
