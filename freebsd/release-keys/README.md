# Release signing keys

Every Beryllium release from 0.20.3.19 carries two small files beside the
package: `RELEASE`, which names the release and lists the SHA-256 of each
file in it, and `RELEASE.sig`, the signature of `RELEASE` made with a key
that is not on GitHub. `install.sh` checks the signature, then the
release's name and version, then the package's digest, and installs
nothing if any of them fails. The design, what it protects against and
what it does not, is in [plan/18](../../plan/18-REMAINING-WORK.md)
section 5.

## The keys

| Key | Fingerprint | Accepted |
|---|---|---|
| Key file on the build machine, `release@beryllium` | `SHA256:WqmnUvCQV4s8rrrKuaM7zov/qa8jzHgTPQPfkJI99lc` (ED25519) | from 11 November 2026 until the end of 2026 |

Two hardware tokens (YubiKey 5C NFC) are to replace the key file. They
were ordered on 12 November 2026 and are not in this list yet.

The key file is the first stage. It protects a release against someone
who gets at the GitHub account, or a token for it, and nothing else. It
does not protect against code running as the maintainer on the build
machine, which can read the file. That is why it stops being accepted at
the end of 2026 without anyone having to remove it: **a release signed
with a hardware token has to be out before 1 January 2027, or the
installer will refuse the latest release from that day.**

`allowed_signers` and `revoked_keys` in this directory are the lists.
`install.sh` carries the same lines inside itself, because it is fetched
alone; `freebsd/tools/tests/test_install_sh.py` fails if they differ.

Whoever can change this repository's main branch can change both the
installer and these lists. Signing does not help against that. Compare
the fingerprint above with the one in `SECURITY.md`, in the manual page
(`man beryllium`, installed with the package), and in the notes of each
release.

## Checking a release by hand

Download `RELEASE`, `RELEASE.sig` and the package from the release, and
`allowed_signers` from this directory. Then:

```sh
ssh-keygen -Y verify -f allowed_signers -I release@beryllium -n beryllium-release -s RELEASE.sig < RELEASE
```

It must print `Good "beryllium-release" signature for release@beryllium`
with a fingerprint from the table above. Then compare the package with
the line for it in `RELEASE`:

```sh
sha256 beryllium-FreeBSD-16-amd64.pkg
```

```sh
grep beryllium-FreeBSD-16-amd64.pkg RELEASE
```

The installer does the same without installing anything:

```sh
sh install.sh --verify-only
```

## Signing a release (maintainer)

`freebsd/tools/publish-release` signs with `~/.ssh/beryllium-release`
(or `--key FILE`, or `BERYLLIUM_RELEASE_KEY`) and refuses to publish
without a signature. Before it uploads anything it runs this checkout's
`install.sh --verify-only` on the files it made, and after the upload it
runs it again on what GitHub serves.

The key file has a passphrase, is readable by the maintainer's account
alone, and is not kept loaded in an agent. Nothing that runs unattended
(a nightly test job, a build jail) runs as a user that can read it.

## When the hardware tokens arrive

1. On each token: `ssh-keygen -t ed25519-sk -O verify-required -C release@beryllium -f ~/.ssh/beryllium-release-token1`
   (and `-token2`). Each signature then needs the PIN and a touch. On
   FreeBSD the `security/u2f-devd` package gives the account access to
   the device. Not yet tried on the maintainer's machine.
2. Add both public keys to `allowed_signers` here and to the same list
   in `install.sh`, with `namespaces="beryllium-release"` and a
   `valid-after`. Keep one token somewhere else.
3. Sign one release with a token while the key file is still listed.
4. Put the key file's public key in `revoked_keys`, here and in
   `install.sh`, and delete the private key.

## Withdrawing a key

Add its public key line to `revoked_keys` here and in `install.sh`. The
installer refuses every release signed with it from then on, the old
ones too.
