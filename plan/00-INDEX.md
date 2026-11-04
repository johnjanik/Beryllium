# Beryllium Planning Documents

**Project:** Beryllium, an independent privacy-focused browser built natively for FreeBSD from code derived from the Helium browser, with a FreeBSD security model (Capsicum renderer confinement, optional jails, resource controls, MAC module study) and the inherited privacy features preserved. Beryllium is not affiliated with Helium.
**Repository:** https://github.com/johnjanik/Beryllium (standalone platform repository; the upstream code is a pinned git submodule from https://github.com/imputnet/helium, currently tag `0.20.3`, Chromium 156.0.8078.79)
**Spec:** [helium-freebsd-security-port-spec.md](../helium-freebsd-security-port-spec.md) (the engineering specification these documents implement)
**Snapshot date:** 18 October 2026, with facts re-checked and owner decisions recorded on 1 November 2026 (see document 12). Since then the port builds and runs: release v0.20.3.1-1 (4 November 2026) is published, and document 13 tracks what is implemented, built and tested for every feature.

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
| 12 | [Work plan and red-team review](12-WORK-PLAN-AND-RED-TEAM.md) | Facts re-checked on 1 November 2026, sprint plan split between cloud sessions and the FreeBSD machine, amendments to documents 01 to 11, 15 red-team findings with evidence and tests, the probe catalogue and attacker payload hook |
| 13 | [Feature matrix](13-FEATURE-MATRIX.md) | Every functional, privacy, security, build and release feature with its priority, phase, and implement, build and test status; generated from `feature-matrix.toml` by `freebsd/tools/feature-matrix`, which CI uses to reject claims the repository cannot back |

## The findings that shape everything else

1. **FreeBSD Chromium has no sandbox.** `sandbox/policy/freebsd/sandbox_freebsd.cc` lowers `RLIMIT_DATA` and returns; there is no zygote, no seccomp, no `cap_enter`. The spec's warning is confirmed from source, and `chrome://sandbox` shows nothing on BSD.
2. **A working analogue exists on OpenBSD** (pledge and unveil per process type, renderers confined to `/dev/null`) in the same patch lineage the FreeBSD port uses, and **a 2026 Capsicum prototype exists for FreeBSD** (Alex S, bug 269234, branch `chromium-sandbox`) with Casper services, interceptors and a re-enabled zygote. Phase 2 starts by evaluating it, not by writing policy code.
3. **Versions line up.** On 1 November 2026 the pin is Helium 0.20.3 on Chromium 156.0.8078.79 and FreeBSD's `www/chromium` is at 156.0.8078.47_1, so the first BSD import is a copy of the FreeBSD set plus point-release fixes. (At the 18 October snapshot the pin was 0.19.4 on 155 and FreeBSD was at 154.)
4. **Helium's tooling already runs inside a FreeBSD port** (`www/ungoogled-chromium` proves it) but that port's hand-copied patch set and flags are why it lags three majors. Beryllium generates its GN arguments and imports the BSD set mechanically.
5. **Upstream Helium will not carry a FreeBSD platform** (issue 773 closed as not planned). The owner decided on 1 November 2026 that Beryllium is an independent project that does not associate itself with Helium: own name, no use of Helium's service endpoints, no upstream contributions planned.
6. **Privacy differences:** no in-app update checks (not compiled on BSD; `pkg` updates), no crash uploads (Crashpad never starts on BSD), and the services switch off by default until Beryllium hosts its own services instance (document 07 section 3 lists the consequences). The last is not implemented yet: release 0.20.3.1 keeps Helium's default and address, held back only until the user consents on the setup page (document 13, P-SVC-01). The rest of the inherited privacy posture carries over unchanged.
7. **The red-team review (document 12) changed the design in several places:** machine identifiers readable in capability mode, kernel-attested sandbox status, environment scrubbing, no shared socket directories, allocator hardening, a reframed MAC study and a freshness target.

## Decisions that need the project owner

Listed in [10-RISKS-AND-OPEN-QUESTIONS.md](10-RISKS-AND-OPEN-QUESTIONS.md) section 2. Decided on 1 November 2026: the name (Beryllium only), Helium services (not used), target branches and development host. Open and affecting Phase 1 soonest: hosting a Beryllium services instance, and whether user-visible `helium://` URLs are renamed to `beryllium://`.

## How these documents are meant to be used

- They are committed under `plan/` in the standalone Beryllium repository, next to the pinned `helium` submodule, per charter decision D1.
- Each document names the spec sections it implements; the spec remains the requirements source and is not duplicated.
- Every document carries a snapshot date. The baseline and risk documents list what must be re-checked before work starts; expect all three upstream versions to have moved.
- Phase 0 replaces the research record with measured facts (`freebsd/BASELINE.md`, `freebsd/SANDBOX-BASELINE.md`, `freebsd/PATCH-MATRIX.md`) and this index is updated to point at them.
