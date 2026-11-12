# 18. The seven remaining items: deep dives, work plans, tests and red-team plans

**Snapshot:** 11 November 2026, after release 0.20.3.17 (commit `41e1ca7`).
**Scope:** the seven entries under "Still to finish" in the README. For
each: where it stands, what the code says, the design, the work in order,
how it is tested, how it is attacked, and when it counts as done.
**Status of this document:** a plan. Nothing in it is built. Where a
statement rests on source reading, a report or a trial, it says which.
**Decisions:** the owner decided the seven open questions on 11 November
2026; they are recorded in section 8.3 and in the sections they change.

How the facts were gathered:

- *Source:* Chromium 156.0.8078.79 as Beryllium builds it (the FreeBSD
  port's patches, Helium's and Beryllium's applied), file by file with
  `freebsd/tools/patch-workbench`.
- *Reports:* the owner's suite runs on 16.0-CURRENT, the Capsicum survey of
  10 November 2026 for what each process does and holds, and the feature
  matrix for what is recorded.
- *Tried in a cloud session (Linux, 11 November 2026):* the release
  signing commands against seven attack cases (section 5), and a debugger
  making an attached Chromium renderer run system calls (section 0.1).
  Neither has run on FreeBSD yet.

Each section ends with **Done when**, which is the bar for removing the
item from the README. A build costs the owner two to three hours, so the
work is grouped by build in section 8.

## Summary

| # | Item | Matrix rows | Needs a build | Depends on | Owner decision |
|---|---|---|---|---|---|
| 1 | Sender-side cut on every link to a confined renderer | S-IPC-01, S-IPC-03 | yes | 0.1 | decided: renderers never hold a device descriptor |
| 2 | The kernel's word on each renderer, and `beryllium://sandbox` | S-STA-01, S-STA-02, S-STA-03 | yes | none | none |
| 3 | On by default, fail closed | S-REN-09, S-REN-10, S-REN-02, S-HRD-01, S-HRD-03, S-KRN-03 | yes, several | 1, 2, 0.1 | decided: one package; 100 clean runs in a row |
| 4 | The other processes | S-PRC-01 to S-PRC-08, S-DSP-01 | yes, later | 3 for the pattern | which processes get a statement instead of a policy |
| 5 | Signed releases | B-PKG-07, R-REL-01 | no | none | decided: a key file first, a hardware token to follow |
| 6 | Assurance | R-TST-06, S-SUP-01, S-SUP-02, S-SUP-03, S-SUP-05 | spikes | none | decided: the owner's machine, at night |
| 7 | WebGPU | F-GPU-02, F-GPU-03 | small | none | decided: off by default, the opt-in kept, not pursued now |

## 0. Tools the plans share

Three pieces of test equipment recur below. They are worth building
first, because items 1 to 4 are only as good as the attacks they survive.

### 0.1 The debugger as the attacker

A compromised renderer is a renderer running code of the attacker's
choice. The suite can stand in for one without a special build: `lldb`
attaches to a confined renderer and makes it call anything in libc.

*Tried, Linux:* attached to a Chromium 153 renderer, `expression --
(int)open("/etc/hostname", 0)` returned a descriptor, the same call on a
missing path returned -1 with errno 2 read back through the errno
accessor, and `kill(1, 0)` returned 0. The suite already drives `lldb`
on FreeBSD (`ThreadsAtLockdown`, 0.20.3.17), on a pseudo-terminal, with
frames named by `llvm-symbolizer`.

*Not yet verified:* expression evaluation by FreeBSD's `lldb` in a
process that is in capability mode (it allocates in the target with
`mmap`, which capability mode allows), and the errno accessor's name there
(`__error()`).

Plan: a `redteam` group in the browser suite (`run redteam --lockdown`),
needing `lldb` and `security.bsd.unprivileged_proc_debug=1`. For one
confined renderer it runs a table of probes and compares each result with
what the policy says must happen:

| Probe (called inside the renderer) | Must return |
|---|---|
| `open("/etc/passwd", O_RDONLY)`, `openat(AT_FDCWD, ...)`, `stat`, `access`, `readlink` | -1, `ECAPMODE` |
| `socket` then `connect` to 127.0.0.1 and to a unix path; `bind`; `sendto` with an address | -1, `ECAPMODE` |
| `kill(browser pid, 0)`, `sigqueue(browser pid, ...)` (FreeBSD-SA-26:28) | -1 |
| `shm_open` with a name; `mkfifo`; `chdir`; `chroot` | -1, `ECAPMODE` |
| `fork()` | -1 once S-HRD-03 is in; before that, a child that is itself in capability mode |
| `execve`, `fexecve` on every held descriptor | -1 |
| `ptrace(PT_ATTACH, browser pid)`, `procctl` on another pid | -1 |
| `sysctl` writes; reads of `kern.proc.*` for another pid | -1 |
| for every descriptor the renderer holds: the operations its kind does not grant (`ftruncate`, `fchmod`, `fchown`, `ioctl`, `mmap` with `PROT_EXEC`, `openat` beneath it, `connectat`, `bindat`, `cap_rights_limit` to a wider set) | -1, `ENOTCAPABLE` |
| `cap_getmode` | 1 |

The table is data in the suite (probe, arguments, expected errno), unit
tested for its parsing against captured `lldb` output, and every row
cites the matrix row it defends. A probe that succeeds where it must fail
is a release blocker.

Two limits, stated in the report each time: the probes run from a
debugger, so they need tracing to be allowed (see 3.2 on
`PROC_TRACE_CTL`), and they show what the kernel refuses a renderer, not
what a renderer can do with what it is rightly allowed (its Mojo
interfaces), which is IPC review (S-IPC-03) and fuzzing (S-IPC-05).

### 0.2 The standalone policy harness

`freebsd/tests/capsicum-standalone/` already compiles a C program on
FreeBSD 14 and 15 in CI virtual machines and on the owner's 16-CURRENT
(the oracle). The same job can compile Beryllium's own
`base/posix/capsicum_rights.cc`, taken out of the patch with
`patch-workbench` and built against small stubs for `base`, and attack
it directly: no browser build, three FreeBSD versions on every push.

For each descriptor kind (read-only file, writable file, socket, kqueue,
eventfd, pipe, shared memory) and each thing that is not a kind (a
directory, `/dev/null`, a terminal, a device): create one, pass it through
`LimitSentDescriptor`, send it over a socket pair to a child that has
called `cap_enter()`, and have the child try every operation outside the
kind's rights. The child reports per operation; the parent fails on any
success. This is the unit test the sender-side cut has never had.

### 0.3 A switch that turns the receiver's limits off

Feature `BerylliumReceiveSideLimits`, on by default. Off, a confined
renderer does not limit what it receives (`LimitReceivedDescriptor`
returns at once), which is how a compromised renderer behaves. With it
off, every descriptor in every renderer must still be inside the policy
by `procstat -C`, or some sender is not cutting. Plan/16 (BER-05) left
this open as "a development-only build switch"; a runtime feature needs
no second build, and it joins the list of switches the production
package ignores once item 3 removes escape hatches.

The debugger gives the same test without trusting a switch: break on
`base::freebsd::LimitReceivedDescriptor` in the renderer and return from
it at once on every hit. Both are planned; they should agree.

## 1. Sender-side cut on every link to a confined renderer

README: "What the GPU process sends a renderer is cut by the receiver
only." Matrix S-IPC-01, review finding BER-05.

### 1.1 Where it stands

- The browser cuts every descriptor it sends a confined renderer before
  `sendmsg()` (0.20.3.13; `beryllium-sender-side-rights.patch`). In the
  two recorded lockdown runs of 0.20.3.17 it cut 1 to 71 and 1 to 83
  descriptors per renderer, and every descriptor read in a renderer was
  inside the policy.
- The hook is `mojo::core::ipcz_driver::Transport::Transmit()`. It cuts
  when the transport's remote process is a registered confined peer, and
  only the browser's own transports to its children know their remote
  process.
- *Source:* a link between two children is made by the browser in
  `Driver::CreateTransports(existing_transport_from_here_to_a,
  existing_transport_from_here_to_b, ...)` (`driver.cc`). It calls
  `Transport::CreatePair(node_a_type, node_b_type)`, sets the trust bits
  from the two existing transports, and gives a remote process handle
  only to an endpoint that is a broker. The two new endpoints are then
  serialized to A and B. `TransportHeader` carries `destination_type`,
  `is_same_remote_process`, `is_peer_trusted` and `is_trusted_by_peer`.
  Nothing tells B that A is confined.
- *Survey, 10 November:* the README understates the item. One renderer
  held four sockets whose other end was another child: two to the GPU
  process, one to the network service and one to the storage service.
  The audio service held none to a renderer when it was sampled. The item
  is "every child that talks to a confined renderer directly".
- What travels on those links today: shared memory, which is created
  with limited rights by `beryllium-anonymous-shared-memory.patch` and
  keeps them in transit, and sockets. On the owner's NVIDIA machine no
  device descriptor reaches a renderer, because Beryllium keeps video
  frames out of GPU memory buffers there. On Mesa drivers that path is on
  by default and would hand a renderer a device-backed buffer, which both
  sides refuse today (no kind for it). Nobody has run the lockdown on a
  Mesa compositor, so whether that breaks video there is unknown.

### 1.2 Design

**A "peer is confined" bit on the transport, set by the browser.**

1. `driver.cc`, `CreateTransports`: the browser knows both pids
   (`our_transport_to_a->remote_process()` and `..._to_b`). If A is a
   registered confined peer, mark `transport_from_b_to_a` (the end B will
   hold) as leading to a confined peer; likewise for B.
2. `transport.h/.cc`: a member `peer_confined_`, a byte for it in
   `TransportHeader`, written in `Serialize()` and read in
   `Deserialize()`.
3. `Transport::Transmit()`: cut when `peer_confined_` is set, as it
   already does when the remote pid is a registered peer.
4. `LimitSentDescriptor()` takes the cut without needing a pid (the
   child does not know it), and logs which process type did the cutting.

Who may set the bit. It is only ever set by the browser and read by the
child the browser hands the endpoint to. A forged *set* bit makes a
sender cut more than it needed to: breakage at worst, never more rights.
A forged *clear* bit would need the renderer to alter a message the
browser sent to another child, which it cannot. `Deserialize()` already
distinguishes a trusted source; the bit is honoured only from one, and
otherwise treated as set (cut when in doubt).

**Renderers never hold a device descriptor under the lockdown.** Rather
than invent a `kGpuBuffer` kind with an ioctl allowlist for buffers
nobody has measured, the lockdown turns GPU memory buffer video frames
off on every driver, as Beryllium already does for NVIDIA. Cost: one copy
per video frame on Mesa. This keeps the renderer policy at seven kinds
and removes the largest unknown. It trades performance on hardware the
project cannot test yet, so it was the owner's to decide. **Decided, 11
November 2026: never.** `freebsd/tools/gpu-probe` says whether a machine
would use Mesa under FreeBSD, to find one to measure the cost on.

**The inventory becomes a committed table.** The survey already names
the process at the other end of every socket a renderer holds. A new
section of the survey report lists, per renderer, each direct link and
the peer's type, and plan/14 records the table per build. A link to a
process type that is not in the table fails the gate.

### 1.3 Work plan

1. Standalone harness (0.2) for `LimitSentDescriptor`: no build, runs in
   CI. Do this first; it tests the code that already ships.
2. Patch: the bit, as above. One patch, three files, plus the helper's
   signature. Compile check of `transport.cc` and `driver.cc` alone is
   not practical (too many dependencies), so the first compile is the
   build; keep the change small and mirror the existing trust-bit code
   line for line.
3. Patch: feature `BerylliumReceiveSideLimits` (0.3) in
   `capsicum_rights.cc`.
4. Patch: no GPU memory buffer video frames when the lockdown is on
   (extend `beryllium-bsd-nvidia-video-frames.patch`'s condition).
5. Suite: count the cuts by sending process type from the log; the link
   inventory; `test_sender_alone_keeps_the_policy`, which starts a
   browser with the lockdown on and the receive limits off and requires
   the policy on every descriptor of every renderer.
6. `redteam` probes for descriptors (0.1): the per-descriptor rows.

### 1.4 Tests

- Unit: the survey's link table and the cut counter (Python, fixtures
  from real logs); the harness's own result parsing.
- Standalone, FreeBSD 14, 15, 16: every kind and every non-kind through
  `LimitSentDescriptor` into a confined child.
- Suite, lockdown on: every renderer within the policy with the receive
  limits on (today's test) and off (new); at least one cut logged by each
  process type that has a link; no link to an unlisted type.

### 1.5 Red team

| Attack | How it is tried | Must hold |
|---|---|---|
| The renderer stops limiting what it receives | feature off; and the debugger returning early from the receive function | every descriptor still within its kind's rights |
| A child sends a renderer something outside the policy (a directory, a device, a writable file) | standalone harness, each non-kind | arrives with no rights at all, and is logged |
| The renderer forges the bit | read `Deserialize()`: a bit from an untrusted source is ignored; unit-test the header parse in the harness if it can be isolated | no sender ever cuts less |
| The renderer builds a link of its own to another child and asks for descriptors over it | source reading of which nodes may create transports for others in ipcz, then an attempt with the debugger (`socketpair`, hand one end over an existing interface that carries a handle) | no child sends a descriptor on a link the browser did not make; or the bit defaults to set on any link whose origin is not the browser |
| Descriptors that do not travel over a Mojo transport | list every `sendmsg` with `SCM_RIGHTS` in the tree as built (a search of the build tree on the owner's machine; the workbench fetches single files only) and place each on one side of the boundary | every path from a child to a renderer is in the list and cut |
| An executable mapping of shared memory | debugger: `mmap(..., PROT_EXEC, ..., fd)` on each shared memory descriptor | refused |
| A confined renderer passing a descriptor it holds to an unconfined child, which then uses it with its own authority | review only (S-IPC-03): which interfaces accept a handle from a renderer, and what the receiver does with it | recorded per interface; not a kernel property |

### 1.6 Done when

The gate includes the receive-limits-off test and it passes in every
lockdown run; the standalone harness passes on 14, 15 and 16; the link
inventory is committed and enforced; the `SCM_RIGHTS` list is in plan/14
with each entry placed. README item 1 goes.

**Risks.** The wire format of `TransportHeader` changes: harmless within
one build, since every process is the same binary, but it must not be
mixed with a helper binary from another build. Turning off buffer
sharing may cost frame rate on Mesa; measure when a Mesa machine exists.

## 2. The kernel's word on each renderer, and `beryllium://sandbox`

Matrix S-STA-01 (the browser refuses an unconfined renderer), S-STA-02
(honest sandbox claims), S-STA-03 (status page), plan/06 section 3.1
(RT-04).

### 2.1 Where it stands

- Whether a renderer is confined is known today from the renderer's own
  log line and from `procstat -s` run by the suite. The browser does not
  ask.
- *Source:* the renderer locks down in
  `RendererMainPlatformDelegate::EnableSandbox()`, before
  `RenderThreadImpl` exists. `ChildThreadImpl::Init()` accepts the Mojo
  invitation after that. So when the browser sees the
  channel connect (`RenderProcessHostImpl::OnChannelConnected`), a
  renderer that locked down is already in capability mode.
- The kernel's answer is `ki_cr_flags & KI_CRF_CAPABILITY_MODE` in the
  process's `kinfo_proc` (`kern.proc.pid`), the field `procstat -s`
  prints as `C`. *Report:* it was readable for every process with
  `security.bsd.unprivileged_proc_debug=0` (the 0.20.3.12 run of 8
  November, where descriptors could not be read and capability mode
  could), so the check does not depend on that setting. The browser is
  the renderer's parent, so the pid cannot be reused before the browser
  reaps it.
- *Source:* `beryllium://sandbox` exists and is an empty shell. The port
  registers Chromium's sandbox page on BSD, but the C++ that fills it
  (`SetSandboxStatusData`) is compiled for Linux and ChromeOS only, and
  the page's script for desktop Linux asks for values nobody set. The
  suite loads the page and checks only that it loads. *Not yet verified:*
  what a person sees there.

### 2.2 Design

**Stage A, the check and the kill.** A helper
`base::freebsd::KernelSaysCapabilityMode(pid)` returning yes, no or
unknown. In `OnChannelConnected`, on FreeBSD, for a renderer the browser
launched with the lockdown on: anything but yes ends the renderer and
logs `beryllium-sandbox: renderer pid=N is not in capability mode by the
kernel's account; ended`. Unknown counts as no. The answer is kept per
process for the page.

The condition for running the check is "the browser asked this renderer
to lock down", and nothing the renderer says. It must not be skipped for
`--no-sandbox` (see 3.5).

**Stage B, attest before inviting.** Stage A leaves a window: messages
the browser queued before the renderer connected are read by the
renderer in the moment before the browser kills it, and the first
navigation can be among them. The strict order is to hold the Mojo
invitation until the kernel says capability mode, so an unconfined
renderer never receives a message at all. The renderer needs nothing
from the browser before it locks down, so it will get there on its own.
The cost is waiting on the launcher thread or a timer between `fork` and
the invitation. Stage A's log gives the number to decide with: the time
from launch to the lockdown line per renderer. Stage B is its own build.

**The page.** A FreeBSD data source and a FreeBSD branch in the page's
script:

- one row per child process (renderers, GPU, each utility by name): type,
  pid, capability mode by the kernel (yes, no, unknown), whether a
  lockdown was requested, and for a renderer whether it was attested;
- session counters: renderers attested, renderers ended by the check,
  renderers that ended at their own lockdown;
- the state of the lockdown features and whether any escape-hatch switch
  is in effect;
- the kernel: release, and the advisory check of S-KRN-03 once it exists;
- one summary line that is true: "Renderers: N of N confined. Other
  processes are not confined." No green tick for a browser whose GPU and
  network processes are unconfined.

The values are read in the browser from the kernel when the page loads.
Nothing on the page comes from a child's own report.

### 2.3 Work plan

1. Standalone test of the kernel flag (0.2 job): a parent forks; one
   child calls `cap_enter()`, one does not, one exits; the parent reads
   `kinfo_proc` for each. Yes, no, unknown. On 14, 15, 16.
2. Patch: the helper (in `capsicum_rights`), the check in
   `OnChannelConnected`, the per-process record.
3. Patch: the page's data source and script branch. The script is a
   grit-preprocessed resource; check which platform expression the
   FreeBSD build evaluates as true before writing the branch.
4. Suite: `test_sandbox_page_matches_kernel` compares every row of the
   page with `procstat -s`, lockdown on and off, as the GPU honesty test
   already does for one value.
5. Suite: the negative test (2.5, first row).
6. Record the launch-to-lockdown time per renderer in the suite's report,
   for Stage B.

### 2.4 Tests

- Standalone: the flag for a confined, an unconfined and an exited child.
- Suite: page against kernel for every process; a browser with the
  lockdown off shows "no" for every renderer and says so in the summary;
  the counters match the log.
- Unit: the page parser in the suite, on a saved copy of the page.

### 2.5 Red team

| Attack | How it is tried | Must hold |
|---|---|---|
| A renderer that does not lock down while the browser believes it will | `--renderer-cmd-prefix` with a wrapper that removes the lockdown feature from the renderer's own command line; and the debugger returning success from the lockdown function at the startup pause | the browser ends it at connect; the test page's script never runs; the log line and the page's counter show it |
| What reached that renderer before it was ended | count the browser's cut lines for that pid before the kill | recorded; this is the window Stage B closes, and after Stage B the count is zero |
| A process leaving capability mode after the check | standalone: a confined child tries every way out it has (there is no call for it) | still confined |
| A confined renderer making a child that is not confined | `fork` through the debugger, then the kernel flag of the child | the child is confined (S-REN-08), or `fork` fails once S-HRD-03 is in |
| The page saying more than is true | page against `procstat` for every row, in a run where one renderer was forced unconfined | every row matches |
| The kernel's answer unavailable (a jail, a MAC policy hiding processes) | run the check with `kern.proc.pid` made to fail in the standalone test; later, the suite in a jail | unknown ends the renderer, and the log and the page say why |

### 2.6 Done when

A renderer that skips its lockdown is ended before its page's script
runs, in the suite, on every run; the page matches the kernel for every
process; plan/14 records the launch-to-lockdown times and the decision on
Stage B. README item 2 goes when Stage A and the page are released;
Stage B is tracked under item 3.

## 3. On by default, fail closed

Matrix S-REN-09 (fail closed), S-REN-10 (no escape hatches), S-REN-02
(warm-up), S-HRD-01, S-HRD-03, S-KRN-03. Plan/06 section 3.4 has the
design of the production and devel split; this section is what has to be
true before the default changes, and how to prove it.

### 3.1 Where it stands

- The lockdown is a feature that is off by default. With it on,
  0.20.3.17 passes the gate in both recorded lockdown runs (the sandbox
  group on 10 November, the whole suite on 11 November).
- A renderer whose lockdown fails ends itself. That is the only
  fail-closed mechanism so far.
- *Survey:* after the lockdown a renderer is refused exactly one call,
  `cpuset_getaffinity`, about once per renderer. Plan/14 names two
  candidates for the caller (libc's processor count; `pthread_attr_get_np`
  under V8's stack bounds) and has not settled which.
- Not implemented from plan/06 section 3.1: `PROC_TRACE_CTL`,
  `PROC_NO_NEW_PRIVS_CTL`, `RLIMIT_NPROC` and `RLIMIT_CORE` at the
  lockdown; the environment allowlist for children (S-IPC-02); the kernel
  advisory check (S-KRN-03); the production switch table (S-REN-10).
- One package is published. The port already reserves the name
  `beryllium-devel` as a conflict.
- Packages exist for FreeBSD 16 only. Plan/14 section 4 has an open
  item for 14.x and 15.x: time zones may fall back to UTC in capability
  mode there.

### 3.2 What must be true first

**P1. Items 1 and 2.** A default-on lockdown whose boundary depends on
the renderer's own code, or that the browser never verifies, is not the
claim the README will make.

**P2. Nothing is refused after the lockdown.** Find the caller of
`cpuset_getaffinity` (the suite can now stop a renderer on that call
with `lldb` and print the stack, as it does for the lockdown point) and
remove the call or answer it from a value read before the lockdown. Then
the after-lockdown list is empty, and a run with `BerylliumCapsicumTrap`
(the kernel signals the process on any refused call) becomes a tripwire:
any regression that makes a confined renderer reach for something it may
not have crashes it in the suite, with a stack.

**P3. The hardening calls of plan/06.** Before `cap_enter()`: no new
privileges; no forking (`RLIMIT_NPROC`; the standalone job first confirms
on 14, 15 and 16 that this stops `fork` and does not stop threads); no
core files; tracing disabled. Tracing is the awkward one: it turns off
`ktrace` and the debugger for that process, which is the point, and it
also turns off the Capsicum survey, the thread probe and the whole
`redteam` group. So it gets a switch, `BerylliumRendererTraceable`, off
by default, that leaves tracing allowed for a test run. The red-team
report then states that it attacked a renderer that differed from the
shipped default by that one call.

**P4. The kernel is one Beryllium can rely on.** At start the browser
compares the kernel's release with `freebsd/ADVISORIES.md` as a compiled
table (FreeBSD-SA-26:28.capsicum first: a confined process could signal
others) and checks that Capsicum is present. On a kernel without
Capsicum every renderer would end at its lockdown and the user would see
a browser that shows nothing. Fail closed is right; silent is not. The
browser says what is wrong, once, in the window and on
`beryllium://sandbox`.

**P5. The web still works.** The suite covers pages, media, fonts,
toolbar and stability under the lockdown. Not covered, and each can meet
capability mode in a way the suite has not seen: WebRTC calls with a
camera and microphone, file upload and download, printing and the PDF
viewer, extensions (their pages are renderers), DevTools, drag and drop,
clipboard, input methods, screen sharing, WebAssembly threads, long
sessions with many tabs. Plan: a checklist of these, done by hand under
the lockdown on each release candidate and recorded in the matrix
(R-TST-03), then automated where a local test is possible. And the owner
runs the lockdown as the daily browser for a stated period before the
default changes.

**P6. A count of what failed.** There is no crash reporter, by design.
`beryllium://sandbox` (item 2) counts renderers ended at their lockdown
and by the browser's check in this session, so a user who sees dead tabs
can say why in a bug report.

**P7. "Every run" has a number.** The owner left the number to this plan
on 11 November 2026, and it is fixed here before the runs begin: on the
release candidate, 100 consecutive whole-suite lockdown runs with nothing
failing, on one package version, over at least 3 boots, at least 20 of
them with windows open (a headless run skips the toolbar tests). Then:
one trap-mode run with no refused call; the `redteam` group passing; the
standalone jobs passing on 14, 15 and 16; the hand checklist of P5
complete.

Why 100. A whole run takes about three minutes (189 seconds in the
report of 10 November), so 100 runs are a little over five hours: one
night. With no failure in 100 runs, the chance that a run fails is below
about 3 in 100 at the usual 95% confidence; twenty runs would only have
shown it to be below about 1 in 7. The boots are there because some
state is set once per boot (device numbering, loaded modules, the
display configuration), and the windowed runs because the toolbar tests
and real compositing only happen with a window.

The rules of the count, so that nothing is decided after the fact:

- A run counts if it is the whole offline suite with `--lockdown`. A run
  of some groups, or without the lockdown, is recorded and changes
  nothing.
- Any failure or error in a counting run sets the count back to zero. So
  does a run that hangs or dies. The cause is found before counting
  resumes; if the fault is in a test, the test is fixed and the count
  still starts again.
- A new package version starts its own count.
- A run the owner stops by hand is not recorded.

The suite keeps the count itself: every run adds a line to a ledger
(`~/beryllium-test-results/ledger.jsonl`), `run --lockdown --repeat 100`
makes the runs one after another, each a process of its own so that a
hung run does not end the night, and `run --tally` prints the count, the
boots and what is still missing. A test holds the numbers in the suite to
the numbers in this paragraph.

*Not yet verified:* that a run with windows completes while the screen
is locked or asleep. Until that has been tried, a night of windowed runs
wants the screen lock off.

Once the kernel check of item 2 is in, a renderer that fails to confine
is ended, so a rare failure shows as a dead tab and not as an unconfined
page. The count then measures reliability more than safety, and what the
suite does not exercise (P5) matters more than a larger number.

### 3.3 The switch itself, in two steps

**Step 1: on by default, with a way back.** The feature's default
becomes on. `--disable-features=BerylliumCapsicumRenderer` still works,
is documented as a temporary way back, and is impossible to miss: a line
on stderr at start, and `beryllium://sandbox` says the renderers are
unconfined by the user's own switch. Reason: with no telemetry, the only
field data is bug reports, and a user who cannot get a page to load
needs a way to keep working while reporting it. The README's sandbox
table changes to "Renderers: confined".

**Step 2: no way back without the administrator.** **Decided, 11
November 2026: one package.** There is no `beryllium-devel`; a second
package would double the owner's build time per release and would mean
testing one binary and shipping another. After a stated number of
releases without a lockdown regression, the switches that undo the
sandbox (S-REN-10, the list in plan/06 section 3.4) work only when a file
that an administrator must create is present, and are ignored otherwise.
The owner's reasoning: BSD users administer their own machines.

The gate, so that it is worth having:

- one fixed path under `/usr/local/etc/beryllium/`, compiled in, never
  taken from the environment or the command line;
- honoured only if the file and every directory above it are owned by
  root and writable by nobody else, checked with `fstat` on an opened
  descriptor so the check and the use are the same file;
- read once, by the browser process, at start; children are told the
  answer and do not look for themselves;
- when it is in effect, a line on stderr and a line on
  `beryllium://sandbox` say so, with each switch that was honoured;
- the suite's deepest tests (the debugger, the survey, the thread probe)
  need it, so the owner's test machine has the file and every report
  says so in its header.

Tests: each switch on the list is ignored without the file and honoured
with it; the file is ignored when it is a symbolic link, when it is
writable by its group or by others, when it is owned by the user, and
when a directory above it is; and a renderer started with the file
absent and `--no-sandbox` given is confined all the same.

### 3.4 Tests

- Suite: everything in P7. A new test starts the browser with each
  switch on the production ignore list and requires the renderers to be
  confined all the same (step 2), or the warning to appear (step 1).
- Standalone: `RLIMIT_NPROC`, no-new-privileges and the tracing switch do
  what plan/06 says on each FreeBSD version.
- Unit: the advisory table against version strings (patched, unpatched,
  a branch not in the table).

### 3.5 Red team: hunting for a way to fail open

The attack is any route by which a page is rendered in a process that is
not confined while the browser is in its default state. Each row is a
test.

| Route | Must hold |
|---|---|
| `--no-sandbox`: *source:* `RendererMain` skips `EnableSandbox()` entirely when the switch is present, so the renderer never locks down | item 2's check ends the renderer, because the check does not look at the switch; step 2 ignores the switch unless the administrator's file is present |
| The administrator's file forged by the user: a symbolic link, a file in a directory the user owns, a path given through the environment | ignored; the tests of 3.3 try each |
| `--single-process`, `--in-process-gpu`: the renderer or the GPU code runs inside the browser process | refused at start in production; in step 1, the page and stderr say so |
| The feature turned off somewhere other than the command line: a flags page entry, a field-trial override, a policy, an environment variable | enumerate each mechanism the build has and test each; none turns the lockdown off silently |
| `--renderer-cmd-prefix`, `--utility-cmd-prefix`: a wrapper that changes the child's command line (this is also the suite's own tool in 2.5) | the browser's check catches the result; step 2 ignores the switches |
| A renderer type that does not pass through `RendererMain` | list the types (page, extension, PDF, service worker, spare, prerender) and attest one of each in the suite |
| A renderer that the browser forgot to register as a confined peer, so its descriptors are sent uncut | the receive limits catch it; the gate counts cuts per renderer and requires at least one |
| A lockdown that fails and is retried forever | the tab shows an error; the counter of 2.2 rises; no unconfined fallback exists in the code (read it) |
| A kernel without Capsicum, or with the 26:28 bug | P4: the browser says so; renderers do not run unconfined |
| An older Beryllium installed over a newer one | out of scope for the browser; item 5 covers the installer |

### 3.6 Done when

P1 to P7 hold on a release candidate and the release notes say so; step
1 is released and the README's table reads "Renderers: confined". Step 2
is a later, separate entry.

## 4. The other processes

Matrix S-PRC-01 (utilities), S-PRC-02 (GPU), S-PRC-03 (network),
S-PRC-04 (audio), S-PRC-08 (every class confined or listed with its
risk), S-DSP-01.

### 4.1 Where it stands: what the survey saw

No process but a renderer has a lockdown point. The survey of 10
November (lockdown on for renderers) recorded, per process, what
capability mode would refuse and what the process holds:

| Process | Needs after start | Holds |
|---|---|---|
| GPU (NVIDIA) | opens `/dev/nvidiactl`, `/dev/nvidia1`, `/dev/nvidia-modeset` and the render node by path, repeatedly; creates and unlinks a file in `/tmp`; makes shader cache directories under the home directory; reads driver configuration by path | 21 device descriptors with every right (`/dev/nvidia1` twelve times, `/dev/nvidiactl` four, `/dev/drm/128` three, `/dev/nvidia-modeset` two); two connections to the X server socket, in a Wayland session; shader cache files in the profile, writable |
| Network service | opens, renames and unlinks cache and profile files by path, constantly; reads `/etc/hosts` and `/etc/resolv.conf`; `connect()` for every request | sockets to the browser and to renderers; profile files |
| Storage service | LevelDB files for local and session storage under the profile | sockets to the browser and one to a renderer; six LevelDB files, writable |
| Audio service | the PulseAudio socket under the runtime directory, reached by path; PulseAudio's cookie in the home directory | sockets to the browser; one to the sound server |
| Short-lived utilities | not seen: they start and end between two samples | unknown |

Every one of them also held the standard streams with every right and
read a handful of sysctls capability mode refuses, as renderers did
before their warm-up.

### 4.2 The plan, by how hard each is

**Tier 1: utilities that only compute.** Some utilities take bytes over
Mojo and give bytes back: the data decoder, the print compositor, the
unzipper, and others to be found. They can use the renderer's lockdown
unchanged. The work is the allowlist, and it goes by service name.
Sandbox type is too coarse: the storage service is a utility of the same
type, and the survey shows it holding the profile's LevelDB files open
for writing.

1. Extend the survey to follow short-lived processes (trace from launch,
   not from a sample) and to write the lockdown marker for every process
   type, so each service gets a "would be refused after start" list.
2. A service whose list is empty joins the allowlist.
3. Generalize `LockDownRenderer` to a policy per process type in
   `sandbox_freebsd.cc`; the existing entry point is already called for
   every process type.
4. Items 1 and 2 apply as they are: the browser registers the pid, cuts
   what it sends, checks the kernel.

**Tier 2: processes that work inside a directory.** The storage service,
and the network service's cache, work inside known directories.

*Source:* for the storage service Chromium already has the other half.
`storage::FilesystemProxy`
(`components/services/storage/public/cpp/filesystem/filesystem_proxy.h`)
has two modes: unrestricted, where the service opens paths itself, and
restricted, where every file operation goes to the browser over a
`mojom::Directory` interface and the service is handed descriptors. A
storage service running in the restricted mode opens nothing by path, so
it could take the tier 1 lockdown as it is, and the browser's
sender-side cut already covers what it would be sent. *Not yet
verified:* what selects the restricted mode in Chromium 156, whether the
port's patches leave it reachable on BSD, and what it costs in speed.

So the storage spike is one build: run the storage service in the
restricted mode, survey it, and confine it if its after-start list comes
back empty. It ends in a confined storage service or a written reason
why not.

The network service's cache has no such layer. Capsicum's own answer is
a directory descriptor with lookup rights and `openat()` beneath it,
while Chromium's cache opens by absolute path. The bridge would be a
table of pre-opened directories and a shim that turns `open(path)` into
`openat(descriptor, rest)` when the path lies under one. Whether that
shim can sit in `base` alone is an open question, and it belongs to
tier 4.

**Tier 3: audio.** One connection, made before the lockdown: PulseAudio's
socket, or sndio's, or `/dev/dsp` with an ioctl allowlist, depending on
the backend in use. The open question is reconnection after the sound
server restarts. After tier 1, because it reuses everything there.

**Tier 4: the network service.** `connect()` does not exist in capability
mode. A confined network service needs someone else to make its
connections: Chromium has a socket broker in the browser for this on
other platforms, and FreeBSD has Casper's network service. Add the cache
(tier 2) and name resolution.

*Source:* the port turns Chromium's `NetworkServiceSandbox` feature on by
default on BSD (`sandbox/policy/features.cc`). On OpenBSD, pledge and
unveil stand behind that. On FreeBSD nothing does, and the survey shows
the network service opening its cache by path and calling `connect()`
itself. So Chromium already takes the network service to be sandboxed
here. The first step is reading what the browser does differently for a
sandboxed network service (which files it opens on the service's behalf,
whether it brokers sockets), because part of the plumbing may be running
already. Until something enforces it, the status page and the manual say
the network service is unconfined, whatever the feature says (S-STA-02).

This is the largest piece of work in the document and is not scheduled.
The network service gets a statement.

**Tier 5: the GPU process.** With the NVIDIA driver the survey leaves no
room: a closed library that opens device nodes by path whenever it likes,
makes files in `/tmp` and directories in the home directory. Capability
mode would need every one of those intercepted inside code the project
cannot read. It gets a statement, and the mitigations that do not need
capability mode:

- no new privileges, no tracing, no forking, no core files, as for
  renderers;
- a clean environment (S-IPC-02);
- no connection to the X server in a Wayland session. The survey shows
  two, which lets a compromised GPU process read and inject input for
  every X11 program on the desktop (S-DSP-01). *Not yet verified:* that
  removing `DISPLAY` from the GPU process's environment under Wayland
  leaves rendering working with the NVIDIA driver;
- an expected-descriptor table for the GPU process, checked by the suite
  (4.4).

With Mesa the picture may differ (one render node, and ioctls on it that
can be listed). That needs a Mesa machine, so it is noted here and left
unplanned.

### 4.3 The statement

Until a process has a policy, the README, `beryllium-sandbox(7)` and
`beryllium://sandbox` say for each: not confined; what it can reach (the
table above, in plain words); what limits it has anyway; what would
change it. S-PRC-08 is met for a process either by a policy with tests or
by this statement with an owner and a date.

### 4.4 Tests

- Suite: `test_capability_mode_per_process` gets an expected mode per
  process type and fails either way round, so a confined utility that
  stops being confined is a failure and so is a table that was not
  updated.
- Survey: per process type, the after-lockdown list is empty for every
  confined type.
- Authority drift: for each unconfined process type, the suite compares
  what it holds with a committed table (kinds and name patterns). The GPU
  process holding a profile database, or the network service holding a
  device, fails. This is the only test an unconfined process can have,
  and it catches the launcher regressing.

### 4.5 Red team

| Attack | Must hold |
|---|---|
| Every row of 0.1, inside each confined utility | as for a renderer |
| A confined utility given a file to work on (the unzipper) reaching beyond it | the descriptor's rights are the kind's; `openat` beneath a file is meaningless; the directory it came from is not held |
| A compromised renderer using a utility as its hands: it sends work to a utility that has more authority | per interface (S-IPC-03): what a renderer can ask the storage, network and audio services to do, written down; the unconfined ones are the ones that matter |
| The GPU process reading the profile | drift test: it holds only its cache files; with its environment cleaned it has the home directory's path only if it asks the system |
| The GPU process and the X server | after the mitigation, no descriptor to the X socket in a Wayland session |

### 4.6 Done when

Tier 1 utilities are confined, attested and tested; every other process
has its statement in the three places; the drift tables are enforced.
README item 4 becomes two shorter ones (tier 2 and tier 4) or goes.

## 5. Signed releases

Review finding BER-06, matrix B-PKG-07. The proposal is in plan/16; this
section tests it and fills what it left out.

### 5.1 Where it stands

`install.sh` fetches `SHA256SUMS` and the package from the same release
and compares digests. Whoever can replace release assets can replace
both. `publish-release` runs on the owner's machine and refuses a package
not built from the commit it names.

*Tried, OpenSSH 9.6:* the proposal's commands work. A signature made
with `ssh-keygen -Y sign -n beryllium-release` verifies against an
`allowed_signers` line, and verification fails for each of: a changed
file, another namespace, another key's signature, a key in a revocation
file, a key outside its validity window, a missing signature, an empty
signature. One trap: the result is `ssh-keygen`'s exit status, and a
pipeline hides it. The installer must test the command itself.

### 5.2 What the proposal leaves open

**Replay.** The asset is named `beryllium-FreeBSD-16-amd64.pkg` in every
release. A signature over an old `SHA256SUMS` stays valid for ever, so
someone who can replace assets can serve last year's package with last
year's checksums and last year's signature, and the installer accepts
it. The signed file has to say which release it is.

**Design:** the signed file becomes a small manifest in place of the
bare checksum list:

```text
beryllium-release 1
version 0.20.3.17
tag v0.20.3.17
commit 41e1ca70a5ab30ba202d1e5287e14c029df1e382
date 2026-11-10
sha256 <digest>  beryllium-FreeBSD-16-amd64.pkg
sha256 <digest>  BUILD-MANIFEST-FreeBSD-16-amd64.json
```

The installer, after the signature verifies:

1. the manifest's tag is the tag it asked for, when it asked for one;
2. the package's own version (`pkg query -F`) is the manifest's version;
3. with `latest`, the version is not older than the installed one, unless
   `--allow-downgrade`;
4. the digest matches.

**Freeze.** Serving an old, validly signed release as "latest" to a
machine with nothing installed cannot be detected by a signature alone.
The installer prints the release's date and version before asking to
install. A real answer needs signed, expiring metadata of the kind a
package repository has, which is the destination anyway (5.4).

**The installer is its own trust root.** A user fetches `install.sh`
from the repository's main branch; the key is inside it. Someone who can
change the main branch can change both. Signing protects against
replaced release assets. It does nothing against a compromised
repository. What
helps: the key's fingerprint published in more than one place (README,
the manual page, the release notes of every release, somewhere the
repository's credentials do not reach), a `--verify-only` mode, and
written instructions for checking by hand.

**The key.** Not on GitHub, not on the build jail, not in CI. Recommended:
a hardware token (`ssh-keygen -t ed25519-sk`), so the private key cannot
be copied and each signature needs a touch; verification needs nothing
special. Two tokens, both in `allowed_signers` from the first signed
release, one kept somewhere else. A revocation file in the repository,
consulted by the installer (`-r`). Validity windows on each line.

**Decided, 11 November 2026: a key file on the build machine first, a
hardware token to follow** (the owner intends a YubiKey 5C NFC). What
the first stage does and does not give:

- It protects against a release whose assets were replaced by someone
  who got at the GitHub account or a token for it and nothing else.
- It does not protect against code running as the owner on the build
  machine, which can read the key file and wait for the passphrase. The
  GitHub token is on the same machine, so such code could publish too.
- So the key file has a passphrase, is not kept loaded in an agent, and
  is readable by the owner's account alone. The nightly test job (6.1)
  runs as another user that cannot read it, because that job builds and
  runs whatever is on main with nobody watching.
- The file key gets a short validity window in `allowed_signers` (to the
  end of the quarter in which the token is expected), so that it stops
  being accepted without anyone having to remember to remove it.

When the token arrives: generate `ed25519-sk` keys on two tokens, with
`-O verify-required` so each signature needs the PIN and a touch; add
both lines to `allowed_signers`; sign one release with both the old and
the new key listed; then put the file key in the revocation file. FreeBSD's
own OpenSSH has had these key types since November 2021; the user needs
access to the USB device, for which the `security/u2f-devd` package
installs the rules. *Not yet verified* on the owner's 16.0-CURRENT.

**Transition.** From the first signed release, `latest` requires a
signature. An older tag installs only with `--release TAG
--allow-unsigned`, which says what it is doing. If `ssh-keygen` is
missing (a minimal jail), the installer refuses and says which package
provides it; it does not fall back to checksums.

### 5.3 Work plan

1. Owner: decide the key (5.2), generate it, publish the fingerprint.
2. `publish-release`: write the manifest, sign it, refuse to publish
   unsigned, then download what it published and run the installer's
   verification against it before reporting success.
3. `install.sh`: verification, the four checks, `--verify-only`,
   `--allow-downgrade`, `--allow-unsigned`, the refusal messages.
4. `allowed_signers` and the revocation file in the repository;
   `SECURITY.md`, README and `beryllium(1)` name the fingerprint.
5. Tests (5.5).
6. Sign the next release. Unsigned installs of `latest` end there.

No browser build is needed for any of it.

### 5.4 The destination: a signed package repository

`pkg` verifies a repository's catalogue against fingerprints the
administrator installed, and `pkg upgrade` then updates Beryllium like
anything else. That replaces the installer's verification with the
system's own and gives expiring, signed metadata. It needs somewhere to
host a repository (the package is larger than GitHub Pages allows per
file) and the same key discipline. Stage 2, after 5.3 has been in use for
a few releases.

### 5.5 Tests

`freebsd/tools/tests/test_install_sh.py` already runs the installer
against stubs. Added, with a real `ssh-keygen` (the CI runner has one)
and throwaway keys made in the test:

| Case | Installer must |
|---|---|
| good signature, matching version and digest | install |
| no signature; empty signature | refuse |
| manifest changed after signing; signature from another key; wrong namespace | refuse |
| key in the revocation file; key outside its validity | refuse |
| replay: an older release's manifest and signature, presented as the requested tag | refuse (tag) |
| replay as `latest` with a newer version installed | refuse (downgrade) |
| manifest names one version, the package is another | refuse |
| the FreeBSD 16 package presented under the FreeBSD 15 name | refuse (ABI check, already there) |
| a manifest with two lines for one asset; a name with `../`; carriage returns; a line of a megabyte | refuse, without acting on any of it |
| `ssh-keygen` absent | refuse and say why |

And `publish-release`: refuses without a key; its round trip catches an
upload that does not verify.

### 5.6 Red team

| Attacker | Can do | Outcome |
|---|---|---|
| Holds a token that can edit releases | replace or delete any asset | signature fails or is missing: refused. Replay: refused by tag or downgrade rule. Freeze on a fresh machine: not prevented, shown (date and version) |
| Can push to the main branch | change `install.sh` and the key | not prevented by signing. Reduced by branch protection, by the fingerprint published elsewhere, and by anyone who checks |
| Controls the build machine | builds a bad package, which the owner then signs | not prevented. A second builder comparing packages is the answer and is not planned yet |
| Sits on the network path | nothing, with TLS | the signature also holds if TLS did not |
| Supplies a hostile manifest | tries to make the installer run or write something | the parser takes fixed fields only; unit tests above |

### 5.7 Done when

A release is published with a signed manifest; `install.sh` refuses
everything in 5.5; the fingerprint is in the places listed. README item
5 goes; the package repository stays in the matrix as B-PKG-07.

## 6. Assurance

Review finding BER-07. Four parts.

### 6.1 A FreeBSD test machine (R-TST-06)

**Where it stands.** CI builds nothing: it runs the unit tests, the
tools' checks, the suite's harness against the runner's Chrome on Linux,
and the Capsicum oracle in FreeBSD 14 and 15 virtual machines. Every
native result comes from the owner running the suite by hand.

**What is wanted.** For every change that reaches main: a build, the
offline suite with and without the lockdown, the `redteam` group, and
the report kept. For 14.x and 15.x: at least the standalone jobs (0.2),
and the suite once packages exist for them.

**Options.**

| Option | For | Against |
|---|---|---|
| The owner's machine as a self-hosted Actions runner | no new hardware; reports land in the pull request | a self-hosted runner on a public repository runs whatever a workflow says; it must take jobs only from main, started by the owner, never from a pull request. It is also the owner's desktop |
| A scheduled job on the owner's machine, outside Actions: pull main, build, test, push the report to a branch | no runner, no inbound trust; simple | reports are not attached to changes; still the desktop |
| A dedicated machine doing the same | separates testing from the desktop; can run Mesa, which the project has never tested | hardware |
| bhyve guests on either, for 14.x and 15.x | the versions the README names as targets | no GPU in a guest: rendering is software, which is fine for the sandbox groups |

**Plan.** Start with the scheduled job, since it needs nothing new: a
script that builds with Poudriere, installs into a clean jail or guest,
runs the suite headless, and pushes `report.txt` and the survey to a
`reports` branch, named by commit. Then the standalone jobs in CI (0.2),
which need no machine. A dedicated machine when one exists.

**Decided, 11 November 2026: the owner's machine, at night.** If the
owner's Lenovo turns out to use Mesa under FreeBSD, it builds and tests
as well, which would give the project its first Mesa results.
`freebsd/tools/gpu-probe` answers that for any machine it is run on, or
for a list of hosts over ssh.

The release key and the test job now share a machine, which the first
draft of this plan ruled out. The separation is by user until the
hardware token arrives: the job runs as an account that cannot read the
key file (5.2), builds main only, and never a pull request.

Until the job exists, the repeat mode of the suite (3.2, P7) is the
night's work: it needs no build.

**Other architectures.** The owner has a StarFive VisionFive 2 (RISC-V,
JH7110). It is not a target, for reasons outside this project. FreeBSD
on that board was reported in 2025 to boot with no video and no USB, and
its GPU (Imagination BXE-4-32) has no FreeBSD driver, so there is nothing
for a browser to draw on. FreeBSD's Chromium port does not build for
riscv64; Chromium itself does on Linux, where distributions carry
patches for it. The board has 8 GB of memory at most, so the build would
be a cross build on amd64, and a new FreeBSD architecture for Chromium is
a port of its own (V8's code generator, the unwinder, the media
libraries' configuration, Rust's tier 3 target). If a second
architecture is wanted, aarch64 is the one the port already supports.
`gpu-probe` run on the board says what its current system uses.

**Tests of the tester.** The job fails loudly: a build that fails, a
suite that does not start, a report that is not pushed each produce a
visible failure, checked by breaking each on purpose once.

### 6.2 Review of the imported patches (S-SUP-01)

**Where it stands.** 1,696 patches come from the FreeBSD port; 217 touch
paths where a mistake is a security matter; none has a review record.
`import-bsd-patches check` lists them and `--strict` would fail on any
unreviewed one. Records go in `bsd-patch-reviews.json` against the
patch's content hash, so a changed patch needs a new review.

By area: `base/process` 19, `media/gpu` 18, `gpu/command_buffer` 17,
`content/browser` 14, `sandbox/policy` 13, `services/network` 12,
`net/dns` 11, `base/files` 11, `content/utility` 9, `gpu/vulkan` 8,
crash handling 7, `mojo/core` 6, the rest of `net` about 30, and smaller
groups.

**Why it will find things: it already has, by accident.** Four defects
in this port's patches were found in a week, none by review:

- the sandbox function returns success having done nothing, so the GPU
  page said "Sandboxed: true";
- the launcher closed no inherited descriptor;
- tracing's deferral past the sandbox was added to a function FreeBSD
  never runs, so every renderer reached its lockdown with two threads;
- thread naming is a stub, so the kernel knew every thread by the
  process's name.

They have three shapes: a function that reports success having done
nothing (the first and the fourth); an assumption that holds on Linux
left in shared code (the launcher read `/dev/fd` to learn what was open,
and on FreeBSD without fdescfs that lists three descriptors); and a
Linux condition extended to BSD inside code FreeBSD never runs. A fifth
turned up while this plan was written: the port turns Chromium's network
service sandbox feature on by default on BSD, which is right on OpenBSD
and enforces nothing on FreeBSD (4.2, tier 4). Each shape can be
searched for.

**Plan.**

1. A tool, `freebsd/tools/bsd-condition-audit`, run over the build tree
   on the owner's machine (the full source is only there), listing:
   (a) every hunk where the port adds BSD to a Linux condition inside
   code compiled only with a zygote, which FreeBSD does not have;
   (b) every Linux-only condition near the words sandbox, zygote or
   single-threaded that the port did *not* extend;
   (c) every function the port makes return a constant or
   `NOTIMPLEMENTED()` on a security path;
   (d) every use of `/proc`, `/dev/fd` or `/dev/shm` in code compiled
   for FreeBSD;
   (e) every feature whose default the port changes for BSD.
   Each line is a question for a reviewer, and the list is short enough
   to read.
2. Review in this order, a group per sitting, recording each patch:
   `sandbox/`, `content/zygote`, `mojo/` and `ipc/`, `base/process`,
   `base/posix`, `base/memory`, `base/files`, `content/browser`,
   `content/utility`, `content/renderer`, `content/gpu`, `content/app`,
   then `services/network` and `net/`, then `gpu/` and `media/gpu`, then
   crash handling.
3. Per patch, the record answers: what it changes; whether it turns a
   Linux security behaviour off, on, or into a stub on FreeBSD; whether
   it touches descriptors, pids, credentials or paths; verdict (fine,
   fine with a note, needs a Beryllium patch, needs a report upstream).
4. `--strict` in CI once the first pass is complete. Every import of a
   new port revision then shows exactly which reviews went stale.

What is found in the port's patches can be reported to the port's
maintainers; whether and how is the owner's call each time.

**Red team.** A second reader takes a sample of patches marked fine and
tries to show one is not. The known defects are the calibration: a
review procedure that would not have caught them is not good enough, so
the tool of step 1 is first tried on the tree as it was before each was
fixed.

### 6.3 Allocator and control-flow hardening (S-SUP-02)

**Where it stands.** `flags.freebsd.gn`, inherited from the port:
`use_allocator_shim=false`, `use_partition_alloc_as_malloc=false`,
`enable_backup_ref_ptr_support=false`. So Chromium's hardened allocator
serves only the allocations that ask for it by name, the system
allocator serves the rest, and the protection against use-after-free
that Chromium ships on other platforms is off. The review calls this the
main hardening deficit. Link-time optimization is a port option, off by
default; control-flow integrity needs it.

**The dependencies run one way:** the allocator shim, then PartitionAlloc
as the process's `malloc`, then BackupRefPtr. Each is a build.

**Plan: three spikes, each with an answer.**

1. *The shim and PartitionAlloc as malloc.* Turn both on. Record what
   fails to compile, to link, and to run. The known risk is memory
   allocated by one allocator and freed by the other, where a system
   library or libc allocates internally. Measure with the suite, with a
   long session, and with memory and CPU against the current build.
   Answer: works, works with listed exceptions, or does not, with the
   reason.
2. *BackupRefPtr.* On top of 1. Same measurements; it costs memory.
3. *Control-flow integrity.* Needs link-time optimization (more memory
   and time to build). Answer: builds and passes the suite, or which
   parts must be excluded.

Each spike's flags and result go in the build manifest and the matrix
whether it succeeds or not. A spike that fails is still an answer.

**Binary hardening audit (S-SUP-03).** A script over the installed
binary and its libraries: position-independent, full RELRO, immediate
binding, stack protector, non-executable stack, fortified libc calls, no
writable and executable segment. Run on the owner's machine at each
release and recorded in the manifest. No build needed.

**Red team.** For the allocator: a test page that provokes a
use-after-free in a debug hook is not available in a release build, so
the evidence is the crash type on a known-bad pattern in a unit test
built alongside, or it is the configuration report alone. Say which.

### 6.4 Someone else attacks each release (S-SUP-05)

The `redteam` group runs on every release candidate and its report ships
with the release. Once per release cycle, someone who did not write the
code is given the build and this document and a week. The 7 November
review did this once without a FreeBSD machine and found seven things;
with the suite's attacker tools it can go further. Not schedulable by the
project alone.

### 6.5 Done when

Reports for main appear without the owner starting them; the standalone
jobs run on 14, 15 and 16; every security-path patch has a record and CI
enforces it; each hardening spike has a recorded answer; the audit script
runs at release. README item 6 shrinks as each lands.

## 7. WebGPU

Matrix F-GPU-02 ("finds an adapter, or is turned off deliberately and
documented"), F-GPU-03 (the GPU is identified).

### 7.1 Why there is no adapter

*Source,* `WebGPUDecoderImpl::CreatePreferredAdapter`, as patched by the
port to include BSD:

```cpp
#elif BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_BSD)
      if (shared_context_state_->GrContextIsVulkan() ||
          webgpu_on_vk_gl_interop_ ||
          shared_context_state_->IsGraphiteDawnVulkan()) {
        backend_types = {wgpu::BackendType::Vulkan};
      } else {
        // Deliberately disable compat on linux.
        backend_types = {wgpu::BackendType::Null};
      }
```

On Linux and BSD, WebGPU gets a real adapter only when the GPU process
composites with Vulkan, or when "WebGPU on Vulkan beside a GL
compositor" is enabled. Otherwise the list of backends is the null one.
The suite's reports show `vulkan=disabled_off` and
`webgpu_on_vk_via_gl_interop=disabled_off`, so "no adapter" is what
Chromium's own design gives on this configuration. No FreeBSD fault is
needed to explain it.

The interop path is decided by `GetWebGPUOnVulkanViaGLInterop`: enabled
unless the GPU blocklist says otherwise, or forced by the feature
`ForceEnableWebGpuInterop`. It is reported disabled here. The likely
reason is the next fact.

**The GPU is not identified.** `beryllium://gpu` shows `VENDOR= 0x0000,
DEVICE=0x0000`. Chromium's blocklist and driver workarounds are keyed on
vendor and device, so on FreeBSD none of them can match. That matters
beyond WebGPU: entries that turn features off for drivers with known
faults do not apply either. *Not yet verified:* that this is why interop
is disabled, and why the identification fails (the package depends on
libpci, which Chromium's GPU information code uses on Linux).

### 7.2 The decision

WebGPU gives every web page a path into the GPU process through a second
graphics stack (Dawn, then Vulkan, then the driver). That process is
unconfined and will stay so on NVIDIA (4.2). Plan/12 said as much on 1
November. The matrix row accepts either outcome.

**Recommendation: off, deliberately, now; an opt-in for those who want
it; revisit when the GPU process has a policy.** Today's state is the
worst of both: the status page says WebGPU is enabled, pages are told
there is no adapter, and nobody chose either.

**Decided, 11 November 2026: off by default, the opt-in switch kept, and
making WebGPU work is not pursued now.** Of the work plan below, steps 1
(the probes, no build) and 2 (the default) and step 3 (identifying the
GPU, which matters for the blocklist with or without WebGPU) stand; step
4 waits.

### 7.3 Work plan

1. *No build.* The suite's rendering group records, in fresh browsers:
   what `navigator.gpu.requestAdapter()` returns by default, with the
   compatibility feature level, with `ForceEnableWebGpuInterop`, with
   the blocklist ignored, and with unsafe WebGPU allowed; whether a
   Vulkan loader and the NVIDIA driver's Vulkan description are
   installed; and whether the GPU process maps a Vulkan library in each
   case. That says whether an adapter is obtainable on this hardware at
   all, and whether the blocklist is what stops it.
2. *Small patch.* WebGPU's service off by default on FreeBSD, so the
   status page says disabled and pages get the same answer for a stated
   reason. README, `beryllium(1)` and the status page say how to turn it
   on and what that exposes.
3. *F-GPU-03.* Find why vendor and device are zero and fix it, for the
   blocklist's sake first. Compare with `pciconf -lv` in the suite's
   report.
4. *Opt-in quality,* only if step 1 found an adapter: a local WebGPU
   smoke page in the suite under `--diagnose`.

### 7.4 Tests

- The suite's WebGPU check becomes an assertion: what a page gets agrees
  with what `beryllium://gpu` says. Default: disabled and no adapter.
  Opted in: the adapter's description is recorded.
- GPU identification: vendor and device on the status page equal the
  system's.

### 7.5 Red team

| Question | How it is answered |
|---|---|
| With WebGPU off, can a page still reach the second graphics stack? | the GPU process's mapped libraries (`procstat -v`) and its opened files (the survey) show no Vulkan loader or driver Vulkan library after a page has called every WebGPU entry point |
| With it on, what does a page learn about the machine? | record `adapter.info` and the feature and limit lists; this is fingerprinting surface, and Helium's noise does not cover it |
| Does turning it on change what the GPU process holds? | the drift table of 4.4, with and without |

### 7.6 Done when

The status page and the page-visible behaviour agree, the README says
which and why, and the GPU's identification is either fixed or recorded
as a defect with its cause. README item 7 goes.

## 8. Order, builds and decisions

### 8.1 What needs no build, and can start now

- 0.2 the standalone harness and its CI job (items 1, 2, 3).
- 0.1 the `redteam` group against 0.20.3.17 as it is.
- 5 signing, end to end.
- 6.1 the scheduled job; 6.2 the audit tool and the first review groups;
  the binary audit script of 6.3.
- 7.3 step 1, the WebGPU probes.
- 3.2 P2: the caller of `cpuset_getaffinity`, with the debugger.

### 8.2 Builds, in order

| Build | Carries | Proves |
|---|---|---|
| 0.20.3.18, built 12 November 2026, not yet published | the two canvas noise patches written on 11 November 2026 (a snapshot noised as `getImageData` is; noise on WebGL `readPixels`), which are outside the seven items (matrix P-FPR-04 and P-FPR-07). Nothing else: the rest of what this row first listed was not written in time and moved one build down | measured with the noise battery that day, 30 readbacks: every row for snapshots and WebGL as rehearsed (freebsd/privacy/noise-hash/README.md) |
| 0.20.3.19 | item 2 stage A and the page; item 1's transport bit and the receive-limits switch; WebGPU off by default; the headers of the two noise patches brought up to date (not before 0.20.3.18 is published or dropped: the manifest pins every patch's SHA-256) | attestation; the sender alone suffices |
| 0.20.3.20 | item 3's P2 fix and P3 hardening calls with the traceable switch; the kernel check (P4); no GPU memory buffer video frames under the lockdown | nothing refused after the lockdown; trap mode as a tripwire |
| 0.20.3.21 | tier 1 utilities (4.2); the GPU process's mitigations | the first confined processes that are not renderers |
| release candidate | step 1 of 3.3: on by default | P7's numbers |
| separate spikes | allocator, BackupRefPtr, control-flow integrity (6.3); the storage service in its restricted mode (4.2 tier 2); item 2 stage B | an answer each |

A build that fails to compile costs a build. Each row keeps its patches
small and of a kind already compiled once in this tree where possible.

### 8.3 The owner's decisions, 11 November 2026

1. **Device descriptors to renderers under the lockdown: never**, at the
   cost of a copy per video frame on Mesa (1.2). A Mesa machine is to be
   found with `freebsd/tools/gpu-probe`.
2. **One package.** The switches that undo the sandbox come to need a
   file only an administrator can create (3.3, step 2). The way back of
   step 1 stays for a few releases after the default changes.
3. **The number was left to this plan:** 100 consecutive whole-suite
   lockdown runs, over at least 3 boots, at least 20 of them with windows
   (3.2, P7). Runs are made overnight with `run --lockdown --repeat`.
4. **The signing key starts as a file on the build machine;** a hardware
   token follows (5.2). Where the fingerprint is published outside
   GitHub is still open.
5. **The test job runs on the owner's machine, at night,** and on the
   owner's Lenovo too if that turns out to be a Mesa machine (6.1).
6. **WebGPU off by default, the opt-in kept,** not pursued now (7.2).
7. **The Helium noise finding is to be reported to Helium, by the owner,**
   once as much evidence as possible has been collected; the evidence is
   in `freebsd/privacy/noise-hash/`. Helium's rules (its
   `CONTRIBUTING.md` and `AGENTS.md`, read on 11 November 2026) forbid
   issue or pull request text generated by AI and code contributions
   written by AI. So the report is written by the owner, in the owner's
   words, from evidence the owner has run and checked, and no patch is
   offered to Helium; Beryllium's own fix is public for anyone to read.
   Which of the port's defects go to the port's maintainers is still
   open.

### 8.4 What this plan does not establish

That any of it works. The debugger-as-attacker technique was tried on
Linux only; a process in capability mode on FreeBSD is untested. The
transport bit is a design read from the source and has never been
compiled. The storage service's restricted mode is read from a header.
The allocator spikes may fail. Each section's **Done when** is
the place where a claim may first be made, and the matrix rows carry the
status until then.
