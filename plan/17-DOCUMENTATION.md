# Beryllium: Documentation Plan

**Written:** 10 November 2026, while build 0.20.3.16 was running.
**Covers:** the manual pages and the other documentation a FreeBSD user
expects from an installed application, how they are written, checked and
shipped, and the order they will be written in.
**Feature matrix:** R-DOC-01 (README), R-DOC-02 (build guide), R-DOC-04
(manual pages).

## 1. Where things stood

The package installed one manual page, and it was not Beryllium's. The
port, like `www/chromium`, installs Chromium's
`chrome/app/resources/manpage.1.in` and substitutes `@@PACKAGE@@` and
`@@MENUNAME@@`. Chromium has since changed the placeholders to `@@PACKAGE`
and `@@MENUNAME` (no closing `@@`), so the substitution matches nothing:
`man beryllium` in 0.20.3.12 opens with `@@PACKAGE - the web browser from
Google`, sends the reader to Google's help centre, and documents none of
what Beryllium adds. The page is also in the old man(7) macros, which
FreeBSD's own pages left long ago. The stock FreeBSD Chromium port very
likely has the same fault; telling its maintainers is the owner's call.

Everything else lived in the repository: the README, SECURITY.md, the plan
documents and the test suite's README. None of it is installed.

## 2. Principles

1. **FreeBSD conventions.** Pages are written in mdoc(7), in the section
   their subject belongs to, with the standard sections in the standard
   order, and they pass `mandoc -T lint` at warning level. A page reads
   like one from the base system: what the thing is, every option, the
   environment, the files, exit status, examples that can be pasted,
   diagnostics that quote the real messages, cross-references.
2. **Nothing the repository cannot back.** A page states only what a
   test, a patch or the code supports. The sandbox page in particular
   follows the feature matrix (plan/13): it says "not confined" where
   the matrix says so, and it says how the reader can check each claim
   from outside the browser. Options are documented only when they were
   verified in the source of the pinned Chromium or are exercised by the
   test suite; Chromium's hundreds of other switches are named as
   undocumented and unstable, as its own page does.
3. **One source.** A page lives in `man/` and nowhere else. The port
   copy (`files/beryllium/man/`) is made by `sync-port`, and CI fails
   when it is stale.
4. **Each page says which release it describes.** The footer carries the
   package version (`.Os Beryllium @@VERSION@@`, filled in by the port),
   and HISTORY names the release each mechanism first appeared in.
5. **Checked like code.** `freebsd/tools/check-man` runs in the unit
   tests and in CI; a page that breaks a rule fails the push.

## 3. The set

| Page | Subject | State |
|---|---|---|
| `beryllium(1)` | The command: what the launcher does, the options Beryllium adds, relies on or tests, the features it and Helium define, environment, files, exit status, examples, diagnostics | written, 10 November 2026 |
| `beryllium-sandbox(7)` | What is confined and what is not, the measures in every process, the renderer lockdown, the descriptor policy with the rights each kind keeps, what is not covered, how to verify with `procstat`, the log messages | written, 10 November 2026 |
| `beryllium-policies(5)` | Managed and recommended policy files: where they live, the JSON format, precedence, the policies that matter for privacy and for a managed desk, with examples | next; every policy named must be checked against the pinned Chromium and loaded once by a test |
| `beryllium-privacy(7)` | What the browser contacts and when, the services switch, the fingerprinting noise (canvas, audio, processors), the defaults that differ from Chromium, how to check with the suite's recording proxy | after policies; draws on plan/07 and the privacy tests |
| `beryllium-test(7)` | The browser test suite: groups, options, the gate, reading a report | only if the suite is packaged; until then its README is the reference |
| Handbook under `share/doc/beryllium/` | Installed copies of the README, SECURITY.md and a troubleshooting guide (fonts, GPUs and drivers, Wayland and X11, "Aw, Snap" codes, the sysctl), behind the port's `DOCS` option | planned; needs the port option and a plain-text rendering |

Not planned: a page per Chromium switch, or a copy of Chromium's user
help. `install.sh` documents itself with `--help` and the README.

## 4. Layout, build and install

- `man/NAME.SECTION`: the source, mdoc, plain ASCII. Paths are written
  with `/usr/local`; the version appears only as `@@VERSION@@` on the
  `.Os` line. From a checkout, `man man/beryllium.1` reads it on FreeBSD.
- `freebsd/tools/sync-port` copies `man/*.[1-9]` to
  `freebsd/ports/www/beryllium/files/beryllium/man/`.
- The port lists the pages in `BERYLLIUM_MANPAGES`, and `do-install`
  replaces `@@VERSION@@` with `${DISTVERSION}` and `/usr/local` with
  `${PREFIX}` before `${INSTALL_MAN}` puts each page in
  `share/man/man<section>/`. Each page is in `pkg-plist`. A unit test
  holds the three lists (the directory, the Makefile, the packing list)
  together.
- Chromium's page is no longer installed.

## 5. Checks

`freebsd/tools/check-man [--require-mandoc] [FILE...]` has two layers.

The first needs only Python, so it runs in a cloud session, in CI and in
the unit tests: plain ASCII; no trailing blanks or empty lines; lines of
at most 80 columns (a quoted `.It` message may be longer); the `.Dd`,
`.Dt`, `.Os` prologue with the file's name and section and a real date;
the standard sections in the standard order with NAME first and the
required ones present; only mdoc macros; blocks closed; one sentence per
line; cross-references with a section, pointing at Beryllium pages that
exist, and SEE ALSO sorted by section and name; the version placeholder
only on the `.Os` line.

The second is `mandoc -T lint -W warning`, the base system's own check. It
runs when mandoc is installed; CI installs it and passes
`--require-mandoc`.

## 6. Writing rules

- One sentence per line, so a change to one sentence is a one-line diff.
- Options with `.Fl`, arguments with `.Ar`, fixed words with `.Cm`,
  paths with `.Pa`, variables with `.Ev` and `.Va`, constants with `.Dv`,
  other pages with `.Xr`. No font escapes.
- Examples are commands that were run, in literal displays.
- DIAGNOSTICS quotes messages as the program prints them; when a message
  changes in a patch, the page changes in the same commit.
- The `.Dd` date changes whenever the content does.
- British spelling, as in the rest of the repository.
- A statement about confinement is made in the page only after it is in
  the matrix with a test behind it.

## 7. At each release

Added to the release procedure (plan/11): read each page against the
matrix and the README's status section; update `.Dd` and HISTORY if a
mechanism landed; run `check-man`; after installing the package, read
`man beryllium` once on the build machine, since only there is the
version filled in.

## 8. Order of work

1. This plan, `beryllium(1)`, `beryllium-sandbox(7)`, the checker, the
   port change (revision 17). Done on 10 November 2026; first shipped
   with the build after 0.20.3.16.
2. `beryllium-policies(5)`, with a test that loads a policy file and sees
   the policy applied.
3. `beryllium-privacy(7)`.
4. The handbook under `share/doc/beryllium/` and the `DOCS` option.
5. HTML renderings of the pages (`mandoc -T html`) for the repository's
   site, if one is made.
