# Helium for FreeBSD: Port Specification and Security Engineering Plan

**Status:** Proposed engineering specification  
**Research snapshot:** 18 October 2026  
**Initial target:** FreeBSD `amd64`, native package built from source  
**Project objective:** Maintain a reproducible FreeBSD port of Helium, retain Helium's privacy behavior, and add a verified, layered FreeBSD-native process-confinement model rather than shipping an effectively unsandboxed Chromium derivative.

---

## 1. Executive summary

The project is feasible, but it is not merely a packaging exercise. It has two related workstreams:

1. **Port maintenance:** build the exact Chromium revision used by Helium, integrate FreeBSD-specific source and build fixes, apply Helium's own customizations, and ship a normal FreeBSD package that can be rebuilt as upstream changes.
2. **Security architecture:** implement and test a real FreeBSD sandbox policy for renderers and other high-risk processes. The first security milestone should be Capsicum confinement of renderer processes; jails, resource controls, and optional MAC policy can add outer boundaries, but must not be used to disguise a weak renderer sandbox.

The current FreeBSD Chromium port is a valuable reference and patch source, but the versions do not necessarily match. At this research snapshot, Helium's latest release notes identify Chromium `155.0.8059.84`, while the latest fetched raw FreeBSD Ports `www/chromium` Makefile reports `154.0.8037.57`. That is a one-milestone version gap, but the revisions still need an explicit compatibility review. Recheck both repositories when implementation begins. Do not silently base a security-sensitive browser on an older Chromium revision just because it is already packaged for FreeBSD. [Helium releases](https://github.com/imputnet/helium/releases) · [FreeBSD Chromium port](https://cgit.freebsd.org/ports/tree/www/chromium/Makefile)

The security goal is **not** “call `cap_enter()` and declare the browser safe.” A production-grade implementation must inventory inherited descriptors; close or tightly restrict them; prove that renderer processes enter capability mode; keep direct networking and sensitive file access out of renderers; test IPC boundaries; and run only on patched, supported FreeBSD kernels.

