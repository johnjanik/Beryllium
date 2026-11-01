# SPDX-License-Identifier: GPL-3.0-only
"""Tests for freebsd/tools/gnargs-from-flags. Run from the repository root:

    python3 -m unittest discover -s freebsd/tools/tests
"""

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TOOL = os.path.join(HERE, "..", "gnargs-from-flags")

_loader = importlib.machinery.SourceFileLoader("gnargs", TOOL)
_spec = importlib.util.spec_from_loader("gnargs", _loader)
gnargs = importlib.util.module_from_spec(_spec)
_loader.exec_module(gnargs)

PRIVACY = {"google_api_key": '""', "enable_mdns": "false"}
HELIUM = 'google_api_key=""\nenable_mdns=false\nenable_widevine=true\n'


class Fixture:
    def __init__(self, fragment, helium=HELIUM, privacy=PRIVACY):
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        self.helium = os.path.join(d, "flags.gn")
        self.fragment = os.path.join(d, "flags.freebsd.gn")
        self.privacy = os.path.join(d, "keys.json")
        with open(self.helium, "w") as f:
            f.write(helium)
        with open(self.fragment, "w") as f:
            f.write(fragment)
        with open(self.privacy, "w") as f:
            json.dump(privacy, f)

    def collect(self, extra=(), variables=None):
        return gnargs.collect(self.dir.name, list(extra), variables or {},
                              fragment_path=self.fragment,
                              helium_path=self.helium,
                              privacy_path=self.privacy)


class ParseTests(unittest.TestCase):
    def test_hash_inside_string_is_not_a_comment(self):
        pairs = gnargs.parse_gn('extra_cxxflags="-DX=#1 -O2"  # note\n', "t")
        self.assertEqual(pairs, [("extra_cxxflags", '"-DX=#1 -O2"')])

    def test_trailing_garbage_rejected(self):
        with self.assertRaises(gnargs.GnArgsError):
            gnargs.parse_gn("a=true false\n", "t")

    def test_unterminated_string_rejected(self):
        with self.assertRaises(gnargs.GnArgsError):
            gnargs.parse_gn('a="abc\n', "t")


class PolicyTests(unittest.TestCase):
    def fixture(self, *a, **kw):
        fx = Fixture(*a, **kw)
        self.addCleanup(fx.dir.cleanup)
        return fx

    def test_clean_merge(self):
        fx = self.fixture("use_lld=true\n")
        args, origin = fx.collect(["use_sndio=true"])
        self.assertEqual(args["use_lld"], "true")
        self.assertEqual(origin["use_sndio"], "--arg")
        self.assertEqual(origin["google_api_key"], "helium/flags.gn")

    def test_fragment_cannot_set_privacy_key(self):
        fx = self.fixture('google_api_key="AIzaSyBsp9n41JLW8jCokwn7vhoaMejDFRd1mp8"\n')
        with self.assertRaisesRegex(gnargs.GnArgsError, "privacy-tagged"):
            fx.collect()

    def test_option_cannot_set_privacy_key(self):
        fx = self.fixture("use_lld=true\n")
        with self.assertRaisesRegex(gnargs.GnArgsError, "privacy-tagged"):
            fx.collect(["enable_mdns=true"])

    def test_fragment_cannot_override_helium(self):
        fx = self.fixture("enable_widevine=false\n")
        with self.assertRaisesRegex(gnargs.GnArgsError, "only one source"):
            fx.collect()

    def test_helium_privacy_drift_detected(self):
        fx = self.fixture("use_lld=true\n",
                     helium='google_api_key=""\nenable_mdns=true\n')
        with self.assertRaisesRegex(gnargs.GnArgsError, "privacy key enable_mdns"):
            fx.collect()

    def test_missing_privacy_key_detected(self):
        fx = self.fixture("use_lld=true\n", helium='google_api_key=""\n')
        with self.assertRaisesRegex(gnargs.GnArgsError, "privacy key enable_mdns"):
            fx.collect()

    def test_unfilled_placeholder(self):
        fx = self.fixture('rust_sysroot_absolute="@LOCALBASE@"\n')
        with self.assertRaisesRegex(gnargs.GnArgsError, "@LOCALBASE@"):
            fx.collect()

    def test_placeholder_escaped_inside_string(self):
        fx = self.fixture('extra_ldflags="@LDFLAGS@"\n')
        args, _ = fx.collect(variables={"LDFLAGS": '-L/x "y" $z'})
        self.assertEqual(args["extra_ldflags"], '"-L/x \\"y\\" \\$z"')


class RepositoryTests(unittest.TestCase):
    """The real helium/flags.gn and flags.freebsd.gn must pass the policy."""

    @unittest.skipUnless(os.path.exists(os.path.join(REPO, "helium", "flags.gn")),
                         "helium submodule not checked out")
    def test_repository_check(self):
        self.assertEqual(gnargs.main(["check", "--repo", REPO]), 0)

    def test_port_api_key_not_in_fragment(self):
        with open(os.path.join(REPO, "flags.freebsd.gn")) as f:
            text = f.read()
        keys = {k for k, _ in gnargs.parse_gn(text, "flags.freebsd.gn")}
        self.assertNotIn("google_api_key", keys)
        self.assertNotIn("enable_hangout_services_extension", keys)


if __name__ == "__main__":
    unittest.main()
