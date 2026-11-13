# Contributing to Beryllium

Thank you for wanting to help. Beryllium is a young project with one
volunteer maintainer, and help from people on other machines is what it
lacks most. This file says what is useful, what to check before writing a
change, and what a change needs before it can be merged.

## The short version

- **A bug or a question:** open an
  [issue](https://github.com/johnjanik/Beryllium/issues).
- **A security problem:** do not open an issue. Report it privately, as
  [SECURITY.md](SECURITY.md) describes.
- **A change to how the browser behaves:** open an issue first and wait
  for an answer before writing it.
- **A small fix** (a typo, a document, a test, a bug in a tool): send a
  pull request directly.
- Run the [checks](#checks-to-run) before you send it, and say what you
  built and tested, on what machine, and what you did not test.

## What helps most

1. **Test reports from other machines.** The browser has been tested on
   one machine: FreeBSD 16.0-CURRENT, an NVIDIA GPU, KDE Plasma on
   Wayland. A run on an Intel or AMD GPU, on X11, on another desktop, or
   on a package built for FreeBSD 14 or 15 tells the project something it
   does not know. Install Beryllium, then from a checkout:

   ```sh
   freebsd/tests/browser/run
   ```

   ```sh
   freebsd/tools/gpu-probe
   ```

   Attach `report.txt` and the probe's output to an issue. The suite uses
   throwaway profiles and never opens your own. Its report holds your
   machine's host name on the third line, and the diagnostic survey
   (`run capsicum --diagnose`) holds paths with your user name; remove
   them first if you prefer. The suite's guide is
   [freebsd/tests/browser/README.md](freebsd/tests/browser/README.md).
2. **Bug reports** that say what you did, what happened, what you
   expected, and the versions (`beryllium://version`,
   `freebsd-version -ku`).
3. **A second reader for security patches.** A patch that touches the
   sandbox needs someone other than its author to read it, and the
   project has nobody for that yet. The same goes for the FreeBSD patches
   Beryllium imports: those on security paths are listed in
   [BSD-PATCH-REVIEW.md](freebsd/ports/www/beryllium/BSD-PATCH-REVIEW.md)
   and wait for review.
4. **Corrections to the documents**, above all where one claims more than
   was measured.

## Before you write a change

**Check whether a setting already does it.** Beryllium inherits its
settings, flags and keyboard shortcut page from Helium and Chromium. If
the behaviour you want can already be switched on, a line in the
documentation is the right change, and no patch is needed.

**A new default is a decision for every user.** Changing what the browser
does out of the box is the maintainer's call, even when the code is one
line. Open an issue, say what you want and why, and wait for the answer.
You save yourself the work if the answer is no.

**Send the change where it belongs.** Beryllium is three layers of other
people's work with a thin layer of its own on top.

| The problem is in | It belongs to |
|---|---|
| Chromium itself, on every platform | [Chromium](https://issues.chromium.org/) |
| A FreeBSD patch for Chromium (`files/patch-*` in the port) | FreeBSD's `www/chromium` port, through [FreeBSD Bugzilla](https://bugs.freebsd.org/). Beryllium imports these files and never edits them by hand |
| A Helium feature, on every platform | [Helium](https://github.com/imputnet/helium), under Helium's own rules. Do not report Beryllium's problems there: Beryllium is not affiliated with Helium |
| The FreeBSD build, the sandbox, the package, the installer, the tests, these documents | Beryllium, here |

If you are not sure, open an issue here and you will be told.

What Beryllium carries itself: FreeBSD fixes that are not in the port yet,
the Capsicum sandbox and other hardening, privacy fixes, and its own name
and packaging. [The patch strategy](plan/05-PATCH-STRATEGY.md) has the
reasoning.

## The repository

| Path | What it is |
|---|---|
| `patches/` | Beryllium's own patches to the browser, applied after Helium's. `patches/series` gives the order |
| `helium/` | Helium, as a git submodule at a pinned commit. Never edited here |
| `freebsd/ports/www/beryllium/` | The FreeBSD port. `files/patch-*` is the imported FreeBSD patch set; `files/beryllium/` holds copies of the repository's own inputs, written by `freebsd/tools/sync-port` |
| `freebsd/tools/` | The project's tools, with their unit tests in `freebsd/tools/tests/` |
| `freebsd/tests/browser/` | The browser test suite |
| `install.sh`, `freebsd/release-keys/` | The installer and the keys that sign releases |
| `plan/` | The plans and the record of every build. `plan/feature-matrix.toml` lists every feature with what is implemented, built and tested |
| `man/` | The manual pages |

Get the submodule before running anything:

```sh
git submodule update --init
```

## Changing the browser

A change to the browser is a patch file. The rules:

1. **One purpose for each patch**, in `patches/<area>/beryllium-<what>.patch`,
   added to `patches/series`. The areas are `platform`, `security`,
   `privacy`, `ui` and `branding`.
2. **Write it against the file it will meet.** Helium and the FreeBSD
   patch set change many files before Beryllium's patches apply.
   `freebsd/tools/patch-workbench --out <dir> path/in/chromium.cc`
   fetches the file and applies every earlier patch to it, so you edit
   exactly what the build will see.
3. **Start the patch with a header**, as every existing patch does:

   ```
   Beryllium: what the patch does, in one line

   Purpose: the problem, how it was seen, and what the patch changes.
     Say whether it is FreeBSD-specific.
   Stage: 4 (Beryllium series), and the earlier patches it depends on.
   Refreshed against: the Chromium version and Helium commit.
   Test: the test that covers it, or the steps to check it by hand.
   security-review: required (why), or: not required (why)
   ```

4. **Mark security patches.** A patch that touches process creation, IPC,
   file descriptors, shared memory, the GPU process, the network service
   or the sandbox carries `security-review: required` and is not merged
   until a second person has read it. The maintainer has the last word on
   which label a patch gets.
5. **Copy it to the port** by running `freebsd/tools/sync-port`. Do not
   edit the copies under `freebsd/ports/www/beryllium/files/beryllium/`.
6. **Add or update its row** in `plan/feature-matrix.toml`, then run
   `freebsd/tools/feature-matrix` to regenerate the page. A row may not
   claim more than the repository shows: an untested feature says so.
7. **Say whether you built it.** A build takes two to three hours and
   about 100 GB, and CI cannot do one. A patch that was never compiled is
   welcome for review, and is merged only when the maintainer is ready to
   build and test it. That can take a while.

## Changing tools, tests and documents

- A change to a tool comes with a change to its tests in
  `freebsd/tools/tests/`.
- Shell scripts are POSIX `sh` and pass ShellCheck. The Python is the
  standard library only.
- Generated files are never edited by hand. Change the source and run the
  generator:

  | Generated | From | With |
  |---|---|---|
  | `plan/13-FEATURE-MATRIX.md` | `plan/feature-matrix.toml` | `freebsd/tools/feature-matrix` |
  | `freebsd/ports/www/beryllium/files/beryllium/` | `patches/`, `man/`, `revision.txt` and the other inputs | `freebsd/tools/sync-port` |
  | `freebsd/ports/www/beryllium/files/patch-*` | the FreeBSD ports tree | `freebsd/tools/import-bsd-patches` |

- Documents use plain words and short sentences. They say what was
  measured, on what, and when, and they say "not yet verified" where
  something was not. A claim about security or privacy needs the test or
  the measurement behind it.

## Files that need agreement first

Open an issue before touching any of these. They are read line by line,
and a pull request that changes them without a prior discussion is closed.

- `freebsd/release-keys/`, the key lists inside `install.sh`, and the
  code in `install.sh` that verifies a release;
- `freebsd/tools/publish-release` and `freebsd/tools/check-provenance`;
- `.github/` (the CI workflows);
- the `helium` submodule's commit and the port's `distinfo`.

Two more are the maintainer's to change, at release time: `revision.txt`
and the release sections at the top of the README.

## Checks to run

CI runs these on every pull request. Run them yourself first:

```sh
python3 -W error::ResourceWarning -m unittest discover -s freebsd/tools/tests
freebsd/tools/sync-port --check
freebsd/tools/feature-matrix --check
freebsd/tools/gnargs-from-flags check
freebsd/tools/helium-linux-conditions
freebsd/tools/helium-bsd-crashpad-calls
freebsd/tools/check-man --require-mandoc
shellcheck -s sh install.sh freebsd/tools/publish-release freebsd/tools/gpu-probe
```

They need Python 3.11 or later, `mandoc` and `shellcheck`, and run on
FreeBSD or Linux in under a minute. On your first pull request GitHub
waits for the maintainer to approve the CI run.

If your change affects the running browser and you have a build, run the
browser suite as well, with and without the sandbox:

```sh
freebsd/tests/browser/run
freebsd/tests/browser/run --lockdown
```

## Commits and pull requests

- One purpose for each pull request. Small ones are read sooner.
- The first line of a commit message says what changes, in plain words.
  The body says why, and what was checked.
- The pull request says what it changes and why, how you tested it (the
  FreeBSD version, the GPU, the desktop), and what you did not test.
- Answer review comments with new commits. The maintainer decides how to
  merge.

## Work written with AI assistance

It is allowed. The maintainer uses an AI assistant too, and the commits
say so.

- **Say so.** Keep the `Co-Authored-By` line the tool adds, or say it in
  the pull request.
- **You answer for it.** Read every line, understand it, and test it, or
  say plainly that it is untested. A pull request whose author cannot
  answer questions about it is closed.
- **Check its claims.** A patch header that says "this cannot conflict" or
  "pages cannot intercept this" has to be true. Say how you know.
- **Keep it out of other projects.** Each has its own rules. Helium bans
  accounts for AI-generated issue and pull request descriptions, so do
  not pass such text there.

## Licence

By sending a contribution you agree that it is published under the
licence of the part it changes, and you confirm that you have the right
to send it: it is your own work, or it comes from a source whose licence
allows it and you name that source.

- Software, patches, tools, tests and documents: GPL-3.0-only
  ([LICENSE](LICENSE)). New source files carry the line
  `SPDX-License-Identifier: GPL-3.0-only`.
- Artwork: CC BY 4.0 ([LICENSES/CC-BY-4.0.txt](LICENSES/CC-BY-4.0.txt)).
- The Beryllium name and logo are reserved:
  [TRADEMARKS.md](TRADEMARKS.md).

There is no contributor agreement to sign.

## Conduct

Be civil and stay on the subject. Criticise code and claims as hard as
you like, and leave the person out of it. The maintainer may hide
comments, close threads or block accounts that make the project unpleasant
to work on.

## What to expect

One person reads everything, in spare time. Expect a first answer within
about a week; if two weeks pass, a reminder on the thread is welcome. A
pull request may be closed with a reason, most often because a setting
already covers it or because the change belongs upstream. That is a
decision about the change, and a better-aimed one is welcome.
