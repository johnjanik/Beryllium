# SPDX-License-Identifier: GPL-3.0-only
"""Tests for install.sh and freebsd/tools/publish-release.

They run the real scripts with POSIX sh against stand-ins for the FreeBSD
commands they call (pkg, poudriere, fetch, sysctl, ...), in --dry-run mode,
and check the commands the scripts would run.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
INSTALL = os.path.join(REPO, "install.sh")
PUBLISH = os.path.join(REPO, "freebsd", "tools", "publish-release")

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
            case "$4" in
            %dn) for d in $STUB_DEPS; do echo "$d"; done ;;
            %q) echo "${STUB_PKGABI:-FreeBSD:16:amd64}" ;;
            %n-%v) echo beryllium-0.20.3.1 ;;
            %n) echo beryllium ;;
            %v) echo 0.20.3.1 ;;
            esac ;;
        *) echo "pkg $* must not run" >&2; exit 99 ;;
        esac""",
    "sysctl": """
        case "$2" in
        kern.ipc.shm_allow_removed) echo "${STUB_SHM:-0}" ;;
        hw.physmem) echo 137438953472 ;;
        esac""",
    "fetch": """
        echo "$4" >>"$STUB_LOG"
        f="$STUB_RELEASE/$(basename "$4")"
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
            "STUB_DEPS": "nss gtk3 noto-basic",
            "STUB_POOLS": "zroot",
            "STUB_JAILS": "",
            "STUB_PORTSTREES": "",
            "BERYLLIUM_POUDRIERE_CONF": os.path.join(self.tmp, "poudriere.conf"),
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def publish(self, majors=(16,), corrupt=False):
        sums = []
        for m in majors:
            name = f"beryllium-FreeBSD-{m}-amd64.pkg"
            data = f"package for {m}".encode()
            with open(os.path.join(self.release, name), "wb") as f:
                f.write(data)
            digest = hashlib.sha256(b"tampered" if corrupt else data).hexdigest()
            sums.append(f"{digest} {name}")
        with open(os.path.join(self.release, "SHA256SUMS"), "w") as f:
            f.write("\n".join(sums) + "\n")

    def run_sh(self, script, *args, **env):
        e = dict(self.env, **env)
        return subprocess.run(["sh", script, *args], env=e, capture_output=True,
                              text=True, timeout=60)

    def fetched(self):
        with open(self.log) as f:
            return f.read().split()


class InstallPackageTests(Harness):
    def test_installs_missing_dependencies_then_package(self):
        self.publish()
        r = self.run_sh(INSTALL, "--dry-run", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("SHA-256 verified", out)
        self.assertIn("+ doas pkg install -y gtk3 noto-basic\n", out)
        self.assertRegex(out, r"\+ doas pkg add \S+/beryllium-FreeBSD-16-amd64\.pkg\n")
        self.assertIn("+ doas sysctl kern.ipc.shm_allow_removed=1\n", out)
        self.assertIn("+ doas sysrc -f /etc/sysctl.conf kern.ipc.shm_allow_removed=1\n", out)
        self.assertIn("no sandbox yet", out)
        self.assertEqual(self.fetched(), [
            "https://github.com/johnjanik/Beryllium/releases/latest/download/SHA256SUMS",
            "https://github.com/johnjanik/Beryllium/releases/latest/download/beryllium-FreeBSD-16-amd64.pkg",
        ])

    def test_reinstall_forces_and_shm_already_set(self):
        self.publish()
        r = self.run_sh(INSTALL, "--dry-run", "--yes",
                        STUB_INSTALLED="nss gtk3 noto-basic beryllium", STUB_SHM="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("All dependencies are installed.", r.stdout)
        self.assertRegex(r.stdout, r"\+ doas pkg add -f \S+\.pkg\n")
        self.assertNotIn("sysctl kern.ipc", r.stdout)

    def test_checksum_mismatch_installs_nothing(self):
        self.publish(corrupt=True)
        r = self.run_sh(INSTALL, "--dry-run", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checksum mismatch", r.stderr)
        self.assertNotIn("pkg add", r.stdout)
        self.assertNotIn("pkg install", r.stdout)

    def test_no_package_for_this_version(self):
        self.publish(majors=(15,))
        r = self.run_sh(INSTALL, "--dry-run", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("none for FreeBSD 16", r.stderr)
        self.assertIn("beryllium-FreeBSD-15-amd64.pkg", r.stdout)

    def test_package_abi_must_match_machine(self):
        self.publish()
        r = self.run_sh(INSTALL, "--dry-run", "--yes", STUB_PKGABI="FreeBSD:15:amd64")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is for FreeBSD:15:amd64", r.stderr)

    def test_no_release_suggests_build(self):
        r = self.run_sh(INSTALL, "--dry-run", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no published Beryllium release", r.stderr)
        self.assertIn("--build", r.stderr)

    def test_named_release(self):
        self.publish()
        r = self.run_sh(INSTALL, "--dry-run", "--yes", "--release", "v0.20.3.1-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fetched()[0],
                         "https://github.com/johnjanik/Beryllium/releases/download/v0.20.3.1-1/SHA256SUMS")

    def test_refuses_other_systems(self):
        r = self.run_sh(INSTALL, "--dry-run", "--yes", STUB_OS="Linux")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Beryllium is for FreeBSD", r.stderr)

    def test_runs_without_sudo_as_root(self):
        self.publish()
        r = self.run_sh(INSTALL, "--dry-run", "--yes", STUB_UID="0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\n\+ pkg add \S+\.pkg\n")

    def test_help(self):
        r = self.run_sh(INSTALL, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("sh install.sh --build", r.stdout)


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

    def test_uninstall(self):
        r = self.run_sh(INSTALL, "--uninstall", "--dry-run", "--yes",
                        STUB_INSTALLED="beryllium")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("+ doas pkg delete -y beryllium\n", r.stdout)


class PublishReleaseTests(Harness):
    def setUp(self):
        super().setUp()
        root = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(root, "helium"))
        with open(os.path.join(root, "helium", "chromium_version.txt"), "w") as f:
            f.write("156.0.8078.79\n")
        git = os.path.join(self.bin, "git")
        with open(git, "w") as f:
            f.write(textwrap.dedent(f"""\
                #!/bin/sh
                case "$*" in
                *show-toplevel*) echo {root} ;;
                *"rev-parse HEAD"*) echo 1234567890abcdef ;;
                *status*) [ -n "$STUB_DIRTY" ] && echo " M file" ; true ;;
                *"branch -r"*) [ -z "$STUB_UNPUSHED" ] && echo "  origin/main" ; true ;;
                esac
                """))
        os.chmod(git, 0o755)
        self.pkgfile = os.path.join(self.tmp, "beryllium-0.20.3.1.pkg")
        with open(self.pkgfile, "w") as f:
            f.write("pkg")

    def test_dry_run_layout_and_notes(self):
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1-1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("beryllium-FreeBSD-16-amd64.pkg", out)
        self.assertIn("+ gh release create v0.20.3.1-1 --target 1234567890abcdef", out)
        self.assertIn("SHA256SUMS", out)
        outdir = out.split("release files in ")[1].split(":")[0]
        with open(os.path.join(outdir, "NOTES.md")) as f:
            notes = f.read()
        self.assertIn("Corresponding source: commit 1234567890abcdef", notes)
        self.assertIn("no sandbox yet", notes)
        with open(os.path.join(outdir, "SHA256SUMS")) as f:
            self.assertRegex(f.read(), r"^[0-9a-f]{64} beryllium-FreeBSD-16-amd64\.pkg\n$")
        shutil.rmtree(outdir)

    def test_refuses_unpushed_or_dirty(self):
        r = self.run_sh(PUBLISH, "--dry-run", "v1", self.pkgfile, STUB_DIRTY="", STUB_UNPUSHED="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("push it first", r.stderr)
        r = self.run_sh(PUBLISH, "--dry-run", "v1", self.pkgfile, STUB_DIRTY="1", STUB_UNPUSHED="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uncommitted changes", r.stderr)


if __name__ == "__main__":
    unittest.main()
