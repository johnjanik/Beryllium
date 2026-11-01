# Capsicum oracle and red-team probes

`cap-oracle` records what the running FreeBSD kernel actually lets a process
in capability mode do. It needs no Chromium. The sandbox suite will use its
output as the expected-result table for each kernel, so a kernel change
shows up as a diff here before it shows up as a browser bug
([08](../../../plan/08-TESTING-AND-VERIFICATION.md) section 2.1,
[12](../../../plan/12-WORK-PLAN-AND-RED-TEAM.md) sections 5 and 6.2).

## Run it

As an ordinary user (not root; root bypasses some of the limits measured):

```sh
sh freebsd/tests/capsicum-standalone/run-oracle.sh
```

This builds with the base `cc`, runs all probes, and writes
`freebsd/results/oracle-<kernel release>-<date>.json`. The summary and every
`exposed`, `broken` or `error` probe are printed to stderr.

Other options:

```sh
make -C freebsd/tests/capsicum-standalone
./freebsd/tests/capsicum-standalone/cap-oracle -l          # list probes
./freebsd/tests/capsicum-standalone/cap-oracle -o proc.    # only one area
```

## How a probe works

Each probe runs in its own forked child: optional setup before
`cap_enter()` (for example opening a socket or setting an rlimit), then
`cap_enter()` (checked with `cap_getmode()`), then one action. The child
reports a fixed-size result over a pipe. A probe that hangs is killed after
10 seconds (60 for the sysctl sweep).

The parent sets up a fixture first: a temporary directory with a canary
file, a subdirectory, a symlink pointing at `/etc/passwd`, a listening Unix
socket, and two sleeping processes that stand in for the unconfined browser
(one of them with `PROC_TRACE_CTL_DISABLE`). Everything is removed at the
end.

## Reading the results

| `expect` | Meaning |
|---|---|
| `deny` | The secure outcome is that the kernel refuses the action |
| `allow` | The sandbox design depends on the action working |
| `record` | No expectation; the kernel's behaviour is recorded |

| `verdict` | Meaning |
|---|---|
| `ok` | The outcome matched the expectation |
| `exposed` | A `deny` probe was allowed. These are the red-team findings: kernel behaviour the Beryllium policy has to work around (for example RT-01, readable host identifiers) |
| `broken` | An `allow` probe was refused: a design assumption does not hold on this kernel |
| `info` | A `record` probe |
| `error` | The probe could not set itself up, crashed or timed out |

`kernel_attestation` checks RT-04: whether the parent can see a child's
capability mode through `kinfo_proc.ki_cr_flags` (`KI_CRF_CAPABILITY_MODE`),
the way the browser would verify its children without trusting them.

`caprd_sysctls` lists every sysctl leaf that could be read from capability
mode, and the subset whose names look like identifiers. Values are never
recorded, only names and sizes.

The exit status is non-zero if any probe is `broken` or `error`. `exposed`
probes do not fail the run; on current kernels several are expected.

## Expected `exposed` results on FreeBSD main (from kernel source, 1 Nov 2026)

These are predictions to be confirmed by the first run:

- `id.kern_hostuuid`, `id.kern_hostid`, `id.kern_hostname`,
  `id.kern_domainname`, `id.kern_boot_id`: nodes are `CTLFLAG_CAPRD` (RT-01).
- `proc.kevent_proc_other`, `proc.kevent_proc_init`: `filt_procattach()`
  checks only `p_cansee()` (RT-02).
- `net.socket_route`, possibly `net.socket_netlink` and
  `net.netlink_getaddr` (RT-02).

Results for the supported stable branches come from CI
(`.github/workflows/freebsd-checks.yml`, artifacts `oracle-freebsd-14` and
`oracle-freebsd-15`); 16-CURRENT results come from the maintainer's
machine.

## Build check without FreeBSD

The code is compile- and link-checked against a FreeBSD 16.0-CURRENT
sysroot (`base.txz`) with
`clang --target=x86_64-unknown-freebsd16.0 --sysroot=... -Wall -Wextra -Wpedantic -Werror`.
That catches header and API mistakes; it does not replace running it.
