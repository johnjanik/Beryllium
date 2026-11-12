# SPDX-License-Identifier: GPL-3.0-only
"""Tests for install.sh and freebsd/tools/publish-release.

They run the real scripts with POSIX sh against stand-ins for the FreeBSD
commands they call (pkg, poudriere, fetch, sysctl, ...), in --dry-run mode,
and check the commands the scripts would run.

Release signatures are made and checked with the real ssh-keygen and keys
made for the test. The installer under test is install.sh with its list
of release keys replaced by the test's key and nothing else changed; that
the real list is the one in freebsd/release-keys is a test of its own.
"""

import atexit
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
INSTALL = os.path.join(REPO, "install.sh")
PUBLISH = os.path.join(REPO, "freebsd", "tools", "publish-release")
BUILD_MANIFEST = os.path.join(REPO, "freebsd", "tools", "build-manifest")
CHECK_PROVENANCE = os.path.join(REPO, "freebsd", "tools", "check-provenance")

KEYS_DIR = os.path.join(REPO, "freebsd", "release-keys")
HAVE_SSH_KEYGEN = shutil.which("ssh-keygen") is not None
NAMESPACE = "beryllium-release"
SIGNER = "release@beryllium"

_keys = {}


def key(name="release"):
    """The path of a throwaway ed25519 key, made once for the test run."""
    if not _keys:
        d = tempfile.mkdtemp(prefix="beryllium-test-keys.")
        atexit.register(shutil.rmtree, d, True)
        _keys["dir"] = d
    path = os.path.join(_keys["dir"], name)
    if not os.path.exists(path):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", path],
                       check=True, capture_output=True)
    return path


def public(name="release"):
    with open(key(name) + ".pub") as f:
        return " ".join(f.read().split()[:2])


def signers_line(name="release", options=f'namespaces="{NAMESPACE}"'):
    return f"{SIGNER} {options} {public(name)}"


def list_lines(text):
    """The lines of a key list that are not comments or blank."""
    return [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]


EMBEDDED_RE = re.compile(r"(?s)(\n{name}\(\) \{{\n\tcat <<'EOF'\n)(.*?)(EOF\n\}}\n)")


def embedded(text, name):
    """The lines install.sh carries in allowed_signers() or revoked_keys()."""
    m = re.search(EMBEDDED_RE.pattern.format(name=name), text)
    assert m, name
    return m.group(2)


def installer_with(path, allowed, revoked="", known=None):
    """install.sh as it is, but for the two key lists it carries (and,
    with known, the SHA-256 by which it knows the last unsigned release)."""
    with open(INSTALL) as f:
        text = f.read()
    if known is not None:
        text, n = re.subn(r'(?m)^LAST_UNSIGNED_SHA256_16="[0-9a-f]{64}"$',
                          f'LAST_UNSIGNED_SHA256_16="{known}"', text)
        assert n == 1
    for name, lines in (("allowed_signers", allowed), ("revoked_keys", revoked)):
        pattern = EMBEDDED_RE.pattern.format(name=name)
        body = lines if not lines or lines.endswith("\n") else lines + "\n"
        text, n = re.subn(pattern, lambda m: m.group(1) + body + m.group(3), text)
        assert n == 1, name
    with open(path, "w") as f:
        f.write(text)
    return path


def sign(path, name="release", namespace=NAMESPACE):
    """path.sig, as ssh-keygen -Y sign writes it."""
    if os.path.exists(path + ".sig"):
        os.unlink(path + ".sig")
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", key(name), "-n", namespace, path],
                   check=True, capture_output=True)


HELIUM_COMMIT = "2f81b9cafa38a95071e20de3f9cd6b0aca6d3c65"
IMPORTED_FROM = ("ports_commit: 6ad3e0c82d8bada5971e0f83de2b4e9a796341d1\n"
                 "port: www/chromium 156.0.8078.47_1\nimported: 2026-11-01\n")

STUBS = {
    "uname": """
        case "$1" in
        -s) echo "${STUB_OS:-FreeBSD}" ;;
        -m) echo amd64 ;;
        -K) echo "${STUB_KERNVER:-1600012}" ;;
        esac""",
    "id": 'echo "${STUB_UID:-1001}"',
    "doas": 'echo "doas must not run in a dry run" >&2; exit 99',
    "pkg": """
        case "$1" in
        config) echo "${STUB_ABI:-FreeBSD:16:amd64}" ;;
        info) for p in $STUB_INSTALLED; do [ "$p" = "$3" ] && exit 0; done; exit 1 ;;
        query)
            if [ "$2" != -F ]; then   # the installed package
                [ "$2" = %v ] && echo "${STUB_INSTALLED_VERSION:-0.20.3.1}"
                exit 0
            fi
            case "$4" in
            %dn) for d in $STUB_DEPS; do echo "$d"; done ;;
            %q) echo "${STUB_PKGABI:-FreeBSD:16:amd64}" ;;
            %n-%v) echo "beryllium-${STUB_PKGVER:-0.20.3.1}" ;;
            %n) echo beryllium ;;
            %v) echo "${STUB_PKGVER:-0.20.3.1}" ;;
            esac ;;
        version)   # -t A B: how A stands to B
            if [ "$3" = "$4" ]; then echo "="
            elif [ "$(printf '%s\\n%s\\n' "$3" "$4" | sort -V | head -1)" = "$3" ]; then echo "<"
            else echo ">"; fi ;;
        *) echo "pkg $* must not run" >&2; exit 99 ;;
        esac""",
    "sysctl": """
        case "$2" in
        kern.ipc.shm_allow_removed) echo "${STUB_SHM:-0}" ;;
        hw.physmem) echo 137438953472 ;;
        esac""",
    "fetch": """
        echo "$4" >>"$STUB_LOG"
        case "$4" in
        file://*) f="${4#file://}" ;;
        *) f="$STUB_RELEASE/$(basename "$4")" ;;
        esac
        [ -f "$f" ] && cp "$f" "$3" """,
    "sha256": """
        if [ "$1" = -q ]; then sha256sum "$2" | cut -d' ' -f1
        else h=$(sha256sum "$2" | cut -d' ' -f1); echo "$h $2"; fi""",
    "freebsd-version": 'echo "${STUB_FBSDVER:-16.0-CURRENT}"',
    "zpool": 'printf "%s\\n" $STUB_POOLS',
    "poudriere": """
        case "$1" in
        jail) for j in $STUB_JAILS; do echo "$j 16.0-CURRENT amd64 http /x/jails/$j"; done ;;
        ports) for p in $STUB_PORTSTREES; do echo "$p git 2026-11-03 /x/ports/$p"; done ;;
        *) echo "poudriere $* must not run" >&2; exit 99 ;;
        esac""",
    "df": 'printf "Filesystem 1K-blocks Used Avail\\nzroot 1 1 %s\\n" "${STUB_FREE:-900000000}"',
}


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for name, body in STUBS.items():
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + textwrap.dedent(body).strip() + "\n")
            os.chmod(path, 0o755)
        self.release = os.path.join(self.tmp, "release")
        os.makedirs(self.release)
        self.log = os.path.join(self.tmp, "fetch.log")
        open(self.log, "w").close()
        self.env = {
            "PATH": self.bin + os.pathsep + os.environ["PATH"],
            "HOME": os.path.join(self.tmp, "home"),
            "TMPDIR": self.tmp,
            "STUB_LOG": self.log,
            "STUB_RELEASE": self.release,
            "STUB_INSTALLED": "nss",
            "STUB_DEPS": "nss gtk3 noto-basic noto-sans-sc noto-emoji",
            "STUB_POOLS": "zroot",
            "STUB_JAILS": "",
            "STUB_PORTSTREES": "",
            "BERYLLIUM_POUDRIERE_CONF": os.path.join(self.tmp, "poudriere.conf"),
        }
        # install.sh with the test's key in place of the release keys.
        self.installer = INSTALL
        if HAVE_SSH_KEYGEN:
            self.installer = installer_with(os.path.join(self.tmp, "install.sh"), signers_line())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    COMMIT = "c0ffee" * 6 + "c0ff"

    def manifest_text(self, lines, version="0.20.3.1", tag="v0.20.3.1"):
        return "\n".join(["beryllium-release 1", f"version {version}", f"tag {tag}",
                          f"commit {self.COMMIT}", "date 2026-11-12", *lines]) + "\n"

    def publish(self, majors=(16,), corrupt=False, version="0.20.3.1", tag="v0.20.3.1",
                signed=True, signer="release", namespace=NAMESPACE, manifest=None):
        """A release where the fetch stand-in finds it: the packages,
        SHA256SUMS, and (unless signed is False) the manifest RELEASE with
        its signature. manifest: a function from the manifest's text to
        the text to sign instead."""
        sums, lines = [], []
        for m in majors:
            name = f"beryllium-FreeBSD-{m}-amd64.pkg"
            data = f"package for {m}".encode()
            with open(os.path.join(self.release, name), "wb") as f:
                f.write(data)
            digest = hashlib.sha256(b"tampered" if corrupt else data).hexdigest()
            sums.append(f"{digest} {name}")
            lines.append(f"sha256 {digest}  {name}")
        with open(os.path.join(self.release, "SHA256SUMS"), "w") as f:
            f.write("\n".join(sums) + "\n")
        if not signed:
            return
        text = self.manifest_text(lines, version, tag)
        if manifest is not None:
            text = manifest(text)
        with open(os.path.join(self.release, "RELEASE"), "wb") as f:
            f.write(text if isinstance(text, bytes) else text.encode())
        sign(os.path.join(self.release, "RELEASE"), signer, namespace)

    def run_sh(self, script, *args, **env):
        e = dict(self.env, **env)
        return subprocess.run(["sh", script, *args], env=e, capture_output=True,
                              text=True, timeout=60)

    def fetched(self):
        with open(self.log) as f:
            return f.read().split()


