# Beryllium Planning Documents

**Project:** Beryllium, a native FreeBSD port of the Helium browser with a FreeBSD security model (Capsicum renderer confinement, optional jails, resource controls, MAC study) and Helium's privacy features preserved.
**Repository:** https://github.com/johnjanik/Beryllium (standalone platform repository; Helium is a pinned git submodule from https://github.com/imputnet/helium)
**Spec:** [helium-freebsd-security-port-spec.md](../helium-freebsd-security-port-spec.md) (the engineering specification these documents implement)
**Snapshot date:** 18 October 2026. No code has been written; these are plans.

## Reading order

| # | Document | What it answers |
|---|---|---|
| 01 | [Project charter](01-PROJECT-CHARTER.md) | What Beryllium is, which upstreams feed it, the eight decisions the spec left open (repository layout, branding, Helium services, patch ownership, fail-closed builds, target matrix, versioning, upstream relationship), first actions |
| 02 | [Baseline findings](02-BASELINE-FINDINGS.md) | The research record: Helium's state and pipeline, the FreeBSD and OpenBSD ports, what the FreeBSD "sandbox" actually does today (nothing), the OpenBSD pledge/unveil model, the 2023 and 2026 Capsicum attempts, Chromium sandbox internals |
| 03 | [Architecture](03-ARCHITECTURE.md) | Source, build and runtime architectures; the process map and authority matrix; how fonts, shared memory, timezone, sysctl and desktop integration are brokered |
| 04 | [Build and porting plan](04-BUILD-AND-PORTING-PLAN.md) | The `www/beryllium` port: source tarball choice, Helium dependencies as distfiles, port targets per stage, generated GN arguments, toolchain, Poudriere, install layout |
| 05 | [Patch strategy](05-PATCH-STRATEGY.md) | How four patch sources layer on one tree in seven stages, where each lives in the repository, how the BSD set is imported from FreeBSD and OpenBSD ports, the conflict matrix, the per-update refresh procedure |
| 06 | [Security model](06-SECURITY-MODEL.md) | The seven layers; Capsicum facts relied on; the renderer lifecycle, descriptor allowlist, shared-memory primitive, fail-closed split; launcher hygiene; per-process policies; `procctl` hardening; resource controls; jail profile; MAC study; residual risks |
| 07 | [Privacy invariants plan](07-PRIVACY-INVARIANTS-PLAN.md) | GN flag reconciliation between Helium and the FreeBSD port, every Helium network endpoint with its preference and Beryllium default, FreeBSD-specific privacy paths, the capture-based regression test |
| 08 | [Testing and verification](08-TESTING-AND-VERIFICATION.md) | The Capsicum kernel oracle, the sandbox suite (observation and devel hooks), privacy, functional, resource and build suites, release gates, infrastructure |
| 09 | [Roadmap](09-ROADMAP.md) | Phases 0 to 6 with concrete work items, order dependencies, rough effort, and the first public release definition |
| 10 | [Risks and open questions](10-RISKS-AND-OPEN-QUESTIONS.md) | 22 risks with triggers and mitigations, 9 decisions for the project owner, facts to re-verify on day one |
| 11 | [Maintenance and release](11-MAINTENANCE-AND-RELEASE.md) | Cadence driven by three upstream clocks, roles, the per-release procedure, advisory checklist, package distribution, security policy, the handover test |

## The findings that shape everything else

1. **FreeBSD Chromium has no sandbox.** `sandbox/policy/freebsd/sandbox_freebsd.cc` lowers `RLIMIT_DATA` and returns; there is no zygote, no seccomp, no `cap_enter`. The spec's warning is confirmed from source, and `chrome://sandbox` shows nothing on BSD.
2. **A working analogue exists on OpenBSD** (pledge and unveil per process type, renderers confined to `/dev/null`) in the same patch lineage the FreeBSD port uses, and **a 2026 Capsicum prototype exists for FreeBSD** (Alex S, bug 269234, branch `chromium-sandbox`) with Casper services, interceptors and a re-enabled zygote. Phase 2 starts by evaluating it, not by writing policy code.
3. **Versions line up unusually well right now.** Helium 0.19.4 and OpenBSD's port are both on Chromium 155.0.8059.84; FreeBSD's port is one major behind at 154. The BSD patch forward-port is mostly an OpenBSD import plus FreeBSD deltas.
4. **Helium's tooling already runs inside a FreeBSD port** (`www/ungoogled-chromium` proves it) but that port's hand-copied patch set and flags are why it lags three majors. Beryllium generates its GN arguments and imports the BSD set mechanically.
5. **Upstream Helium will not carry a FreeBSD platform** (issue 773 closed as not planned) and rejects AI-assisted contributions; Beryllium is an independent downstream with hand-written upstream submissions only.
6. **Two privacy differences are forced by the platform:** no in-app update checks (not compiled on BSD; `pkg` updates) and no crash uploads (Crashpad never starts on BSD). Everything else in Helium's privacy posture carries over unchanged.

## Decisions that need the project owner

Listed in [10-RISKS-AND-OPEN-QUESTIONS.md](10-RISKS-AND-OPEN-QUESTIONS.md) section 2. The two that affect Phase 1 work soonest: ship under the Beryllium name (recommended) or seek permission to use Helium's, and whether to keep upstream Helium services endpoints or self-host.

## How these documents are meant to be used

- They are committed under `plan/` in the standalone Beryllium repository, next to the pinned `helium` submodule, per charter decision D1.
- Each document names the spec sections it implements; the spec remains the requirements source and is not duplicated.
- Every document carries a snapshot date. The baseline and risk documents list what must be re-checked before work starts; expect all three upstream versions to have moved.
- Phase 0 replaces the research record with measured facts (`freebsd/BASELINE.md`, `freebsd/SANDBOX-BASELINE.md`, `freebsd/PATCH-MATRIX.md`) and this index is updated to point at them.
