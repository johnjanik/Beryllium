# SPDX-License-Identifier: GPL-3.0-only
"""Tests for install.sh and freebsd/tools/publish-release.

They run the real scripts with POSIX sh against stand-ins for the FreeBSD
commands they call (pkg, poudriere, fetch, sysctl, ...), in --dry-run mode,
and check the commands the scripts would run.
"""

import hashlib
import io
import json
import os
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
            "STUB_DEPS": "nss gtk3 noto-basic noto-sans-sc noto-emoji",
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
        self.assertIn("+ doas pkg install -y gtk3 noto-basic noto-sans-sc noto-emoji\n", out)
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
                        STUB_INSTALLED="nss gtk3 noto-basic noto-sans-sc noto-emoji beryllium", STUB_SHM="1")
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


class PublishReleaseTests(Harness):
    def setUp(self):
        super().setUp()
        root = os.path.join(self.tmp, "repo")
        self.digests = fake_checkout(root)
        self.root = root
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
        write_package(self.pkgfile, manifest_for(root, self.digests))

    def test_dry_run_layout_and_notes(self):
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1-1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("check-provenance: built from this checkout: Beryllium 0.20.3.1", out)
        self.assertIn("beryllium-FreeBSD-16-amd64.pkg", out)
        self.assertRegex(out, r"\+ gh release create v0\.20\.3\.1-1 --target 1234567890abcdef .* "
                              r"\S+/SHA256SUMS \S+/beryllium-FreeBSD-16-amd64\.pkg "
                              r"\S+/BUILD-MANIFEST-FreeBSD-16-amd64\.json\n")
        outdir = out.split("release files in ")[1].split(":")[0]
        with open(os.path.join(outdir, "NOTES.md")) as f:
            notes = f.read()
        self.assertIn("Corresponding source: commit 1234567890abcdef", notes)
        self.assertIn("BUILD-MANIFEST-FreeBSD-<version>-amd64.json", notes)
        self.assertIn("no sandbox yet", notes)
        with open(os.path.join(outdir, "SHA256SUMS")) as f:
            self.assertRegex(f.read(), r"^[0-9a-f]{64} beryllium-FreeBSD-16-amd64\.pkg\n$")
        with open(os.path.join(outdir, "BUILD-MANIFEST-FreeBSD-16-amd64.json")) as f:
            self.assertEqual(json.load(f)["helium_commit"], HELIUM_COMMIT)
        shutil.rmtree(outdir)

    def test_refuses_a_package_built_from_other_patches(self):
        """The release must not name a commit the package was not built from."""
        other = dict(self.digests, **{"security/one.patch": "f" * 64})
        write_package(self.pkgfile, manifest_for(self.root, other))
        r = self.run_sh(PUBLISH, "--dry-run", "v0.20.3.1-1", self.pkgfile,
                        STUB_DIRTY="", STUB_UNPUSHED="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("security/one.patch differs", r.stderr)
        self.assertIn("was not built from this checkout (commit 1234567890abcdef)", r.stderr)
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