@unittest.skipUnless(HAVE_SSH_KEYGEN, "needs ssh-keygen")
class InstallPackageTests(Harness):
    def test_installs_missing_dependencies_then_package(self):
        self.publish()
        r = self.run_sh(self.installer, "--dry-run", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("Signature verified: Good \"beryllium-release\" signature for "
                      "release@beryllium", out)
        self.assertIn(f"Release: Beryllium 0.20.3.1 (v0.20.3.1), dated 2026-11-12, "
                      f"source commit {self.COMMIT}", out)
        self.assertIn("SHA-256 verified", out)
        self.assertIn("+ doas pkg install -y gtk3 noto-basic noto-sans-sc noto-emoji\n", out)
        self.assertRegex(out, r"\+ doas pkg add \S+/beryllium-FreeBSD-16-amd64\.pkg\n")
        self.assertIn("+ doas sysctl kern.ipc.shm_allow_removed=1\n", out)
        self.assertIn("+ doas sysrc -f /etc/sysctl.conf kern.ipc.shm_allow_removed=1\n", out)
        self.assertIn("no sandbox yet", out)
        base = "https://github.com/johnjanik/Beryllium/releases/latest/download/"
        self.assertEqual(self.fetched(), [base + "RELEASE", base + "RELEASE.sig",
                                          base + "beryllium-FreeBSD-16-amd64.pkg"])

    def test_reinstall_forces_and_shm_already_set(self):
        self.publish()
        r = self.run_sh(self.installer, "--dry-run", "--yes",
                        STUB_INSTALLED="nss gtk3 noto-basic noto-sans-sc noto-emoji beryllium", STUB_SHM="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("All dependencies are installed.", r.stdout)
        self.assertRegex(r.stdout, r"\+ doas pkg add -f \S+\.pkg\n")
        self.assertNotIn("sysctl kern.ipc", r.stdout)

    def test_checksum_mismatch_installs_nothing(self):
        self.publish(corrupt=True)
        r = self.run_sh(self.installer, "--dry-run", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checksum mismatch", r.stderr)
        self.assertNotIn("pkg add", r.stdout)
        self.assertNotIn("pkg install", r.stdout)

    def test_no_package_for_this_version(self):
        self.publish(majors=(15,))
        r = self.run_sh(self.installer, "--dry-run", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("none for FreeBSD 16", r.stderr)
        self.assertIn("beryllium-FreeBSD-15-amd64.pkg", r.stdout)

    def test_package_abi_must_match_machine(self):
        self.publish()
        r = self.run_sh(self.installer, "--dry-run", "--yes", STUB_PKGABI="FreeBSD:15:amd64")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is for FreeBSD:15:amd64", r.stderr)

    def test_no_release_suggests_build(self):
        r = self.run_sh(self.installer, "--dry-run", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no published Beryllium release", r.stderr)
        self.assertIn("--build", r.stderr)

    def test_named_release(self):
        self.publish(tag="v0.20.3.1-1")
        r = self.run_sh(self.installer, "--dry-run", "--yes", "--release", "v0.20.3.1-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fetched()[0],
                         "https://github.com/johnjanik/Beryllium/releases/download/v0.20.3.1-1/RELEASE")

    def test_refuses_other_systems(self):
        r = self.run_sh(self.installer, "--dry-run", "--yes", STUB_OS="Linux")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Beryllium is for FreeBSD", r.stderr)

    def test_runs_without_sudo_as_root(self):
        self.publish()
        r = self.run_sh(self.installer, "--dry-run", "--yes", STUB_UID="0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\n\+ pkg add \S+\.pkg\n")

    def test_help(self):
        r = self.run_sh(self.installer, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("sh install.sh --build", r.stdout)


@unittest.skipUnless(HAVE_SSH_KEYGEN, "needs ssh-keygen")
class SignedReleaseTests(Harness):
    """What the installer must refuse (plan/18 section 5.5). The signature
    is a real one, made with ssh-keygen; the installer is install.sh with
    the test's key in its list."""

    def install(self, *args, installer=None, **env):
        return self.run_sh(installer or self.installer, "--dry-run", "--yes", *args, **env)

    def refused(self, r, *needles):
        self.assertNotEqual(r.returncode, 0, r.stdout)
        for needle in needles:
            self.assertIn(needle, r.stderr)
        self.assertIn("Nothing was installed", r.stderr)
        for never in ("pkg add", "pkg install", "doas"):
            self.assertNotIn(never, r.stdout)

    def package_was_fetched(self):
        return any(u.endswith(".pkg") for u in self.fetched())

    def path(self, name):
        return os.path.join(self.release, name)

    def test_no_signature(self):
        self.publish()
        os.unlink(self.path("RELEASE.sig"))
        self.refused(self.install(), "has no signature beside it")
        self.assertFalse(self.package_was_fetched())

    def test_empty_signature(self):
        self.publish()
        open(self.path("RELEASE.sig"), "w").close()
        self.refused(self.install(), "does not verify")
        self.assertFalse(self.package_was_fetched())

    def test_manifest_changed_after_signing(self):
        self.publish()
        with open(self.path("RELEASE")) as f:
            text = f.read()
        with open(self.path("RELEASE"), "w") as f:
            f.write(text.replace("version 0.20.3.1", "version 0.20.3.9"))
        self.refused(self.install(), "does not verify")
        self.assertFalse(self.package_was_fetched())

    def test_signature_from_another_key(self):
        self.publish(signer="another")
        self.refused(self.install(), "does not verify")

    def test_signature_for_another_purpose(self):
        """The same key, signing in another namespace (a file, a git commit)."""
        self.publish(namespace="file")
        self.refused(self.install(), "does not verify")

    def test_withdrawn_key(self):
        self.publish()
        installer = installer_with(os.path.join(self.tmp, "revoked.sh"), signers_line(),
                                   revoked=public())
        self.refused(self.install(installer=installer), "does not verify")

    def test_key_outside_its_validity(self):
        self.publish()
        for window in ('valid-before="20260101"', 'valid-after="20990101"'):
            installer = installer_with(
                os.path.join(self.tmp, "window.sh"),
                signers_line(options=f'namespaces="{NAMESPACE}",{window}'))
            self.refused(self.install(installer=installer), "does not verify")

    def test_an_older_release_served_as_the_one_asked_for(self):
        self.publish(tag="v0.20.3.1")
        r = self.install("--release", "v0.20.3.2")
        self.refused(r, "asked for release v0.20.3.2, and the signed manifest is that of v0.20.3.1")
        self.assertFalse(self.package_was_fetched())

    def test_an_older_release_served_as_the_latest(self):
        self.publish(version="0.20.3.1")
        newer = {"STUB_INSTALLED": "nss gtk3 noto-basic noto-sans-sc noto-emoji beryllium",
                 "STUB_INSTALLED_VERSION": "0.20.3.5"}
        r = self.install(**newer)
        self.refused(r, "Beryllium 0.20.3.5 is installed", "which is older", "--allow-downgrade")
        self.assertFalse(self.package_was_fetched())
        r = self.install("--allow-downgrade", **newer)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\+ doas pkg add -f \S+\.pkg\n")
        # asked for by name, an older release is what was asked for
        r = self.install("--release", "v0.20.3.1", **newer)
        self.assertEqual(r.returncode, 0, r.stderr)
        # and the same version again is a reinstall, not a downgrade
        r = self.install(**dict(newer, STUB_INSTALLED_VERSION="0.20.3.1"))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_package_is_another_version_than_the_manifest_says(self):
        self.publish(version="0.20.3.2")
        r = self.install()
        self.refused(r, "the package says it is version 0.20.3.1, and the signed manifest "
                        "says 0.20.3.2")

    def test_a_signed_manifest_that_is_not_one(self):
        """Signed with the right key, so that only the parser stands in
        the way: nothing in such a manifest may be acted on."""
        digest = "a" * 64
        pkg = "beryllium-FreeBSD-16-amd64.pkg"
        cases = {
            "two lines for one file": lambda t: t + f"sha256 {digest}  {pkg}\n",
            "a path": lambda t: t + f"sha256 {digest}  ../../etc/passwd\n",
            "a path in a name": lambda t: t + f"sha256 {digest}  sub/dir.pkg\n",
            "a hidden name": lambda t: t + f"sha256 {digest}  .profile\n",
            "carriage returns": lambda t: t.replace("\n", "\r\n"),
            "a control character": lambda t: t.replace("date ", "date \x1b[2J"),
            "an unknown field": lambda t: t + "run rm -rf /\n",
            "a field twice": lambda t: t + "version 9.9.9\n",
            "no date": lambda t: "".join(l for l in t.splitlines(True) if not l.startswith("date")),
            "another format": lambda t: t.replace("beryllium-release 1", "beryllium-release 2"),
            "a tag with a command": lambda t: t.replace("tag v0.20.3.1", "tag v0.20.3.1;reboot"),
            "a version with a command": lambda t: t.replace("version 0.20.3.1", "version $(reboot)"),
            "a word too many": lambda t: t.replace("version 0.20.3.1", "version 0.20.3.1 x"),
            "a short digest": lambda t: t + "sha256 abc  other.pkg\n",
            "a short commit": lambda t: t.replace(self.COMMIT, "c0ffee"),
            "no files": lambda t: "".join(l for l in t.splitlines(True) if not l.startswith("sha256")),
            "nothing": lambda t: "",
            "a long line": lambda t: t + "sha256 " + digest + "  " + "a" * 400 + "\n",
        }
        for name, change in cases.items():
            with self.subTest(name):
                open(self.log, "w").close()
                self.publish(manifest=change)
                r = self.install()
                self.refused(r, "release manifest")
                self.assertFalse(self.package_was_fetched(), name)

    def test_a_manifest_of_a_megabyte(self):
        self.publish(manifest=lambda t: t + "sha256 " + "a" * 64 + "  " + "b" * (1 << 20) + "\n")
        self.refused(self.install(), "a real one is a few hundred")
        self.assertFalse(self.package_was_fetched())

    def test_without_ssh_keygen(self):
        """A minimal system: refused with the reason, never a fall back to
        the checksum file."""
        farm = os.path.join(self.tmp, "farm")
        os.makedirs(farm)
        for d in ("/bin", "/usr/bin"):
            for name in os.listdir(d):
                link = os.path.join(farm, name)
                if name != "ssh-keygen" and not os.path.lexists(link):
                    os.symlink(os.path.join(d, name), link)
        self.publish()
        r = self.install(PATH=self.bin + os.pathsep + farm)
        self.refused(r, "ssh-keygen is needed to check the release's signature")
        self.assertFalse(self.package_was_fetched())

    def test_an_unsigned_release_is_refused(self):
        self.publish(signed=False)
        r = self.install("--release", "v0.20.3.12")
        self.refused(r, "is not signed", "sh install.sh --release v0.20.3.12 --allow-unsigned")
        self.assertFalse(self.package_was_fetched())
        # as the latest: a signed release is out, so nothing else is taken
        r = self.install()
        self.refused(r, "the latest release is not signed", "sh install.sh --release v0.20.3.18")
        self.assertFalse(self.package_was_fetched())
        # and from a place of the user's choosing
        r = self.install("--from", "file://" + self.release)
        self.refused(r, "the latest release is not signed")

    def test_the_last_unsigned_release_is_known_by_its_digest(self):
        """0.20.3.18, the release before signing: asked for by its name,
        its package installs without a signature because the installer
        carries its SHA-256, and nothing else is taken for it. As the
        latest release it is not taken: that ended when 0.20.3.19, the
        first signed release, was published."""
        self.publish(signed=False)
        with open(self.path("beryllium-FreeBSD-16-amd64.pkg"), "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        knows = installer_with(os.path.join(self.tmp, "knows.sh"), signers_line(), known=digest)
        env = {"STUB_PKGVER": "0.20.3.18"}
        named = ("--release", "v0.20.3.18")
        r = self.install(*named, installer=knows, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("This installer knows its package by its SHA-256", r.stdout)
        self.assertRegex(r.stdout, r"\+ doas pkg add \S+\.pkg\n")
        self.assertNotIn("NOT VERIFIED", r.stdout)
        # offered as the latest, the same bytes are refused: no signature
        open(self.log, "w").close()
        r = self.install(installer=knows, **env)
        self.refused(r, "the latest release is not signed", "sh install.sh --release v0.20.3.18")
        self.assertFalse(self.package_was_fetched())
        # the checksum file beside it is not what decides
        with open(self.path("SHA256SUMS"), "w") as f:
            f.write("0" * 64 + " beryllium-FreeBSD-16-amd64.pkg\n")
        self.assertEqual(self.install(*named, installer=knows, **env).returncode, 0)
        # another package under that name: the real installer knows another digest
        r = self.install(*named, **env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checksum mismatch", r.stderr)
        self.assertNotIn("pkg add", r.stdout)
        # the right bytes saying they are another version
        r = self.install(*named, installer=knows, STUB_PKGVER="0.20.3.17")
        self.refused(r, "the package says it is version 0.20.3.17")
        # no other machine's package is known
        self.publish(majors=(15,), signed=False)
        r = self.install(*named, installer=knows, STUB_ABI="FreeBSD:15:amd64", **env)
        self.refused(r, "this release (v0.20.3.18) is not signed")

    def test_the_installer_knows_0_20_3_18_as_it_was_published(self):
        with open(INSTALL) as f:
            text = f.read()
        self.assertIn('LAST_UNSIGNED_TAG="v0.20.3.18"', text)
        self.assertIn('LAST_UNSIGNED_SHA256_16="0094119e7283cec3f8ff8a3388a615c4debc04738d513b63'
                      'f8bc0f7981bb1c26"', text)

    def test_an_older_release_by_name_and_on_request(self):
        self.publish(signed=False)
        r = self.install("--release", "v0.20.3.18", "--allow-unsigned")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NOT VERIFIED BY SIGNATURE", r.stdout)
        self.assertRegex(r.stdout, r"\+ doas pkg add \S+\.pkg\n")
        self.assertNotIn("Signature verified", r.stdout)
        # never for the latest, and never from a place of the user's choosing
        r = self.install("--allow-unsigned")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--allow-unsigned goes with --release TAG", r.stderr)
        r = self.install("--release", "v0.20.3.18", "--allow-unsigned", "--from", "file:///x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("they must be signed", r.stderr)
        # a checksum that does not match is still refused
        self.publish(signed=False, corrupt=True)
        r = self.install("--release", "v0.20.3.18", "--allow-unsigned")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checksum mismatch", r.stderr)

    def test_verify_only_installs_nothing(self):
        self.publish()
        r = self.run_sh(self.installer, "--verify-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Signature verified", r.stdout)
        self.assertIn("Verified: the signature, the release's name and version, and the package. "
                      "Nothing was installed", r.stdout)
        for never in ("pkg add", "pkg install", "Install beryllium", "doas"):
            self.assertNotIn(never, r.stdout)
        # a release with no package for this machine: its signature is checked all the same
        os.unlink(self.path("beryllium-FreeBSD-16-amd64.pkg"))
        self.publish(majors=(15,))
        r = self.run_sh(self.installer, "--verify-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("There is no package for FreeBSD 16", r.stdout)
        # and a bad one fails it
        self.publish(signer="another")
        r = self.run_sh(self.installer, "--verify-only")
        self.assertNotEqual(r.returncode, 0)

    def test_files_from_another_place_are_verified_the_same_way(self):
        self.publish()
        mirror = os.path.join(self.tmp, "mirror")
        shutil.copytree(self.release, mirror)
        r = self.install("--from", "file://" + mirror, STUB_RELEASE=os.path.join(self.tmp, "none"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fetched()[0], f"file://{mirror}/RELEASE")
        with open(os.path.join(mirror, "RELEASE"), "a") as f:
            f.write("x\n")
        r = self.install("--from", "file://" + mirror, STUB_RELEASE=os.path.join(self.tmp, "none"))
        self.refused(r, "does not verify")

    def test_the_options_belong_to_installing_a_release(self):
        for args in (["--build", "--verify-only"], ["--uninstall", "--allow-downgrade"],
                     ["--build", "--from", "file:///x"]):
            r = self.install(*args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn("are for installing a release", r.stderr)
        r = self.install("--release", "v1", "--allow-unsigned", "--verify-only")
        self.assertIn("--verify-only checks a signature", r.stderr)


@unittest.skipUnless(HAVE_SSH_KEYGEN, "needs ssh-keygen")
class ReleaseKeys(unittest.TestCase):
    """The keys install.sh trusts are the ones the repository lists, and
    their fingerprints stand where a person is told to look for them."""

    def read(self, *parts):
        with open(os.path.join(REPO, *parts)) as f:
            return f.read()

    def test_the_installer_carries_the_repositorys_lists(self):
        text = self.read("install.sh")
        self.assertEqual(list_lines(embedded(text, "allowed_signers")),
                         list_lines(self.read("freebsd", "release-keys", "allowed_signers")))
        self.assertEqual(list_lines(embedded(text, "revoked_keys")),
                         list_lines(self.read("freebsd", "release-keys", "revoked_keys")))
        self.assertTrue(list_lines(embedded(text, "allowed_signers")), "no release key at all")

    def test_every_key_is_for_releases_only_and_has_a_start(self):
        for line in list_lines(self.read("freebsd", "release-keys", "allowed_signers")):
            principal, options, keytype, blob = line.split()[:4]
            self.assertEqual(principal, SIGNER)
            self.assertIn(f'namespaces="{NAMESPACE}"', options)
            self.assertIn("valid-after=", options)
            self.assertIn(keytype, ("ssh-ed25519", "sk-ssh-ed25519@openssh.com"))
            if keytype == "ssh-ed25519":   # a key that is a file: accepted for a while only
                self.assertIn("valid-before=", options, "a key file with no end")

    def test_no_listed_key_is_also_withdrawn(self):
        allowed = {" ".join(l.split()[2:4])
                   for l in list_lines(self.read("freebsd", "release-keys", "allowed_signers"))}
        revoked = {" ".join(l.split()[:2])
                   for l in list_lines(self.read("freebsd", "release-keys", "revoked_keys"))}
        self.assertEqual(allowed & revoked, set())

    def test_the_fingerprints_are_where_people_are_told_to_look(self):
        tmp = tempfile.mkdtemp()
        try:
            for line in list_lines(self.read("freebsd", "release-keys", "allowed_signers")):
                pub = os.path.join(tmp, "k.pub")
                with open(pub, "w") as f:
                    f.write(" ".join(line.split()[2:4]) + "\n")
                out = subprocess.run(["ssh-keygen", "-lf", pub], capture_output=True, text=True,
                                     check=True).stdout
                fingerprint = out.split()[1]
                self.assertTrue(fingerprint.startswith("SHA256:"), out)
                for where in (("freebsd", "release-keys", "README.md"), ("SECURITY.md",),
                              ("freebsd", "release-keys", "allowed_signers"),
                              ("man", "beryllium.1")):
                    self.assertIn(fingerprint.replace("SHA256:", ""),
                                  self.read(*where).replace("\\&", ""), where)
        finally:
            shutil.rmtree(tmp)


class InstallBuildTests(Harness):
    def test_fresh_16_current_machine(self):
        r = self.run_sh(INSTALL, "--build", "--dry-run", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        src = os.path.join(self.env["HOME"], "Beryllium")
        for line in [
                "+ doas pkg install -y poudriere",
                f"+ git clone --branch main --recurse-submodules "
                f"https://github.com/johnjanik/Beryllium.git {src}",
                "    ZPOOL=zroot",
                "    USE_TMPFS=no",
                "    ALLOW_MAKE_JOBS=yes",
                "+ doas poudriere jail -c -j 160amd64 -v 16.0-CURRENT -a amd64",
                "+ doas poudriere ports -c -p default",
                f"+ doas poudriere ports -c -p beryllium -m null -M {src}/freebsd/ports",
                "+ doas poudriere bulk -j 160amd64 -p default -O beryllium -b latest www/beryllium",
                "+ pkg add <the new beryllium package>"]:
            self.assertIn(line + "\n", out)
        self.assertIn("data/logs/bulk/160amd64-default/latest/logs/", out)
        self.assertNotIn("ccache", out, "a build without --ccache must stay a clean build")

    def test_15_release_machine_with_existing_setup(self):
        conf = self.env["BERYLLIUM_POUDRIERE_CONF"]
        with open(conf, "w") as f:
            f.write("ZPOOL=tank\nBASEFS=/usr/local/poudriere\nUSE_TMPFS=no\n"
                    "ALLOW_MAKE_JOBS=yes\nMAX_EXECUTION_TIME=200000\nNOHANG_TIME=28800\n"
                    "DISTFILES_CACHE=/usr/ports/distfiles\n")
        r = self.run_sh(INSTALL, "--build", "--dry-run", "--yes",
                        STUB_FBSDVER="15.1-RELEASE-p3", STUB_ABI="FreeBSD:15:amd64",
                        STUB_INSTALLED="poudriere git python3",
                        STUB_JAILS="151amd64", STUB_PORTSTREES="default beryllium")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("Already set up for Beryllium.", out)
        self.assertIn("Jail 151amd64 exists.", out)
        self.assertIn("Ports tree 'beryllium' exists.", out)
        self.assertIn("+ doas poudriere bulk -j 151amd64 ", out)
        self.assertNotIn("pkg install", out)
        self.assertNotIn("poudriere jail -c", out)

    def test_poudriere_devel_counts_as_installed(self):
        r = self.run_sh(INSTALL, "--build", "--dry-run", "--yes",
                        STUB_INSTALLED="poudriere-devel")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("pkg install", r.stdout)

    def test_several_pools_need_a_choice(self):
        r = self.run_sh(INSTALL, "--build", "--dry-run", "--yes", STUB_POOLS="tank data")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("several ZFS pools", r.stderr)

    # --ccache: a compiler cache for the build set "ccache" and no other.

    def ccache_build(self, *args, **env):
        return self.run_sh(INSTALL, "--build", "--ccache", "--dry-run", "--yes", *args, **env)

    def stub_ls(self, owner):
        """ls -ld DIR, as on a machine where DIR belongs to owner."""
        path = os.path.join(self.bin, "ls")
        with open(path, "w") as f:
            f.write('#!/bin/sh\necho "drwxr-xr-x  2 %s %s  3 Nov 11 12:00 $2"\n'
                    % tuple(owner.split(":")))
        os.chmod(path, 0o755)

    def test_ccache_is_its_own_build_set(self):
        r = self.ccache_build()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        d = os.path.join(self.tmp, "poudriere.d")
        cache = "/usr/local/poudriere/ccache-beryllium"
        for line in [
                f"+ doas mkdir -p {d}",
                f"+ append to {d}/ccache-poudriere.conf:",
                f"    CCACHE_DIR={cache}",
                "    CCACHE_DIR_NON_ROOT_SAFE=yes",
                f"+ doas mkdir -p {cache}",
                f"+ write {cache}/ccache.conf: max_size = 30G",
                f"+ doas chown -R nobody:nobody {cache}",
                "+ doas poudriere bulk -j 160amd64 -p default -z ccache -O beryllium "
                "-b latest www/beryllium"]:
            self.assertIn(line + "\n", out)
        # the set's own logs, not those of a clean build
        self.assertIn("data/logs/bulk/160amd64-default-ccache/latest/logs/", out)
        self.assertIn("publish-release refuses to\npublish it", out)
        # the main configuration gets no cache: other builds stay clean
        main = out.split("Compiler cache for the build set")[0]
        self.assertNotIn("CCACHE", main)
        self.assertFalse(os.path.exists(d), "a dry run changed the system")

    def test_ccache_goes_with_build(self):
        self.publish()
        r = self.run_sh(INSTALL, "--ccache", "--dry-run", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--ccache goes with --build", r.stderr)
        self.assertNotIn("pkg add", r.stdout)

    def test_ccache_keeps_an_existing_setup(self):
        d = os.path.join(self.tmp, "poudriere.d")
        cache = os.path.join(self.tmp, "cache")
        os.makedirs(d)
        os.makedirs(cache)
        with open(os.path.join(d, "ccache-poudriere.conf"), "w") as f:
            f.write(f"CCACHE_DIR={cache}\nCCACHE_DIR_NON_ROOT_SAFE=yes\n")
        self.stub_ls("nobody:nobody")
        r = self.ccache_build()
        self.assertEqual(r.returncode, 0, r.stderr)
        section = r.stdout.split("Compiler cache for the build set")[1].split("==>")[0]
        self.assertIn("Already set up.", section)
        self.assertIn(f"  {cache}\n", section)
        self.assertNotIn("\n+ ", section, "an existing setup was changed")
        self.assertNotIn("belongs to", r.stderr)
        self.assertIn("-z ccache ", r.stdout)

    def test_ccache_directory_named_in_the_set_file_is_used(self):
        """The owner may move the cache: CCACHE_DIR in the set's file wins."""
        d = os.path.join(self.tmp, "poudriere.d")
        os.makedirs(d)
        with open(os.path.join(d, "ccache-poudriere.conf"), "w") as f:
            f.write("CCACHE_DIR=/tank/ccache\n")
        r = self.ccache_build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("+ doas mkdir -p /tank/ccache\n", r.stdout)
        self.assertIn("    CCACHE_DIR_NON_ROOT_SAFE=yes\n", r.stdout)
        self.assertNotIn("CCACHE_DIR=/usr/local/poudriere", r.stdout)

    def test_ccache_directory_belongs_to_whoever_compiles(self):
        conf = self.env["BERYLLIUM_POUDRIERE_CONF"]
        for text, owner in [("BUILD_AS_NON_ROOT=no\n", "root:wheel"),
                            ("PORTBUILD_USER=root\n", "root:wheel"),
                            ("PORTBUILD_USER=builder\nPORTBUILD_UID=2000\n", "2000:2000"),
                            ("PORTBUILD_USER=builder\n", "65532:65532"),
                            ("BASEFS=/pd\n", "nobody:nobody")]:
            with open(conf, "w") as f:
                f.write(text)
            r = self.ccache_build()
            self.assertEqual(r.returncode, 0, r.stderr)
            base = "/pd" if "BASEFS" in text else "/usr/local/poudriere"
            self.assertIn(f"+ doas chown -R {owner} {base}/ccache-beryllium\n", r.stdout, text)

    def test_ccache_warns_about_a_directory_the_build_cannot_write(self):
        d = os.path.join(self.tmp, "poudriere.d")
        cache = os.path.join(self.tmp, "cache")
        os.makedirs(d)
        os.makedirs(cache)
        with open(os.path.join(d, "ccache-poudriere.conf"), "w") as f:
            f.write(f"CCACHE_DIR={cache}\nCCACHE_DIR_NON_ROOT_SAFE=yes\n")
        self.stub_ls("root:wheel")
        r = self.ccache_build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{cache} belongs to root:wheel, but Poudriere compiles as nobody:nobody",
                      r.stderr)

    def test_ccache_warns_when_every_build_is_cached(self):
        with open(self.env["BERYLLIUM_POUDRIERE_CONF"], "w") as f:
            f.write("CCACHE_DIR=/var/cache/ccache\n")
        r = self.ccache_build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("every Poudriere build on this machine uses a compiler cache", r.stderr)
        r = self.run_sh(INSTALL, "--build", "--dry-run", "--yes")
        self.assertNotIn("compiler cache", r.stderr)

    def real_build(self, *args):
        """install.sh --build for real (no --dry-run), as root, against
        stand-ins that record what Poudriere and pkg were asked to do. The
        poudriere stand-in puts the package where Poudriere would:
        data/packages/<jail>-<tree>[-<set>]/All."""
        base = os.path.join(self.tmp, "pd")
        src = os.path.join(self.tmp, "src")
        os.makedirs(os.path.join(src, ".git"), exist_ok=True)
        os.makedirs(os.path.join(src, "freebsd", "tools"), exist_ok=True)
        stubs = {
            "id": "echo 0",
            "git": 'case "$*" in *"remote get-url"*) '
                   "echo https://github.com/johnjanik/Beryllium.git ;; esac",
            os.path.join(src, "freebsd", "tools", "sync-port"): "exit 0",
            "chown": 'echo "chown $*" >>"$STUB_LOG"',
            "ccache": 'echo "ccache $* in $CCACHE_DIR"',
            "pkg": """
                case "$1" in
                config) echo FreeBSD:16:amd64 ;;
                info) [ "$3" != beryllium ] ;;
                query) [ "$4" = %dn ] && echo nss ;;
                add) echo "pkg $*" >>"$STUB_LOG" ;;
                *) echo "pkg $* must not run" >&2; exit 99 ;;
                esac""",
            "poudriere": """
                case "$1" in
                jail) echo "160amd64 16.0-CURRENT amd64 http /x/jails/160amd64" ;;
                ports) echo "default git 2026-11-03 /x/ports/default"
                       echo "beryllium null 2026-11-03 /x/ports/beryllium" ;;
                bulk)
                    echo "poudriere $*" >>"$STUB_LOG"
                    shift; jail=""; tree=""; set=""
                    while [ $# -gt 0 ]; do
                        case "$1" in
                        -j) jail=$2; shift ;;
                        -p) tree=$2; shift ;;
                        -z) set=$2; shift ;;
                        esac
                        shift
                    done
                    d="$STUB_BASEFS/data/packages/$jail-$tree${set:+-$set}/All"
                    mkdir -p "$d" && : >"$d/beryllium-0.20.3.1.pkg" ;;
                esac""",
        }
        for name, body in stubs.items():
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + textwrap.dedent(body).strip() + "\n")
            os.chmod(path, 0o755)
        conf = self.env["BERYLLIUM_POUDRIERE_CONF"]
        if not os.path.exists(conf):
            with open(conf, "w") as f:
                f.write(f"ZPOOL=zroot\nBASEFS={base}\nDISTFILES_CACHE={self.tmp}/distfiles\n"
                        "USE_TMPFS=no\nALLOW_MAKE_JOBS=yes\nMAX_EXECUTION_TIME=172800\n"
                        "NOHANG_TIME=28800\n")
        open(self.log, "w").close()
        r = self.run_sh(INSTALL, "--build", "--yes", "--dir", src, *args,
                        STUB_BASEFS=base, STUB_SHM="1")
        with open(self.log) as f:
            return r, f.read().splitlines(), base

    def test_ccache_build_for_real(self):
        r, did, base = self.real_build("--ccache")
        self.assertEqual(r.returncode, 0, r.stderr)
        cache = os.path.join(base, "ccache-beryllium")
        setconf = os.path.join(self.tmp, "poudriere.d", "ccache-poudriere.conf")
        with open(setconf) as f:
            written = f.read()
        self.assertEqual(written,
                         "# Added by the Beryllium installer (install.sh --build --ccache)\n"
                         f"CCACHE_DIR={cache}\nCCACHE_DIR_NON_ROOT_SAFE=yes\n")
        with open(os.path.join(cache, "ccache.conf")) as f:
            self.assertEqual(f.read(), "max_size = 30G\n")
        pkgfile = os.path.join(base, "data", "packages", "160amd64-default-ccache", "All",
                               "beryllium-0.20.3.1.pkg")
        self.assertEqual(did, [
            f"chown -R nobody:nobody {cache}",
            "poudriere bulk -j 160amd64 -p default -z ccache -O beryllium -b latest www/beryllium",
            f"pkg add {pkgfile}"])
        self.assertIn("This package was built with a compiler cache: it is a test build",
                      r.stdout)
        self.assertIn(f"ccache -s in {cache}\n", r.stdout)
        with open(self.env["BERYLLIUM_POUDRIERE_CONF"]) as f:
            self.assertNotIn("CCACHE", f.read(), "the cache leaked into every build")

        # again: nothing is set up twice, and the cache is the same one
        r, did, _ = self.real_build("--ccache")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Already set up.", r.stdout)
        with open(setconf) as f:
            self.assertEqual(f.read(), written)
        self.assertEqual(len(did), 2, did)   # the build and the install, no chown

        # and a build without --ccache is still a clean one, in its own place
        r, did, _ = self.real_build()
        self.assertEqual(r.returncode, 0, r.stderr)
        clean = os.path.join(base, "data", "packages", "160amd64-default", "All",
                             "beryllium-0.20.3.1.pkg")
        self.assertEqual(did, [
            "poudriere bulk -j 160amd64 -p default -O beryllium -b latest www/beryllium",
            f"pkg add {clean}"])
        self.assertNotIn("compiler cache", r.stdout)

    def test_help_names_ccache(self):
        r = self.run_sh(INSTALL, "--help")
        self.assertIn("--ccache", r.stdout)
        self.assertIn("a release is built without it", r.stdout)

    def test_uninstall(self):
        r = self.run_sh(INSTALL, "--uninstall", "--dry-run", "--yes",
                        STUB_INSTALLED="beryllium")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("+ doas pkg delete -y beryllium\n", r.stdout)


def fake_checkout(root, patches=("security/one.patch", "ui/two.patch"), revision=1):
    """A checkout with what check-provenance reads: the Chromium version, the
    port's Makefile.helium and IMPORTED-FROM, and a patch series."""
    port = os.path.join(root, "freebsd", "ports", "www", "beryllium")
    os.makedirs(os.path.join(root, "helium"))
    os.makedirs(os.path.join(port, "files"))
    with open(os.path.join(root, "helium", "chromium_version.txt"), "w") as f:
        f.write("156.0.8078.79\n")
    with open(os.path.join(port, "Makefile.helium"), "w") as f:
        f.write(f"# Generated\nHELIUM_COMMIT=\t\t{HELIUM_COMMIT}\nHELIUM_VERSION=\t\t0.20.3\n"
                f"CHROMIUM_VERSION=\t156.0.8078.79\nBERYLLIUM_REVISION=\t{revision}\n")
    with open(os.path.join(port, "files", "IMPORTED-FROM"), "w") as f:
        f.write(IMPORTED_FROM)
    digests = {}
    os.makedirs(os.path.join(root, "patches"), exist_ok=True)
    with open(os.path.join(root, "patches", "series"), "w") as f:
        f.write("# series\n" + "".join(p + "\n" for p in patches))
    for p in patches:
        path = os.path.join(root, "patches", p)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        body = f"Beryllium: {p}\n--- a/x\n+++ b/x\n".encode()
        with open(path, "wb") as f:
            f.write(body)
        digests[p] = hashlib.sha256(body).hexdigest()
    return digests


def manifest_for(root, digests, **overrides):
    """What build-manifest writes for fake_checkout(root)."""
    m = {
        "beryllium_version": "0.20.3.1",
        "chromium_version": "156.0.8078.79",
        "helium_commit": HELIUM_COMMIT,
        "bsd_patches": {k.strip(): v.strip() for k, v in
                        (l.split(":", 1) for l in IMPORTED_FROM.splitlines() if ":" in l)},
        "beryllium_patches": dict(digests),
        "gn_args": {}, "gn_arg_origin": {}, "hardening": {},
        "build_host": {"system": "FreeBSD", "release": "16.0-CURRENT", "machine": "amd64"},
        "sandbox_status": "none",
    }
    m.update(overrides)
    return m


def write_package(path, manifest, member="/usr/local/share/beryllium/BUILD-MANIFEST.json"):
    """A pkg-shaped tar: the two pkg manifests, then files by absolute path."""
    with tarfile.open(path, "w") as t:
        for name, data in [("+COMPACT_MANIFEST", b"{}"), ("+MANIFEST", b"{}"),
                           ("/usr/local/share/beryllium/beryllium", b"ELF"),
                           (member, (json.dumps(manifest, indent=2) + "\n").encode()
                            if manifest is not None else None)]:
            if data is None:
                continue
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


class CheckProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "repo")
        self.digests = fake_checkout(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def check(self, manifest, *args):
        path = os.path.join(self.tmp, "m.json")
        with open(path, "w") as f:
            f.write(manifest if isinstance(manifest, str) else json.dumps(manifest))
        return subprocess.run([sys.executable, CHECK_PROVENANCE, "--repo", self.root, *args, path],
                              capture_output=True, text=True, timeout=60)

    def test_matching_manifest(self):
        r = self.check(manifest_for(self.root, self.digests), "--version", "0.20.3.1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("built from this checkout: Beryllium 0.20.3.1, Chromium 156.0.8078.79", r.stdout)
        self.assertIn("2 patches", r.stdout)

    def test_port_revision_suffix_is_not_a_difference(self):
        r = self.check(manifest_for(self.root, self.digests), "--version", "0.20.3.1_2")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_changed_patch(self):
        changed = dict(self.digests, **{"ui/two.patch": "0" * 64})
        r = self.check(manifest_for(self.root, changed))
        self.assertEqual(r.returncode, 1)
        self.assertIn("beryllium_patches: ui/two.patch differs", r.stderr)

    def test_missing_and_extra_patches(self):
        d = dict(self.digests)
        del d["ui/two.patch"]
        d["privacy/three.patch"] = "1" * 64
        r = self.check(manifest_for(self.root, d))
        self.assertEqual(r.returncode, 1)
        self.assertIn("ui/two.patch in the checkout, not in the package", r.stderr)
        self.assertIn("privacy/three.patch in the package, not in the checkout", r.stderr)

    def test_other_versions_and_commits(self):
        r = self.check(manifest_for(self.root, self.digests, beryllium_version="0.20.3.2",
                                    helium_commit="abc", chromium_version="156.0.8078.80",
                                    bsd_patches={"ports_commit": "other"}))
        self.assertEqual(r.returncode, 1)
        for line in ["beryllium_version: package '0.20.3.2', checkout '0.20.3.1'",
                     "helium_commit: package 'abc'", "chromium_version: package '156.0.8078.80'",
                     "bsd_patches: ports_commit differs", "bsd_patches: port in the checkout"]:
            self.assertIn(line, r.stderr)

    def test_package_version_must_match_the_manifest(self):
        r = self.check(manifest_for(self.root, self.digests), "--version", "0.20.3.4")
        self.assertEqual(r.returncode, 1)
        self.assertIn("manifest '0.20.3.1', package '0.20.3.4'", r.stderr)

    def test_a_build_with_a_compiler_cache_is_not_a_release(self):
        """plan/04: a release is a clean build. Exit 3, so publish-release
        can say what is wrong; a manifest without the key predates it."""
        r = self.check(manifest_for(self.root, self.digests, compiler_cache="ccache"),
                       "--version", "0.20.3.1")
        self.assertEqual(r.returncode, 3)
        self.assertIn("built with a compiler cache (ccache)", r.stderr)
        self.assertNotIn("not built from this checkout", r.stderr)
        self.assertNotIn("built from this checkout:", r.stdout)
        r = self.check(manifest_for(self.root, self.digests, compiler_cache="none"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("compiler_cache", manifest_for(self.root, self.digests))

    def test_a_compiler_cache_and_other_patches_are_both_named(self):
        other = dict(self.digests, **{"ui/two.patch": "0" * 64})
        r = self.check(manifest_for(self.root, other, compiler_cache="ccache"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("built with a compiler cache", r.stderr)
        self.assertIn("ui/two.patch differs", r.stderr)

    def test_unreadable_manifest(self):
        r = self.check("not json")
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot read", r.stderr)
        r = self.check("[1, 2]")
        self.assertEqual(r.returncode, 2)


class BuildManifestTests(unittest.TestCase):
    """The tool the port runs at stage time (the port carries a copy, kept
    identical by sync-port --check)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "repo")
        self.digests = fake_checkout(self.root)
        self.gnargs = os.path.join(self.tmp, "gnargs.json")
        with open(self.gnargs, "w") as f:
            json.dump({"args": {"is_official_build": True}, "origin": {}, "hardening": {}}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def manifest(self, *extra):
        port = os.path.join(self.root, "freebsd", "ports", "www", "beryllium")
        r = subprocess.run(
            [sys.executable, BUILD_MANIFEST, "--gnargs-json", self.gnargs,
             "--imported-from", os.path.join(port, "files", "IMPORTED-FROM"),
             "--version", "0.20.3.1", "--chromium", "156.0.8078.79",
             "--helium-commit", HELIUM_COMMIT,
             "--patches-dir", os.path.join(self.root, "patches"), *extra],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def check(self, text):
        path = os.path.join(self.tmp, "BUILD-MANIFEST.json")
        with open(path, "w") as f:
            f.write(text)
        return subprocess.run([sys.executable, CHECK_PROVENANCE, "--repo", self.root,
                               "--version", "0.20.3.1", path],
                              capture_output=True, text=True, timeout=60).returncode

    def test_a_clean_build_says_so_and_can_be_released(self):
        text = self.manifest()
        self.assertEqual(json.loads(text)["compiler_cache"], "none")
        self.assertEqual(json.loads(text)["beryllium_patches"], self.digests)
        self.assertEqual(self.check(text), 0)

    def test_a_build_with_a_compiler_cache_says_so_and_cannot(self):
        text = self.manifest("--compiler-cache", "ccache")
        self.assertEqual(json.loads(text)["compiler_cache"], "ccache")
        self.assertEqual(self.check(text), 3)

    def test_the_port_records_the_ports_frameworks_cache_switch(self):
        with open(os.path.join(REPO, "freebsd", "ports", "www", "beryllium", "Makefile")) as f:
            makefile = f.read()
        self.assertIn(".if defined(WITH_CCACHE_BUILD) && !defined(NO_CCACHE)\n"
                      "BERYLLIUM_COMPILER_CACHE=\tccache\n"
                      ".else\nBERYLLIUM_COMPILER_CACHE=\tnone\n.endif\n", makefile)
        self.assertIn("\t\t--compiler-cache ${BERYLLIUM_COMPILER_CACHE} \\\n"
                      "\t\t> ${STAGEDIR}${DATADIR}/BUILD-MANIFEST.json\n", makefile)


@unittest.skipUnless(HAVE_SSH_KEYGEN, "needs ssh-keygen")
class PublishReleaseTests(Harness):
    def setUp(self):
        super().setUp()
        root = os.path.join(self.tmp, "repo")
        self.digests = fake_checkout(root)
        self.root = root
        # The checkout's installer and key list, with the test's key: what
        # publish-release verifies its own work against.
        installer_with(os.path.join(root, "install.sh"), signers_line())
        os.makedirs(os.path.join(root, "freebsd", "release-keys"))
        with open(os.path.join(root, "freebsd", "release-keys", "allowed_signers"), "w") as f:
            f.write("# the test's key\n" + signers_line() + "\n")
        self.env["BERYLLIUM_RELEASE_KEY"] = key()
        git = os.path.join(self.bin, "git")
        with open(git, "w") as f:
            f.write(textwrap.dedent(f"""\
                #!/bin/sh
                case "$*" in
                *show-toplevel*) echo {root} ;;
                *"rev-parse HEAD"*) echo 1234567890abcdef1234567890abcdef12345678 ;;
                *status*) [ -n "$STUB_DIRTY" ] && echo " M file" ; true ;;
                *"branch -r"*) [ -z "$STUB_UNPUSHED" ] && echo "  origin/main" ; true ;;
                esac
                """))
        os.chmod(git, 0o755)
        self.pkgfile = os.path.join(self.tmp, "beryllium-0.20.3.1.pkg")
        write_package(self.pkgfile, manifest_for(root, self.digests))

    def test_dry_run_layout_and_notes(self):
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1-1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("check-provenance: built from this checkout: Beryllium 0.20.3.1", out)
        self.assertIn("beryllium-FreeBSD-16-amd64.pkg", out)
        self.assertRegex(out, r"\+ gh release create v0\.20\.3\.1-1 --target 1234567890abcdef1234567890abcdef12345678 .* "
                              r"\S+/RELEASE \S+/RELEASE\.sig \S+/SHA256SUMS "
                              r"\S+/beryllium-FreeBSD-16-amd64\.pkg "
                              r"\S+/BUILD-MANIFEST-FreeBSD-16-amd64\.json\n")
        outdir = out.split("release files in ")[1].split(",")[0]
        with open(os.path.join(outdir, "NOTES.md")) as f:
            notes = f.read()
        self.assertIn("Corresponding source: commit 1234567890abcdef1234567890abcdef12345678", notes)
        self.assertIn("BUILD-MANIFEST-FreeBSD-<version>-amd64.json", notes)
        self.assertIn("no sandbox yet", notes)
        with open(os.path.join(outdir, "SHA256SUMS")) as f:
            self.assertRegex(f.read(), r"^[0-9a-f]{64} beryllium-FreeBSD-16-amd64\.pkg\n$")
        with open(os.path.join(outdir, "BUILD-MANIFEST-FreeBSD-16-amd64.json")) as f:
            self.assertEqual(json.load(f)["helium_commit"], HELIUM_COMMIT)
        shutil.rmtree(outdir)

    def test_the_release_is_signed_and_the_installer_accepts_it(self):
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("verifying what was made with this checkout's install.sh", r.stdout)
        self.assertIn("Verified: the signature, the release's name and version, and the package",
                      r.stdout)
        outdir = r.stdout.split("release files in ")[1].split(",")[0]
        with open(os.path.join(outdir, "RELEASE")) as f:
            manifest = f.read()
        self.assertRegex(manifest, r"\Aberyllium-release 1\nversion 0\.20\.3\.1\ntag v0\.20\.3\.1\n"
                                   r"commit 1234567890abcdef1234567890abcdef12345678\n"
                                   r"date \d{4}-\d\d-\d\d\n"
                                   r"sha256 [0-9a-f]{64}  beryllium-FreeBSD-16-amd64\.pkg\n"
                                   r"sha256 [0-9a-f]{64}  BUILD-MANIFEST-FreeBSD-16-amd64\.json\n\Z")
        with open(os.path.join(outdir, "beryllium-FreeBSD-16-amd64.pkg"), "rb") as f:
            self.assertIn(hashlib.sha256(f.read()).hexdigest(), manifest)
        with open(os.path.join(outdir, "RELEASE"), "rb") as signed:
            check = subprocess.run(
                ["ssh-keygen", "-Y", "verify", "-f",
                 os.path.join(self.root, "freebsd", "release-keys", "allowed_signers"),
                 "-I", SIGNER, "-n", NAMESPACE, "-s", os.path.join(outdir, "RELEASE.sig")],
                stdin=signed, capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        fingerprint = check.stdout.split(" key ")[1].strip()
        with open(os.path.join(outdir, "NOTES.md")) as f:
            notes = f.read()
        self.assertIn(fingerprint, notes)
        self.assertIn("sh install.sh --verify-only", notes)
        self.assertIn(f"signed with {fingerprint}", r.stdout)
        shutil.rmtree(outdir)

    def test_nothing_is_published_unsigned(self):
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1", self.pkgfile, STUB_DIRTY="",
                        STUB_UNPUSHED="", BERYLLIUM_RELEASE_KEY=os.path.join(self.tmp, "no-key"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no release signing key at", r.stderr)
        self.assertIn("a release is not published unsigned", r.stderr)
        self.assertNotIn("gh release create", r.stdout)
        r = self.run_sh(PUBLISH, "--dry-run", "--key", key(), "v0.20.3.1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="",
                        BERYLLIUM_RELEASE_KEY=os.path.join(self.tmp, "no-key"))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_key_the_installer_does_not_know_publishes_nothing(self):
        """Signed, but with a key that is not in the list: users' installers
        would refuse the release, so it must not go out."""
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1", self.pkgfile, STUB_DIRTY="",
                        STUB_UNPUSHED="", BERYLLIUM_RELEASE_KEY=key("another"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("install.sh does not accept the signed release", r.stderr)
        self.assertNotIn("gh release create", r.stdout)

    def test_a_tag_the_manifest_cannot_carry(self):
        for tag in ("0.20.3.1", "v0.20.3.1;reboot", "latest"):
            r = self.run_sh(PUBLISH, "--dry-run", tag, self.pkgfile, STUB_DIRTY="",
                            STUB_UNPUSHED="")
            self.assertNotEqual(r.returncode, 0, tag)
            self.assertIn("the tag", r.stderr)
            self.assertNotIn("gh release create", r.stdout)

    def test_refuses_a_package_built_from_other_patches(self):
        """The release must not name a commit the package was not built from."""
        other = dict(self.digests, **{"security/one.patch": "f" * 64})
        write_package(self.pkgfile, manifest_for(self.root, other))
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1-1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("security/one.patch differs", r.stderr)
        self.assertIn("was not built from this checkout (commit 1234567890abcdef1234567890abcdef12345678)", r.stderr)
        self.assertNotIn("gh release create", r.stdout)

    def test_refuses_a_package_built_with_a_compiler_cache(self):
        write_package(self.pkgfile, manifest_for(self.root, self.digests,
                                                 compiler_cache="ccache"))
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1-1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("was built with a compiler cache: it is a test build", r.stderr)
        self.assertIn("without --ccache", r.stderr)
        self.assertNotIn("was not built from this checkout", r.stderr)
        self.assertNotIn("gh release create", r.stdout)

    def test_refuses_a_package_without_a_manifest(self):
        write_package(self.pkgfile, None)
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1-1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("carries no BUILD-MANIFEST.json", r.stderr)

    def test_refuses_a_manifest_for_another_version(self):
        """pkg says 0.20.3.1 (the stub); a manifest saying otherwise is a
        package assembled from mismatched parts."""
        write_package(self.pkgfile, manifest_for(self.root, self.digests,
                                                 beryllium_version="0.20.3.2"))
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1-1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("beryllium_version", r.stderr)

    def test_manifest_without_the_leading_slash(self):
        """GNU tar lists absolute members without their slash; both work."""
        write_package(self.pkgfile, manifest_for(self.root, self.digests),
                      member="usr/local/share/beryllium/BUILD-MANIFEST.json")
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1-1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_refuses_unpushed_or_dirty(self):
        r = self.run_sh(PUBLISH, "--dry-run", "v1", self.pkgfile, STUB_DIRTY="", STUB_UNPUSHED="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("push it first", r.stderr)
        r = self.run_sh(PUBLISH, "--dry-run", "v1", self.pkgfile, STUB_DIRTY="1", STUB_UNPUSHED="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uncommitted changes", r.stderr)


if __name__ == "__main__":
    unittest.main()
