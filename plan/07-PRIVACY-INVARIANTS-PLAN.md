# Beryllium: Privacy Invariants Plan

**Status:** Draft plan, no code written
**Date:** 18 October 2026; amended 1 November 2026 (services decision, red-team findings RT-01 and RT-13)
**Implements:** spec section 10 (Helium privacy feature preservation)
**Deliverable it defines:** `freebsd/PRIVACY-INVARIANTS.md`, the living inventory that every release must re-verify

---

## 1. Purpose

Helium's privacy posture is the product. The FreeBSD port can lose it in three
ways: a GN flag inherited from `www/chromium` instead of from Helium, a Helium
patch dropped during a conflict, or a FreeBSD-only code path (crash handling,
paths, audio, fonts) that opens a network channel Helium never had. This plan
sets up the inventory and the tests that catch all three.

## 2. GN flag reconciliation

The two flag sets disagree on the points that matter most. Snapshot values:

| Flag | Helium `flags.gn` | FreeBSD `www/chromium` Makefile | Beryllium |
|---|---|---|---|
| `enable_hangout_services_extension` | `false` | `true` | `false` |
| `google_api_key` | `""` | the FreeBSD project's own key, set in the www/chromium Makefile (not reproduced here) | `""` |
| `google_default_client_id` / `_secret` | `""` | unset (defaults) | `""` |
| `use_official_google_api_keys` | `false` | unset | `false` |
| `safe_browsing_mode` | `0` | unset (Chromium default, on) | `0` |
| `enable_reporting` | `false` | unset | `false` |
| `enable_mdns` | `false` | unset | `false` |
| `enable_service_discovery` | `false` | unset | `false` |
| `enable_remoting` | `false` | `false` | `false` |
| `disable_fieldtrial_testing_config` | `true` | unset | `true` |
| `enable_widevine` | `true` | `true` (+ `WIDEVINE` option pulls `foreign-cdm`) | `true`, option-gated as in the port |
| `chrome_pgo_phase` | `0` | unset (port ships a profdata tarball and merges it) | `0` in Phase 1; PGO is a later performance task and must not change behaviour |
| `clang_use_chrome_plugins` | `false` | `false` | `false` |
| `exclude_unwind_tables` | `true` | unset | `true` |
| `treat_warnings_as_errors` | `false` | `false` | `false` |
| `use_unofficial_version_number` | `false` | unset | `false` |
| `is_official_build` | (set by platform repos) | `true` in Release | `true` |

Mechanism: the port never hand-copies flags. `freebsd/tools/gnargs-from-flags`
reads `helium/flags.gn` verbatim, appends `flags.freebsd.gn` (the
FreeBSD build-system and system-library arguments from the `www/chromium`
Makefile, minus anything privacy-relevant), and emits the `--args` string. A
test asserts that the FreeBSD fragment contains none of the keys in the table
above, so a future port update cannot silently reintroduce the API key or the
Hangouts extension.

The FreeBSD port comment says its API key is "for FreeBSD use ONLY". Beryllium
does not use it; Helium's design is empty keys plus Helium's own
`ridiculous-google-compat-exceptions` and `restore-google` search patches, and
that design is kept as is.

## 3. Helium network services inventory

Every endpoint found in Helium's patch tree at the snapshot, with the pref that
controls it and Beryllium's default. "Upstream default" is Helium's registered
pref default; all of the service toggles are also presented on the onboarding
page.

Owner decision, 1 November 2026 (charter D3): Beryllium does not use any
Helium endpoint (`services.helium.imput.net`, `crash.helium.computer`,
`updates.helium.computer`). Phase 1 ships with `helium.services.enabled=false`
and no origin. A Beryllium-hosted instance of the AGPL-3.0 `helium-services`
is the recommended path before the first public release (open item Q10); when
it exists, the defaults below change to "on, Beryllium origin" and this table
gets the new endpoint.

