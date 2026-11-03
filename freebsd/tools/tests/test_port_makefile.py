# SPDX-License-Identifier: GPL-3.0-only
"""Checks that the port installs what the patched Chromium tree builds."""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PORT = os.path.join(REPO, "freebsd", "ports", "www", "beryllium")
HELIUM = os.path.join(REPO, "helium", "patches")
PRUNED = "ungoogled-chromium/fix-building-with-prunned-binaries.patch"


def helium_series():
    with open(os.path.join(HELIUM, "series"), encoding="utf-8") as f:
        return [l.split("#", 1)[0].strip() for l in f if l.split("#", 1)[0].strip()]


@unittest.skipUnless(os.path.exists(os.path.join(HELIUM, "series")),
                     "helium submodule not checked out")
class ChromedriverTests(unittest.TestCase):
    def test_chromedriver_install_matches_build_output(self):
        """Sixth Poudriere build (3 November 2026) failed in stage on
        chromedriver.unstripped, which this tree never produces."""
        linux_branch_disabled = False
        if PRUNED in helium_series():
            with open(os.path.join(HELIUM, PRUNED), encoding="utf-8") as f:
                text = f.read()
            section = text.split("+++ b/chrome/test/chromedriver/BUILD.gn", 1)
            linux_branch_disabled = (len(section) == 2 and
                                     "-if (is_linux) {\n+if (false) {" in section[1])
        with open(os.path.join(PORT, "Makefile"), encoding="utf-8") as f:
            m = re.search(r"^post-install-DRIVER-on:\n\t\$\{INSTALL_PROGRAM\} "
                          r"\$\{WRKSRC\}/out/\$\{BUILDTYPE\}/(\S+)", f.read(), re.M)
        self.assertIsNotNone(m)
        expected = "chromedriver" if linux_branch_disabled else "chromedriver.unstripped"
        self.assertEqual(m.group(1), expected)


if __name__ == "__main__":
    unittest.main()
