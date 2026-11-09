# FreeBSD security advisories that touch Beryllium

The record kept by the advisory checklist in
[plan/11 section 4](../plan/11-MAINTENANCE-AND-RELEASE.md): when FreeBSD
publishes a security advisory (FreeBSD-SA) or errata notice (FreeBSD-EN)
that touches Capsicum, process control, file descriptors, shared memory,
jails, `rctl`, the dynamic linker or the graphics drivers, it is listed
here with what Beryllium relies on, which branches carry the fix, and what
was done. The browser's sandbox leans on the kernel for every one of these,
so an advisory in them changes what a release can claim until the test
machines run a fixed kernel.

Sources: <https://www.freebsd.org/security/advisories/> and the
`freebsd-security-notifications` list.

| Advisory | Published | What it touches that Beryllium relies on | Fixed in | Test machines updated | Beryllium action |
|---|---|---|---|---|---|
| `FreeBSD-SA-26:28.capsicum` | 9 June 2026 | `sigqueue(2)` lacked the capability-mode restriction, so a confined process could signal an unrelated process (plan/06 section 3) | the supported 14.x and 15.x branches, per the advisory | the development host runs 16.0-CURRENT; the fix there is confirmed by the Capsicum oracle's `sigqueue` probe, not by a version number (plan/08) | the oracle (`freebsd/tests/capsicum-standalone/cap-oracle.c`) tests `sigqueue`; the preflight check is to warn on an older kernel (plan/11 section 4, step 3, not yet written); the renderer policy assumes the fix |

How to add a row: the advisory id and date; the kernel facility and the
Beryllium feature (matrix row) that depends on it; the FreeBSD branches
and patch levels with the fix; the date the owner's machine and any test
hosts were updated; and what Beryllium did (a release note, a changed
claim in the README's sandbox table, a code change, or nothing with the
reason). Until the test machines are fixed, the README's sandbox table and
the release notes must say which claims the advisory suspends.