| Service | Endpoint | Pref | Upstream default | Beryllium default | Reason for any difference |
|---|---|---|---|---|---|
| Helium services master switch | `https://services.helium.imput.net` (overridable, HTTPS only; disabled value is the dummy `helium-services-are-disabled.qjz9zk`) | `helium.services.enabled`, `helium.services.origin_override` | on | **off**, no origin, until a Beryllium instance is hosted | charter D3: Helium endpoints are not used |
| Extension proxy (Chrome Web Store downloads and updates routed through Helium services at `/ext` and `/ext/cws_snippet`; the downloader spoofs a Windows x64 Chrome client; the Google URL `clients2.google.com/service/update2/crx` is only used when the proxy is off) | services origin | `helium.services.ext_proxy` | on | off (follows the master switch) | with the proxy off, extension installs and updates go directly to Google's `clients2.google.com`. Privacy cost: Google sees the IP address and the extension IDs. Only happens when the user installs extensions; to be documented in onboarding and the known-limitations page |
| `!bangs` (list fetched from `/bangs.json`, matched locally) | services origin | `helium.services.bangs` | on | off | the bangs list is unavailable until hosted; `!bang` searches fall through to the default search engine |
| uBlock filter assets (`/ubo/assets.json` catalog, lists mirrored by the service; remote list URLs are stripped from the bundled catalog until consent) | services origin | `helium.services.ublock_assets` | on | off | remote filter-list updates are unavailable until hosted; the lists bundled with the uBlock component keep working and only age between Beryllium releases |
| Browser update check | `https://updates.helium.computer/` appcasts | none on FreeBSD | compiled only for macOS and Windows | not compiled | `pkg` is the update channel; onboarding/settings copy about automatic browser updates is adjusted in a platform patch |
| Component updates (CRLSets, certificate transparency logs, uBlock component; Google's `update.googleapis.com` is replaced by the services origin, exact path to be confirmed in Phase 1) | services origin | `helium.services.browser_updates` | on | off until hosted | **security issue:** with no origin these components go stale (revoked certificates stay trusted, CT log lists age). Acceptable for Phase 1 testing only; the first public release requires a Beryllium-hosted origin or another update source for these components (risk R13, release gate in 09 section 9) |
| Crash reports (Crashpad; Linux ships `helium_crashpad_handler`) | `https://crash.helium.computer/crash` | `helium.crash_reporting_mode` (integer, onboarding asks) | asked at onboarding | **no upload path exists**: the BSD patch set never starts Crashpad (`chrome_main_delegate.cc` patch), and the Helium endpoint is not used, so the pref must be hidden or forced to "off" in the onboarding and settings UI by a platform patch; the port wrapper's `ulimit -c 0` is reconsidered so that `beryllium-devel` can produce core dumps for triage | charter D3 |
| Spellcheck dictionary downloads (re-enabled by Helium, served from `/dict/` on the services origin) | services origin | Chromium spellcheck prefs | on when a language is enabled | unavailable until hosted | no dictionary source; spellcheck works only for dictionaries installed some other way |
| DNS-over-HTTPS provider list | Cloudflare `https://cloudflare-dns.com/dns-query`, NextDNS `https://dns.nextdns.io` offered in settings | Chromium secure DNS prefs | user choice | same as Helium | |
| Helium sync ("vault") | provider API defined by `helium/core/sync/provider/*` patches; endpoint is user-configured provider | sync prefs | off until configured | same as Helium | verify no default provider URL in Phase 1 |
| Kagi image search | `https://kagi.com` only when the user picks it | search engine prefs | user choice | same | |
| Onboarding `helium://setup` | local, no network | | | same, rebranded; scheme possibly renamed to `beryllium://setup` (Q11) | the onboarding's services toggles default to off and explain why |

Everything else that Chromium would contact (Google host detection, GCM,
domain reliability, GAIA, network time, MEI preload, field trials, WebRTC log
upload, privacy sandbox, Safe Browsing, metrics, variations) is removed or
disabled by the ungoogled-chromium, Inox, Iridium and Bromite patches in
Helium's series or by domain substitution. The inventory lists each by patch
name so that a dropped patch is visible as a missing row.

## 4. FreeBSD-specific privacy paths to audit

These are places where FreeBSD code differs from Linux and may add network or
disk behaviour Helium never audited:

1. **Crashpad on FreeBSD.** The BSD patch set builds Crashpad but never
   starts it. Phase 1 confirms by observation that no handler process exists
   and that Helium's crash-reporting preference cannot cause a network request
   on FreeBSD, then adjusts the UI so the user is not offered a choice that
   does nothing.
2. **Audio and video backends.** sndio, OSS/ALSA, PulseAudio and PipeWire
   are local, but PulseAudio and PipeWire can be network-transparent; the
   invariants document states that Beryllium does not enable any network audio
   transport and that the renderer never holds an audio socket.
3. **xdg-open and desktop integration.** `xdg-utils` is a run dependency of
   the port; external-link handling and MIME registration are local actions but
   are part of the jail profile's policy (spec 7.1).
4. **NSS certificate database (`~/.pki`).** Created by the browser process at
   startup on BSD (see `PreinitializeSandbox` in the BSD stub). Local, but the
   jail profile must map it.
5. **Font configuration caches.** Fontconfig cache writes under
   `~/.cache/fontconfig`; local, mapped in the jail profile.
6. **Widevine via `foreign-cdm`.** Optional; when enabled it loads a Linux CDM
   through a compatibility shim and the CDM has its own network behaviour
   (licence requests, by design). Documented as an opt-in feature with its own
   row in the inventory and its own sandbox policy in Phase 3.

7. **Machine identifiers (RT-01).** `kern.hostuuid`, `kern.hostid`,
   `kern.hostname` and `kern.boot_id` stay readable in capability mode. A
   compromised renderer can read them and send them out, which links every
   profile and private window on the machine. The hostname often contains
   the user's name. Mitigations: the jail profile's random per-jail values,
   and the optional MAC module (06 section 9). The oracle's list of
   capability-mode-readable sysctls is part of this inventory.

## 4a. Invariant: Beryllium presents as Linux x86_64 (RT-13)

FreeBSD users are a small population, so every script-visible or
header-visible FreeBSD signal is close to a unique identifier. The BSD patch
set already reports UA platform `X11; Linux x86_64`, client hint platform
`Linux` and reduced `navigator.platform` `Linux x86_64`. The invariant is
that this holds on every surface, consistently:

| Surface | Required value | Known gap |
|---|---|---|
| `User-Agent` header and `navigator.userAgent` | `X11; Linux x86_64` | none known |
| `Sec-CH-UA-Platform`, high-entropy client hints | `Linux`, empty platform version | none known |
| `navigator.platform` (window and worker) | `Linux x86_64` | the unreduced path (`NavigatorID::platform()`) calls `uname()` and returns `FreeBSD amd64` whenever the `ReduceUserAgentMinorVersion` runtime feature is off; a Beryllium platform patch returns the reduced value instead |
| Any full user agent built from `BuildOSCpuInfoFromOSVersionAndCpuType()` | no `FreeBSD` | the BSD patch formats `Linux x86_64; <sysname> <cpu>`, which puts `FreeBSD` in the string; patched |
| Installed fonts | close to a common Linux distribution | documented; font probe in the test page |
| WebRTC ICE candidates | no local addresses (mDNS names or none) | Helium sets `enable_mdns=false`; tested |
| TCP/IP stack signature | not fixable in the browser | documented, with optional `pf` `scrub` settings; a Linux user agent over a FreeBSD TCP signature is a known bot-detection signal and may mean more CAPTCHAs |

The test is a fixed local page that records all of the above in window and
worker contexts, run by the privacy suite on every release and diffed against
the stored baseline.

## 5. Build-time guards

- Helium's `devutils/check_gn_flags.py` and `validate_config.py` run in
  Beryllium CI unchanged.
- A Beryllium check compares the `flags.gn` snapshot in the last release
  manifest against the current one and fails on any change to a privacy-tagged
  key unless the change is annotated in the changelog.
- The domain substitution cache (`domsubcache.tar.gz`) is verified to contain
  the expected count of substituted files; a large drop means the list no
  longer matches the tarball layout.
- The package plist is checked for any file that would make the browser read
  a system-wide policy directory Helium does not expect (the Chromium policy
  path patches in the BSD set move policies under `${LOCALBASE}/etc`; Helium's
  `prioritize-platform-policy-loading` patch changes ordering; the merged
  behaviour is documented).

## 6. Runtime privacy regression test

Defined in detail in [08-TESTING-AND-VERIFICATION.md](08-TESTING-AND-VERIFICATION.md),
summarised here because it is the acceptance test for this document:

1. Fresh user, fresh profile, in a jail with a transparent capture of DNS and
   TCP/UDP flows (`pf` with logging plus `tcpdump`, or a VNET jail whose only
   route is a capturing host).
2. Scenarios: first launch through onboarding with defaults; five minutes
   idle; ten ordinary navigations to a fixed local page set; uBlock asset
   update; extension install through the proxy; a `!bang` search; a forced
   component update check; a crash of a renderer (via `chrome://crash`); a
   private window session.
3. Output: the set of (scenario, destination host, port, byte count) tuples,
   compared with the stored baseline. Every new destination must be explained
   in the inventory before the release can proceed.
4. With the Phase 1 default (`helium.services.enabled=false`) the run must
   show no destinations other than the test page set, apart from
   `clients2.google.com` during the extension-install scenario (expected with
   the proxy off, see section 3). No request to any `*.helium.imput.net` or
   `*.helium.computer` host is acceptable in any scenario. Once a Beryllium
   services instance exists, the run is repeated with it enabled and its
   endpoints become the expected set.
5. The OS fingerprint page from section 4a is loaded in the same run.

Logs are stored without payloads. The capture host is not the build host.

## 7. Licensing and attribution

The inventory also carries the licence manifest the spec requires: Helium's
GPL-3.0 for its patches and tooling, ungoogled-chromium's BSD-3-Clause, the
Chromium licences, the uBlock Origin fork (GPL-3.0), the onboarding package,
and the non-free search-engine icon pack (status to be determined; see charter
D2). The port's `LICENSE` and `LICENSE_COMB` lines are derived from this
manifest, not written by hand.