One useful warning from the existing code base: the FreeBSD Ports tree contains a BSD GPU pre-sandbox hook whose visible implementation preloads Vulkan libraries and leaves a comment about enabling a namespace sandbox after crashes are understood. A 2023 FreeBSD bug report also proposed rudimentary Capsicum support for Chromium renderers, explicitly noting that it did not restrict all inherited file descriptors. Neither fact should be treated as evidence that the current port already provides the complete sandbox specified here. The first implementation task is to audit the exact selected revisions and establish the real baseline. [Current BSD GPU hook](https://cgit.freebsd.org/ports/plain/www/chromium/files/patch-content_common_gpu__pre__sandbox__hook__bsd.cc) · [Historical Capsicum proposal](https://lists.freebsd.org/archives/freebsd-chromium/2023-January/001087.html)

## 2. Goals, non-goals, and release principles

### 2.1 Required goals

- Build Helium as a **native FreeBSD application**, not as a Linux binary under Linuxulator and not as a macOS binary.
- Track a pinned Helium release/commit and its exact Chromium base revision.
- Preserve Helium's browser patches, defaults, built-in uBlock Origin fork, filters and CNAME-uncloaking behavior, onboarding, and other intentional privacy customizations.
- Maintain a FreeBSD-specific patch queue that is auditable and rebases cleanly as Chromium changes.
- Make renderer confinement testable and observable. A build that starts renderers without the intended OS-enforced sandbox must fail the security acceptance gate.
- Apply least privilege to renderers and other high-risk child processes, particularly their file descriptors, filesystem reach, sockets, device access, and IPC.
- Offer optional jail-based containment and measurable resource policies without requiring unsafe SUID helpers.
- Produce native packages installable and removable through `pkg`, plus reproducible build instructions and a security test suite.
- Document any feature that is unavailable, weakened, or differently implemented on FreeBSD compared with Helium's supported platforms.

### 2.2 Non-goals for the first production milestone

- Claiming equivalent protection to every Chromium sandbox backend on Linux or macOS before testing establishes that equivalence.
- Rewriting Chromium's entire multiprocess architecture or replacing Mojo IPC.
- Requiring a custom FreeBSD kernel or an administrator-controlled MAC policy for ordinary package installation.
- Enforcing every possible MAC policy in the first release. MAC is an advanced optional layer and must be separately designed and tested.
- Automatically running the entire desktop browser in a jail without a documented GUI integration and threat analysis.
- Promising that a renderer compromise is impossible. The goal is to make exploitation substantially harder and limit post-compromise authority.

### 2.3 Release principles

1. **No silent sandbox downgrade.** If renderer Capsicum setup fails, the browser must not silently continue in an unrestricted mode. Either fail closed for the affected process or make a deliberately insecure development build distinguishable from production builds and impossible to distribute under the production package name.
2. **Security fixes outrank feature parity.** Do not ship a Chromium base known to miss applicable security fixes merely to preserve a convenient patch match.
3. **Use kernel-enforced boundaries.** Renderer-side checks and Chromium IPC policy are important, but they are not substitutes for kernel-enforced process confinement.
4. **Minimize trusted code.** Keep the browser broker, network service, GPU process and privileged setup code as small and separately testable as practical.
5. **Document what is actually enforced.** Distinguish a configured restriction from a tested restriction and distinguish both from an aspirational design.

## 3. Threat model

### 3.1 Protect against

- A hostile web page exploiting a renderer bug and gaining native code execution in that renderer.
- A compromised renderer trying to read local files, including `~/.ssh`, browser profiles, documents, password stores, or other tabs' data.
- A compromised renderer trying to write persistent files, execute arbitrary programs, open new network connections, inspect unrelated processes, signal other processes, or access device nodes.
- Malformed media, fonts, images, PDF content, JavaScript, WebAssembly, and other attacker-controlled inputs reaching renderer or utility code.
- Resource-exhaustion attacks, including high CPU use, memory pressure, too many processes, or excessive descriptors.
- An ordinary web compromise escalating through overly broad browser IPC, excessive inherited descriptors, or a helper process with more privileges than necessary.
- Privacy regressions introduced while rebasing Helium patches or changing GN/build flags.

### 3.2 Assumptions and limits

- The FreeBSD kernel, installed base system, graphics stack, and package manager are patched and trustworthy. Kernel compromise is outside the renderer sandbox's protection boundary.
- The user account may contain sensitive data. Running the browser under the same account means a successful compromise of an unconstrained process can be serious; Capsicum and a jail are intended to reduce that exposure.
- If the browser has permission to access the desktop compositor, X server, clipboard, keyring, or a portal, that interface is an additional attack surface. A jail does not automatically make these channels safe.
- A Capsicum process may retain authority through file descriptors and memory mappings acquired before entering capability mode. Capability mode must be paired with descriptor-rights reduction and descriptor hygiene. [Capsicum manual](https://man.freebsd.org/cgi/man.cgi?query=capsicum&sektion=4) · [`cap_enter(2)` manual](https://man.freebsd.org/cgi/man.cgi?query=cap_enter&sektion=2)
- A compromised renderer may still abuse legitimate broker IPC. IPC services must validate requests, bind data to the correct origin/process, enforce permission checks, and avoid becoming confused deputies.
- Capsicum is not itself a complete syscall-filtering system and does not automatically create a network namespace. It limits namespace access and authority conveyed through descriptors; all inherited descriptors and permitted IPC paths remain part of the security design.

### 3.3 Out of scope or separate projects

- Defending against a malicious or compromised FreeBSD kernel, firmware, GPU firmware, or trusted system libraries.
- Guaranteeing anonymity against every network observer. Browser privacy features and network sandboxing are distinct controls.
- Using browser profile separation as a substitute for operating-system process confinement.

## 4. Source-of-truth and repository strategy

### 4.1 Upstream inputs to pin

Every build must record exact, immutable references for:

- Helium top-level commit/tag and version.
- Helium's Chromium/`helium-chromium` revision and Chromium version.
- All required Helium subprojects and asset repositories.
- FreeBSD Ports revision used as a reference for FreeBSD-specific dependencies and patches.
- FreeBSD base/ABI target and supported compiler/toolchain versions.
- Every local patch, including ordering and cryptographic checksums for source archives.

Helium is not just a handful of brand assets over the Ports version of Chromium. Its main repository contains version/revision metadata, a patch tree and build configuration, and it credits both ungoogled-chromium and other browser patchsets. The Linux packaging repository uses a separate build wrapper and prepared Chromium source flow. Porting should adapt that source pipeline rather than assuming the existing macOS or Debian scripts will run unchanged on FreeBSD. [Helium source repository](https://github.com/imputnet/helium) · [Helium Linux build repository](https://github.com/imputnet/helium-linux)

### 4.2 Proposed local layout

Develop a separate local port, provisionally named `www/helium`, instead of editing `www/chromium` in place. Keep the work in version control, and preserve a clearly separated patch series:

```text
www/helium/
  Makefile
  distinfo
  pkg-descr
  pkg-plist
  files/
    patches-freebsd/       # FreeBSD-specific adaptations
    patches-security/      # Capsicum and related hardening
    patches-helium/        # Only local integration patches; upstream Helium remains source of truth
  tests/
    build-smoke/
    sandbox/
    privacy/
  docs/
    SECURITY.md
    PATCH-QUEUE.md
    UPDATING.md
```

The directory names are a proposal, not a requirement of the Ports framework. Follow FreeBSD port conventions during implementation. Avoid duplicating Helium patches locally unless a FreeBSD-specific adaptation is required. Each local patch should have a rationale, upstream bug/commit where relevant, affected revision, and a test that protects against regression.

### 4.3 Version alignment policy

At the research snapshot, the Helium releases page shows a Chromium `155.0.8059.84` update, while the latest fetched FreeBSD Ports Makefile reports `154.0.8037.57`. Because Chromium security maintenance is fast-moving, the port must not adopt a fixed policy of “use whatever version `www/chromium` currently has.” The maintainer should:

1. Resolve the exact Chromium source used by the selected Helium tag.
2. Compare FreeBSD's current Chromium port revision and all FreeBSD-specific patches.
3. Port the minimum required BSD build/runtime adaptations forward to the Helium Chromium revision.
4. Reconcile Helium's patches against that same revision.
5. Record every patch conflict and test whether the change is semantic, not just textual.
6. If a security fix is available upstream, do not hold the package on an older version merely because a full rebase is inconvenient. Prefer a new upstream revision with a smaller but correct feature set to an obsolete build.

Re-check the two version numbers when starting work; they are a dated snapshot, not a permanent statement about either repository.

## 5. Target process architecture

Chromium already has multiple process types, but a process existing does not imply that FreeBSD enforces an adequate sandbox around it. The port should build an explicit matrix of **process type → authority → policy → proof test** and update it whenever Chromium changes the process model. Chromium's sandbox documentation describes the general broker/target pattern, while the exact OS enforcement differs by platform. [Chromium sandbox design](https://github.com/chromium/chromium/blob/main/docs/design/sandbox.md) · [Sandbox FAQ](https://github.com/chromium/chromium/blob/main/docs/design/sandbox_faq.md)

| Process/component | Intended role | Default authority | Required FreeBSD treatment |
|---|---|---|---|
| Browser/UI broker | Window lifecycle, user input, process supervision, user-approved file operations | User account; profile and user-selected files only | No root privileges; narrow profile paths; hardened IPC; no broad helper APIs exposed to renderers |
| Renderer | HTML/CSS layout, JavaScript, WebAssembly, DOM and web content | CPU/memory plus explicitly delegated IPC and shared-memory handles | **Capsicum required**; no arbitrary path access; no direct network socket creation; no sensitive profile/download descriptors; descriptor-rights reductions and inheritance audit |
| Network service | DNS, HTTP(S), TLS, proxy policy and web requests | Network access and small set of configuration/certificate resources | Separate process; least filesystem authority; constrain IPC callers; evaluate Capsicum only after a descriptor/network design is proven workable |
| GPU/compositor | Graphics API and GPU command processing | Selected graphics device and required shared resources | Separate process; only necessary device nodes; pre-load libraries before lockdown; restrict descriptors/ioctls where practical; document remaining driver attack surface |
| Audio/media utilities | Decode media, audio output and related services | Only required IPC, shared memory, codecs, audio handles | Separate sandbox policy per utility; do not inherit broad browser handles |
| PDF/print/image/other utilities | Parse and transform potentially hostile formats | No general user-file or profile access | Apply renderer-like restrictions where technically supported; dedicated tests per utility |
| Crash/diagnostic process | Collect minimal crash data and report only according to preference | Read only required crash artifacts | No access to general profile contents; reporting disabled unless the selected Helium behavior explicitly permits it and the user setting is clear |
| Update/install helper | Fetch/update application files | Normally package manager / signed package infrastructure, not an always-running privileged browser helper | No SUID helper; distribute updates as signed FreeBSD packages through a configured repository |

The browser broker should be treated as part of the trusted computing base (TCB), not as harmless glue. It must validate renderer identity, IPC message types and sizes, resource references, file chooser results, downloads, permission decisions, and origin-sensitive actions.

### 5.1 File and network access model

- A renderer must not receive arbitrary profile directories, home-directory descriptors, keyring sockets, downloads-directory descriptors, or writable directories.
- File chooser and download access must be brokered. The browser process should perform user-approved file opening/saving and pass only the narrow resulting handle needed for the operation.
- A renderer must not own general-purpose Internet sockets. The network service is the network broker. The browser/renderer IPC protocol must not let a compromised renderer bypass origin, permission, or proxy rules.
- Do not assume “no network” just because a process has entered capability mode. A pre-existing connected socket or a passed socket descriptor can still convey network authority. Inventory open descriptors and explicitly test the no-direct-socket requirement.
- Shared memory should be created through mechanisms compatible with the target FreeBSD capability model. The historical Capsicum work on Chromium discussed changing shared-memory behavior to avoid named System V shared-memory dependencies; verify current Chromium abstractions and do not cargo-cult an old implementation. [Historical Capsicum/Chromium paper](https://papers.freebsd.org/2010/rwatson-capsicum/)

## 6. Capsicum renderer sandbox specification

### 6.1 Required policy

Use FreeBSD's native Capsicum interfaces, including `cap_enter(2)` and descriptor-rights controls (`cap_rights_limit(2)`, `cap_ioctls_limit(2)`, and `cap_fcntls_limit(2)` as applicable). Capability mode restricts access to global namespaces; descriptor capabilities limit what a process can do with specific already-open resources. [Capsicum(4)](https://man.freebsd.org/cgi/man.cgi?query=capsicum&sektion=4) · [`cap_enter(2)`](https://man.freebsd.org/cgi/man.cgi?query=cap_enter&sektion=2) · [`cap_rights_limit(2)`](https://man.freebsd.org/cgi/man.cgi?query=cap_rights_limit&sektion=2)

The renderer policy must meet these requirements:

1. **Enter capability mode in every production renderer.** Call `cap_enter()` at a controlled, process-specific point after required setup and resource acquisition but before untrusted page content is processed. Verify the result and verify capability mode using `cap_getmode()`; log a structured failure and refuse to continue in production mode if it did not enter.
2. **Close inherited descriptors by default.** Do not treat inherited file descriptors as trusted simply because the parent opened them. Build an explicit allowlist of descriptor roles. Close all other descriptors, including accidental terminals, log files, listening sockets, browser profile files, files containing credentials, and device handles not required by the process.
3. **Reduce rights on every retained descriptor.** Apply minimum rights for read/write/seek/stat/lookup/ioctl/fcntl operations according to each descriptor's use. Where a device or file requires `ioctl`, use an allowlist of specific commands rather than leaving every ioctl allowed. If a descriptor cannot be safely reduced, redesign the handoff or keep that authority in a broker.
4. **No home-directory namespace access.** The renderer must not be able to use paths to find or read arbitrary files such as `~/.ssh`, browser cookies, saved credentials, or documents. Do not pass it a directory descriptor that grants wider `openat(2)` traversal than required.
5. **No direct network authority.** Renderers must not inherit network sockets. Test that attempts to create sockets or resolve/connect through unbrokered APIs fail under the actual kernel and Chromium build. If a browser design requires an exceptional network descriptor, treat it as an explicit policy exception, document it, and investigate whether the design can be moved to the network service.
6. **Restrict process-control authority.** Review process descriptors, inherited handles, signals, debug/trace interfaces, and process APIs. Add regression tests for attempts to signal or inspect unrelated processes. Kernel-version requirements must include relevant Capsicum security fixes.
7. **Narrow IPC.** Only pass the Mojo/Unix-domain IPC and shared-memory descriptors required for defined communication. IPC messages must be size-limited, validated, and authorized at the receiving broker; renderer identity must not be inferred from untrusted message fields.
8. **No lock-down bypass switches in production.** `--no-sandbox` and similar escape hatches must never be inserted into the production launcher or silently enabled after a startup failure. If a developer switch is retained for debugging, the package must clearly label it as insecure and the tests must ensure release builds do not set it.
9. **Child-process inheritance is explicit.** Since capability mode is inherited by child processes, validate the launch sequence and descriptor inheritance. Do not enter capability mode in a parent process that still needs to create unsandboxed children or perform browser-level work. Each process should receive only its intended authority before the final lockdown point.
10. **Failure is observable.** Emit enough local diagnostic information to tell the user or tester which sandbox setup stage failed, without including page data, URLs, cookies, or secrets in the logs.

### 6.2 Descriptor inventory and policy generation

Before enabling Capsicum in production, instrument renderer startup in a diagnostic build and produce a descriptor inventory by workload. Include at least:

- stdin/stdout/stderr, including terminal inheritance;
- executable, dynamic libraries, locale/font resources, ICU and Chromium data packs;
- shared memory and Mojo/IPC descriptors;
- random-number sources;
- any profile, cache, cookie, history, local storage, or crash-report files;
- network sockets and proxy sockets;
- GPU, audio, camera, input, portal, and other device descriptors;
- directory descriptors and any `openat` roots;
- descriptors opened by third-party libraries.

For each descriptor role, record **who opens it, why the child needs it, exact rights, whether it is read-only, whether it can be passed onward, and the test proving the policy**. Then derive a minimal allowlist. New descriptors introduced by an upstream update should fail a test or produce a reviewable inventory diff rather than automatically receiving broad rights.

The initial descriptor policy should prefer no descriptors over broad descriptor authority. Pre-opened resources must be mapped intentionally; library-loading and font behavior must be tested because late dynamic loading can cause legitimate failures after capability mode is entered.

### 6.3 Security caveats

Capsicum is a powerful building block, not a complete renderer sandbox by itself. It does not automatically remove access already conveyed by file descriptors, memory mappings, IPC, or other inherited process state. It is also not equivalent to Linux seccomp plus namespaces. Therefore:

- Do not claim that `cap_enter()` alone makes a process unable to use networking.
- Do not assume every system call that is undesirable is automatically filtered. Test and constrain its effects using the actual FreeBSD interfaces available.
- Do not assume a `cap_enter()` call that returns successfully proves the descriptor set is safe.
- Do not accept a build where renderers are capability-confined but are passed a descriptor to a privileged broker that allows arbitrary file reads or arbitrary network requests.

## 7. Jail and outer-boundary design

### 7.1 Recommended first use: optional whole-browser jail

Use a jail as an **outer perimeter**, not as a substitute for per-renderer Capsicum confinement. A jail can restrict the visible filesystem, users, devices, and selected OS resources. It does not automatically isolate one renderer from other processes in the same jail; jailing individual Chromium child processes would require a separate launcher/permission architecture and is not an initial milestone. [FreeBSD Handbook: Jails](https://docs.freebsd.org/en/books/handbook/jails/)

A useful optional deployment profile should provide:

- A minimal jail root with read-only operating-system files and only required runtime libraries/resources.
- A dedicated unprivileged UID/GID for the browser inside the jail where operationally practical.
- A private writable profile/cache directory and private temporary directory, with quotas or a dedicated ZFS dataset if available.
- Only the needed devices, e.g. selected graphics nodes if acceleration is enabled. Do not expose broad `/dev` by default.
- A deliberate network configuration. A VNET jail can provide a separate network stack, but it still needs an explicit path to the Internet, DNS, and any chosen proxy. The renderer's Capsicum policy must still deny direct networking.
- A carefully considered display path. A mounted/shared X11 socket or broad desktop-session socket can weaken isolation. Prefer narrow Wayland/portal integration where workable, but audit the authority those sockets grant; the compositor/portal is a trust boundary, not magic isolation.
- Explicit policy for clipboard, downloads, external programs, file chooser, password manager, and opening links in other applications.

Do not automatically install or activate a jail configuration system-wide as a side effect of installing the browser package. Ship documented administrator-managed examples and test the standard non-jail package separately.

### 7.2 Per-process jails are a later research item

Jailing each renderer could in theory provide another layer, but Chromium creates and supervises child processes dynamically and relies on IPC, shared memory, filesystem resources, and desktop integration. Creating a safe per-renderer jail also requires a trusted setup component and carefully brokered resources. Do not build a root-running browser or broad SUID jail helper to make this convenient. If per-process jails are pursued, use a minimal, auditable privileged setup service with a narrow request protocol, strong validation, one-way privilege drop, no generic command execution, and dedicated security review.

## 8. Resource controls

Resource limits protect availability but do not, by themselves, prevent data theft or sandbox escape.

### 8.1 Process-level limits

Use `setrlimit(2)` for limits that can safely be applied to individual child processes, such as file-descriptor count, address space or CPU-time ceilings where compatible with Chromium. Apply limits in the child process, not globally to the desktop session. Limits must be calibrated with realistic web workloads. A limit that causes the browser to malfunction can lead users to disable the sandbox or can cause unsafe fallback behavior, so production defaults should be conservative and test-backed.

### 8.2 Jail-level resource accounting

For jail deployments, consider `rctl(8)` rules for resources including `pcpu`, `memoryuse`, `vmemoryuse`, `maxproc`, `openfiles`, and `swapuse`, after checking which controls are supported by the target FreeBSD branch and kernel configuration. The FreeBSD Handbook documents jail-level rules and notes that resource accounting must be enabled. [FreeBSD Handbook: Jail resource limits](https://docs.freebsd.org/en/books/handbook/jails/#jail-resource-limits) · [`rctl(8)`](https://man.freebsd.org/cgi/man.cgi?query=rctl&sektion=8)

Resource-control design requirements:

- Establish measured normal-use baselines for ordinary browsing, video playback, large web apps, many tabs, WebAssembly and developer tools.
- Prefer per-process `rlimit` limits where they have the intended scope; use jail-wide `rctl` only when the operator wants to cap the whole browser instance.
- Distinguish `memoryuse` from virtual address-space limits, and distinguish an allocation failure from a cleanly terminated renderer. Do not claim a memory rule will always kill only the offending tab.
- Test CPU-loop handling. A CPU percentage cap and a CPU-time limit have different behavior; neither should be described as a generic “cleanly kills a rogue tab” control without a tested supervisor policy.
- On exhaustion, terminate or contain the offending child where possible and report a useful error; do not corrupt profile databases or silently disable sandboxing.
- Provide configuration profiles (e.g. desktop, constrained, jail) rather than hard-coding arbitrary limits for every machine.

## 9. Mandatory Access Control (MAC): optional, carefully scoped

FreeBSD's MAC framework permits kernel-enforced policy modules, but MAC should not be treated as a quick switch that makes the browser safe. Labels and rules need a threat model and system-level testing. [FreeBSD Architecture Handbook: MAC Framework](https://docs.freebsd.org/en/books/arch-handbook/mac/)

### 9.1 Choose the policy for the property it actually protects

- **`mac_biba` is an integrity model.** It is designed to protect integrity and prevent lower-integrity subjects from influencing higher-integrity objects. It is not, by itself, the correct mechanism to assert that a compromised renderer cannot read secret user files. [FreeBSD `mac_biba(4)`](https://man.freebsd.org/cgi/man.cgi?query=mac_biba&sektion=4)
- **`mac_mls` models confidentiality labels.** It can support confidentiality-based information-flow controls, but labels must be applied consistently to subjects and objects, and the resulting policy affects system behavior well beyond one browser. It should be a separate, administrator-enabled hardening profile, never an untested package default. [FreeBSD `mac_mls(4)`](https://man.freebsd.org/cgi/man.cgi?query=mac_mls&sektion=4)
- A custom MAC policy or type-enforcement-style system could be considered only after the simpler layers are working. It carries ongoing kernel-version and policy-maintenance costs and should not block the first secure native port.

### 9.2 MAC phase gate

A MAC experiment is acceptable only when it specifies labels for the browser executable, libraries, user profile, downloaded files, renderer subjects and required IPC objects; demonstrates allowed and denied flows; includes recovery/rollback instructions; and is tested on a clean machine. Do not apply broad MAC labels to a user's existing home directory without a separately validated plan.

## 10. Helium privacy feature preservation

The FreeBSD port must preserve the upstream product behavior where technically possible, and clearly disclose any difference. Helium describes its uBlock Origin fork as including Helium-specific filters/defaults and CNAME uncloaking. Its services cover extension proxying, `!bangs`, filter lists, browser updates, crash reports and related functions. The browser repository also includes `flags.gn`, patch sets, pruning rules, domain lists, revision/version metadata, onboarding resources and supporting components. [Helium repository](https://github.com/imputnet/helium) · [Helium components/services description](https://github.com/imputnet/helium#helium) · [Helium `flags.gn`](https://github.com/imputnet/helium/blob/main/flags.gn)

### 10.1 Maintain a privacy invariants file

Create `docs/PRIVACY-INVARIANTS.md` listing each behavior, its upstream source, default value, network endpoints (if any), whether it is user-configurable, and its regression test. At minimum audit:

- Helium's uBlock Origin fork, filter lists, default filter configuration and CNAME uncloaking.
- Tracking/advertising protection and any related browser defaults.
- Chromium/Google API keys and client identifiers; retain intentional empty/unofficial values unless upstream's documented design changes.
- Reporting, metrics, field-trial configuration, service discovery, mDNS, remoting, and other background service flags.
- Safe Browsing and other reputation/download-check behavior: document the exact Helium setting and its privacy/security tradeoff rather than accidentally inheriting a generic Chromium default.
- Helium services, extension proxying, search shortcuts/`!bangs`, filter-list retrieval, update checks, and crash reporting. These are potential privacy-relevant network paths, not “no network at all.” Record domains, data sent, opt-out/opt-in behavior and any FreeBSD-specific difference.
- Extension installation/update behavior and any changes to extension-store access.
- First-run onboarding, default search configuration, import/upgrade behavior and update UI.
- Background networking and telemetry tests. Capture traffic in a clean profile at first launch, idle, normal browsing, extension updates, filter updates and crash-report test paths.

The visible Helium `flags.gn` includes several explicit privacy-/service-related settings, such as disabling reporting, mDNS, remoting, Hangouts services and service discovery, empty Google API credentials and a `safe_browsing_mode` setting. The FreeBSD Chromium port has its own GN defaults—including a FreeBSD API key and `enable_hangout_services_extension=true` in the fetched Makefile—so the Helium integration must explicitly reconcile these differences rather than accidentally inherit Chromium-port defaults. Treat both sets of flags as versioned inputs to audit, not as timeless policy constants. Compare them against the exact tagged version on every update. [Helium `flags.gn`](https://github.com/imputnet/helium/blob/main/flags.gn)

### 10.2 Do not accidentally remove privacy features to solve FreeBSD build problems

- Do not delete Helium patches from the build simply because they conflict with FreeBSD patches. Classify the conflict and port the smallest correct change.
- Do not replace Helium's uBlock fork with generic upstream uBlock Origin unless it is a deliberate, documented temporary deviation.
- Do not silently re-enable reporting, metrics, default network services or unwanted Google integration as a workaround for a build/test failure.
- Do not claim “telemetry-free” solely from GN flags; verify runtime behavior and document required Helium service traffic.
- Preserve license files and attribution. Helium's unique code/patches are GPL-3.0, while imported code can retain other licenses. Generate an inventory of all bundled components and their licenses for the package. [Helium license notes](https://github.com/imputnet/helium#license)

## 11. Build-system and packaging requirements

### 11.1 Port build

- Use the FreeBSD Ports framework and a clean build jail; build artifacts should be installable with `pkg`.
- Make the package build independent of the maintainer's home directory, local caches, environment secrets and GUI session.
- Pin and verify source archives, required subprojects and generated assets. Record all hashes in the normal port metadata.
- Integrate GN arguments through a maintained FreeBSD-specific configuration fragment. Do not blindly copy macOS `xcodebuild` assumptions or Linux-only Docker/apt commands.
- Reuse FreeBSD-specific Chromium port patches where applicable, but rebase them to the exact selected Chromium revision. Keep Helium privacy patches and FreeBSD sandbox patches separately auditable.
- Ensure the build uses the native FreeBSD toolchain and libraries appropriate for the target ports tree. Do not rely on Linuxulator artifacts or hidden shared libraries from another OS.
- Provide a clean package plist and a proper `pkg-descr`; make install/deinstall/upgrade operations reversible.
- Preserve debug symbols separately or provide a reproducible way to obtain them for crash/sandbox triage without shipping unnecessarily large binaries by default.

### 11.2 Build hardening

Audit Chromium's existing platform hardening and the FreeBSD toolchain's supported protections. Keep address-space randomization and stack protections enabled; retain supported position-independent and linker hardening defaults; do not weaken compiler diagnostics merely to make the first port build. Consider CFI or other mitigations only where supported by the relevant Chromium build configuration and FreeBSD toolchain, and measure correctness/performance before making claims.

Record build configuration, compiler/linker versions, `gn args`, source commits and patch hashes in build metadata. Provide a maintainer command or script that emits a concise build manifest without leaking paths or usernames unnecessarily.

### 11.3 Update and package security

- Distribute packages through a signed package repository or a documented signed local repository; do not embed an ad hoc privileged updater in the browser.
- Do not use SUID browser binaries or SUID sandbox helpers.
- Use the package manager's trusted update mechanisms and normal FreeBSD file ownership/permissions.
- Avoid world-writable executable, library, profile, or helper directories.
- Use a dedicated, unprivileged build account and an isolated builder, ideally Poudriere or an equivalent clean environment.
- Generate a license manifest and component/source manifest for every release.

## 12. Implementation phases and deliverables

### Phase 0 — Establish the current baseline

**Tasks**

1. Pin the selected Helium tag/commit and read its revision metadata, build flags, patch tree and subproject requirements.
2. Pin the target FreeBSD Ports tree revision and inspect `www/chromium/Makefile`, relevant `files/patch-*` changes, GN configuration and dependency requirements.
3. Compare Chromium revisions and make a patch conflict matrix: Helium patch, FreeBSD patch, overlap, expected integration approach, test.
4. Audit current FreeBSD sandbox implementation paths. In particular, confirm the actual behavior of renderer processes, GPU processes and utility processes; do not infer it from the presence of separate PIDs.
5. Build and run upstream FreeBSD Chromium on the target machine as a reference. Record `chrome://version`, `chrome://sandbox` behavior where available, process tree, loaded libraries, startup logs, network endpoints, and functionality.

**Deliverables**

- `docs/BASELINE.md`
- Exact upstream/revision manifest
- Helium-vs-FreeBSD patch conflict table
- Baseline build log and package
- Current sandbox capability matrix by process type

**Exit criteria**

The project can reproduce the current FreeBSD Chromium baseline from clean source and can clearly state which process types are—and are not—OS-sandboxed.

### Phase 1 — Native FreeBSD Helium build with no unsupported security claims

**Tasks**

1. Create the provisional `www/helium` port.
2. Apply FreeBSD build/runtime adaptations to the Helium Chromium revision.
3. Apply Helium's patch stack, flags, resources and supporting components.
4. Build a package, launch it as a normal user and validate core browser behavior.
5. Write the first privacy invariants and runtime network inventory.

**Deliverables**

- Reproducible local package build
- Patch queue and build manifest
- `docs/PRIVACY-INVARIANTS.md`
- Known limitations list

**Exit criteria**

Helium behavior is recognizably preserved, package installation is reversible, and the project makes no unsupported claim about sandbox equivalence.

### Phase 2 — Capsicum renderer prototype

**Tasks**

1. Trace Chromium's BSD sandbox-related code and identify the exact renderer setup point.
2. Build a diagnostic-only descriptor inventory for common workloads.
3. Implement a narrow descriptor allowlist, rights reductions, descriptor cleanup and `cap_enter()`/`cap_getmode()` verification.
4. Add a production fail-closed path for failed sandbox setup.
5. Verify that the renderer has no general home-directory access, no profile-write authority, and no direct network descriptors.
6. Test normal browsing, shared memory, fonts, media and crash handling after confinement.

**Deliverables**

- Capsicum implementation patch series
- Descriptor allowlist and rationale
- `tests/sandbox/` suite
- Security design review documenting residual authority

**Exit criteria**

Every production renderer enters capability mode; all retained descriptors are inventoried and restricted; no broad or undocumented exception remains; core browsing works without disabling the sandbox.

### Phase 3 — Broaden process-specific policies

**Tasks**

- Create separate policies for renderer-like PDF/image/media utilities and other high-risk child processes.
- Evaluate GPU lockdown separately, because graphics libraries and driver ioctls can require substantial authority.
- Separate network authority from renderers and audit proxy behavior, DNS, sockets and all broker IPC.
- Ensure helper processes do not inherit descriptors or authority from the browser beyond what is needed.

**Deliverables**

- Per-process authority matrix
- Additional sandbox patches and tests
- Documented unsupported or reduced features, where applicable

**Exit criteria**

Process isolation is enforced on the kernel side for each process class claimed to be sandboxed, and all remaining unsandboxed services have an explicit risk statement and an owner.

### Phase 4 — Optional jail and resource profiles

**Tasks**

- Provide a documented whole-browser jail profile with minimal filesystem/device exposure.
- Define supported desktop integration paths and describe GUI/clipboard/file chooser tradeoffs.
- Provide optional resource profiles and measurements.
- Ensure the package does not silently require root or modify global kernel configuration.

**Deliverables**

- Administrator-managed jail example/configuration
- Resource policy examples and tuning notes
- Jail integration test plan

**Exit criteria**

The jail is optional, reversible and least-privilege; resource-control behavior has been measured; users understand the limitations of GUI IPC and shared desktop sockets.

### Phase 5 — MAC feasibility study (not a prerequisite for the first release)

**Tasks**

- Decide whether a MAC module addresses a specific residual threat not sufficiently covered by Capsicum and jails.
- Compare `mac_mls` confidentiality use cases, `mac_biba` integrity use cases and the maintenance costs of custom policy.
- Test on a disposable system and write rollback instructions.

**Deliverables**

- MAC threat-model addendum
- Policy prototype and tests, or a documented decision not to pursue MAC

**Exit criteria**

No production release depends on a MAC policy that has not been independently reviewed and tested.

### Phase 6 — Release engineering and maintenance

**Tasks**

- Build in clean Poudriere/jail environments for every supported ABI/release branch.
- Set up CI to detect patch failures, build regressions, test failures, privacy flag drift and package-manifest drift.
- Track upstream Chromium security releases and FreeBSD kernel/security advisories.
- Require a sandbox and privacy regression run for each Chromium update.
- Keep a public `SECURITY.md`, supported-version policy, disclosure channel and update procedure.

**Deliverables**

- Signed package artifacts or instructions for a signed local repository
- CI build/test configuration
- Security support policy and release checklist
- User-facing FreeBSD limitations page

**Exit criteria**

A maintainer other than the original author can update the Chromium base, resolve patch conflicts, reproduce the package, run the test suite and publish a release with clear evidence of sandbox status.

## 13. Verification plan and measurable acceptance criteria

A browser should not be described as production-grade merely because its launch command succeeds. Use automated negative tests as well as real-world feature tests.

### 13.1 Sandbox unit/integration tests

For a dedicated test renderer or instrumented test child, verify all of the following on each supported kernel:

- `cap_getmode()` reports capability mode after the required initialization point.
- Opening sensitive paths by absolute pathname fails, including representative files under the home directory, SSH configuration, and browser profile paths.
- The process cannot create or connect general Internet sockets through an unbrokered path.
- The process does not hold network sockets, profile database descriptors, writable user-file descriptors or unexpected device descriptors.
- Attempts to read/write/seek/ioctl/fcntl a passed descriptor beyond its declared rights fail.
- Attempts to inspect, trace or signal unrelated processes fail under the actual policy and kernel configuration.
- The renderer cannot create a new path-based IPC connection to arbitrary filesystem endpoints.
- Descriptor leakage is detected when a new upstream dependency or Chromium revision adds an unexpected inherited descriptor.
- A child process cannot escape capability mode through the normal Chromium process launcher.
- Failure to establish the sandbox is reported and does not silently launch an unrestricted production renderer.

Tests must assert the actual error and kernel behavior observed on supported releases rather than assume every syscall has the same failure mode. Keep a small standalone Capsicum regression executable so kernel/policy regressions can be diagnosed independently of Chromium.

### 13.2 Relevant FreeBSD security advisory check

FreeBSD published **FreeBSD-SA-26:28.capsicum** on 9 June 2026 for a missing capability-mode restriction in `sigqueue(2)`, which could permit signal delivery beyond the intended boundary. The advisory lists corrected 14.x and 15.x release/stable branches. This is a concrete reminder that OS sandbox security depends on a patched kernel, not merely on correct application code. The release preflight must confirm the host kernel is updated for applicable advisories, and the sandbox regression suite should test signal-related boundaries. For `-CURRENT`, verify the applicable source/commit status separately rather than extrapolating a release-branch fix. [FreeBSD-SA-26:28.capsicum](https://lists.freebsd.org/archives/freebsd-security/2026-June/000485.html)

### 13.3 Functional regression tests

Test clean startup, profile creation and migration, multiple tabs, site isolation, navigation, downloads, user-approved file opening, cookies and site storage, fonts, audio/video, hardware acceleration if supported, extensions, uBlock filters, CNAME uncloaking, private browsing, printing, clipboard, Wayland/X11 support, crash recovery, package upgrade and package removal.

When a function fails only because confinement blocks access, first redesign the authority handoff. Do not grant the renderer an entire directory or disable Capsicum as the first workaround.

### 13.4 Privacy regression tests

Use a clean profile and capture DNS/socket/HTTP(S) activity for these cases: first launch, idle time, ordinary navigation, filter-list update, extension update, search shortcut, browser update check, crash-report test and private-browsing session. Compare results with a stored baseline, explain every new endpoint, and verify that user preferences are respected. Do not store browsing content or sensitive request data in CI logs.

### 13.5 Resource-exhaustion tests

Run synthetic high-CPU, high-memory, high-file-descriptor and high-process tests in a disposable user/jail. Verify which limit fires, which process is killed or denied, whether the rest of the browser remains usable, and whether profile data stays consistent. Do not rely solely on a jail-wide limit to claim per-tab isolation.

### 13.6 Release gates

A release is blocked if any of the following is true:

- The exact Chromium revision and security-fix status are unknown.
- Production renderer capability mode cannot be demonstrated.
- The renderer descriptor allowlist is incomplete or includes unexplained powerful descriptors.
- A sandbox setup failure falls back to an unrestricted renderer.
- Privacy-related flags or background network behavior changed without review.
- A known applicable FreeBSD kernel security advisory is unaddressed on the target system.
- The port cannot be reproduced from clean source or omits required license/attribution files.

## 14. Maintenance cadence and upstreaming strategy

The port will be a continuing maintenance project because Chromium changes rapidly and its build system is large. To keep the work sustainable:

- Rebase FreeBSD-specific changes at each Chromium version update rather than allowing a long-lived patch fork to accumulate.
- Prefer small upstreamable patches with tests over a large local rewrite of Chromium's process infrastructure.
- Send generic FreeBSD Chromium fixes upstream where feasible; keep Helium integration and product-specific privacy behavior in the Helium/port layer.
- Track each sandbox patch against an upstream issue or local test. Any patch touching process creation, IPC, file access, shared memory, the GPU, network service or sandbox setup requires security review.
- Include a patch-drift report in every release review.
- Track the FreeBSD release/ABI matrix separately from `-CURRENT`. `-CURRENT` is valuable for early compatibility testing but should not be the only build target for a maintainable user package.
- Keep a documented policy for unsupported architectures. Begin with `amd64`; add `aarch64` only after toolchain, sandbox, graphics and package CI cover it.

## 15. Practical first work session

Start by collecting facts without changing the working system:

```sh
freebsd-version -kru
uname -m
pkg info chromium
pkg info -D chromium

# If a Ports checkout is present:
cd /usr/ports/www/chromium
make -V PORTVERSION
make -V PATCHDIR
make -V FILESDIR

# Record source revisions in separate working clones of Helium and Ports:
git -C /path/to/helium rev-parse HEAD
git -C /path/to/ports rev-parse HEAD
```

Adjust the paths if the checkouts live elsewhere. If Chromium is not installed, the `pkg info` commands may return no package; that is not a failure in the audit. The purpose is to capture the kernel/ABI, installed reference browser, exact Ports revision, and source revisions before editing anything.

Then create three initial artifacts:

1. `BASELINE.md`: source revisions, build commands, current process tree and observed security controls.
2. `PATCH-MATRIX.md`: each Helium patch and FreeBSD patch, version compatibility, conflict and test.
3. `SANDBOX-BASELINE.md`: per-process sandbox status, descriptor inventory methodology, known gaps and first Capsicum test results.

Do not begin by enabling a jail, changing global MAC settings, or editing the working Chromium port. First establish reproducibility and understand the actual process and descriptor model.

## 16. References

### Helium and Chromium

- [Helium source repository](https://github.com/imputnet/helium)
- [Helium releases](https://github.com/imputnet/helium/releases)
- [Helium Linux build and packaging](https://github.com/imputnet/helium-linux)
- [Helium build flags](https://github.com/imputnet/helium/blob/main/flags.gn)
- [Chromium sandbox design](https://github.com/chromium/chromium/blob/main/docs/design/sandbox.md)
- [Chromium sandbox FAQ](https://github.com/chromium/chromium/blob/main/docs/design/sandbox_faq.md)

### FreeBSD build and security

- [FreeBSD Ports `www/chromium` Makefile](https://cgit.freebsd.org/ports/tree/www/chromium/Makefile)
- [FreeBSD Chromium BSD GPU pre-sandbox hook](https://cgit.freebsd.org/ports/plain/www/chromium/files/patch-content_common_gpu__pre__sandbox__hook__bsd.cc)
- [Historical FreeBSD Chromium Capsicum proposal, January 2023](https://lists.freebsd.org/archives/freebsd-chromium/2023-January/001087.html)
- [Capsicum(4)](https://man.freebsd.org/cgi/man.cgi?query=capsicum&sektion=4)
- [`cap_enter(2)`](https://man.freebsd.org/cgi/man.cgi?query=cap_enter&sektion=2)
- [`cap_rights_limit(2)`](https://man.freebsd.org/cgi/man.cgi?query=cap_rights_limit&sektion=2)
- [FreeBSD Handbook: Jails](https://docs.freebsd.org/en/books/handbook/jails/)
- [`rctl(8)`](https://man.freebsd.org/cgi/man.cgi?query=rctl&sektion=8)
- [FreeBSD MAC Framework documentation](https://docs.freebsd.org/en/books/arch-handbook/mac/)
- [`mac_biba(4)`](https://man.freebsd.org/cgi/man.cgi?query=mac_biba&sektion=4)
- [`mac_mls(4)`](https://man.freebsd.org/cgi/man.cgi?query=mac_mls&sektion=4)
- [FreeBSD-SA-26:28.capsicum, 9 June 2026](https://lists.freebsd.org/archives/freebsd-security/2026-June/000485.html)
- [FreeBSD Porter's Handbook](https://docs.freebsd.org/en/books/porters-handbook/)

---

## Final recommendation

Treat this as a **security engineering project built around a maintainable FreeBSD port**, not simply a browser build. First make Helium reproducible on FreeBSD at the correct upstream Chromium revision. Then make the renderer's Capsicum policy the central security milestone: explicit descriptor allowlists, rights reduction, no direct network authority, no sensitive filesystem access, fail-closed setup and adversarial regression tests. Add a documented optional jail profile and calibrated resource limits after renderer confinement works. Keep MAC as a separate, justified hardening layer rather than relying on `mac_biba` to provide confidentiality.

A credible release is one for which the maintainer can demonstrate, with repeatable tests, what each process can access and why—and can repeat those tests after every Chromium update.
