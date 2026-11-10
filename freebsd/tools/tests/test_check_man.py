# SPDX-License-Identifier: GPL-3.0-only
"""freebsd/tools/check-man: the structure check of the manual pages. The
repository's own pages pass, and each rule catches what it is for."""

import importlib.machinery
import importlib.util
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TOOL = os.path.join(REPO, "freebsd", "tools", "check-man")

loader = importlib.machinery.SourceFileLoader("check_man", TOOL)
spec = importlib.util.spec_from_loader("check_man", loader)
check_man = importlib.util.module_from_spec(spec)
loader.exec_module(check_man)

GOOD = """.Dd November 10, 2026
.Dt EXAMPLE 1
.Os Beryllium @@VERSION@@
.Sh NAME
.Nm example
.Nd an example page
.Sh SYNOPSIS
.Nm
.Op Fl v
.Sh DESCRIPTION
The first sentence.
The second sentence, on a line of its own.
.Bl -tag -width Ds
.It Fl v
Be verbose.
.El
.Sh SEE ALSO
.Xr procstat 1 ,
.Xr capsicum 4 ,
.Xr beryllium-sandbox 7
"""
KNOWN = ["example.1", "beryllium-sandbox.7"]


def messages(text, name="example.1"):
    return [m for _, m in check_man.structure_problems(name, text, KNOWN)]


class Structure(unittest.TestCase):
    def test_a_good_page_passes(self):
        self.assertEqual(messages(GOOD), [])

    def test_the_repository_pages_pass(self):
        pages = check_man.pages()
        self.assertTrue(pages, "no pages in man/")
        known = [os.path.basename(p) for p in pages]
        for path in pages:
            with open(path, encoding="utf-8") as f:
                problems = check_man.structure_problems(os.path.basename(path), f.read(), known)
            self.assertEqual(problems, [], path)

    def test_the_port_installs_every_page(self):
        """man/, the port's BERYLLIUM_MANPAGES, its copy and pkg-plist agree."""
        port = os.path.join(REPO, "freebsd", "ports", "www", "beryllium")
        names = [os.path.basename(p) for p in check_man.pages()]
        with open(os.path.join(port, "Makefile"), encoding="utf-8") as f:
            m = re.search(r"^BERYLLIUM_MANPAGES=\s*(.+)$", f.read(), re.M)
        self.assertEqual(sorted(m.group(1).split()), names)
        with open(os.path.join(port, "pkg-plist"), encoding="utf-8") as f:
            plist = f.read().split("\n")
        for name in names:
            section = name.rsplit(".", 1)[1]
            self.assertIn(f"share/man/man{section}/{name}.gz", plist)
            self.assertTrue(os.path.isfile(os.path.join(port, "files", "beryllium", "man", name)), name)

    def test_every_page_carries_the_version_placeholder(self):
        for path in check_man.pages():
            with open(path, encoding="utf-8") as f:
                self.assertIn(".Os Beryllium @@VERSION@@\n", f.read(), path)

    def test_non_ascii_trailing_blank_and_empty_line(self):
        self.assertIn("not plain ASCII", messages(GOOD.replace("first", "f—rst")))
        self.assertIn("trailing blank", messages(GOOD.replace("Be verbose.", "Be verbose. ")))
        self.assertIn("empty line (use .Pp)", messages(GOOD.replace(".Sh SYNOPSIS", "\n.Sh SYNOPSIS")))

    def test_long_line_but_not_a_quoted_item(self):
        long_text = "word " * 20
        self.assertTrue(any("columns" in m for m in messages(GOOD.replace("Be verbose.", long_text.strip() + "."))))
        item = '.It "' + "message " * 14 + '"'
        self.assertEqual(messages(GOOD.replace(".It Fl v", item)), [])

    def test_two_sentences_on_one_line(self):
        self.assertIn("new sentence, new line",
                      messages(GOOD.replace("The first sentence.", "The first sentence. The next.")))

    def test_prologue_name_section_and_date(self):
        self.assertIn(".Dt must be: EXAMPLE 1", messages(GOOD.replace(".Dt EXAMPLE 1", ".Dt OTHER 1")))
        self.assertIn(".Dt must be: EXAMPLE 7", messages(GOOD, name="example.7"))
        self.assertIn("the date must read like: November 10, 2026",
                      messages(GOOD.replace("November 10, 2026", "2026-11-10")))
        self.assertIn("the date must read like: November 10, 2026",
                      messages(GOOD.replace("November 10, 2026", "November 31, 2026")))
        self.assertIn("the page must begin with .Dd, .Dt and .Os",
                      messages(GOOD.replace(".Os Beryllium @@VERSION@@\n", "")))

    def test_sections(self):
        swapped = GOOD.replace(".Sh SYNOPSIS\n.Nm\n.Op Fl v\n", "").replace(
            ".Sh SEE ALSO", ".Sh SYNOPSIS\n.Nm\n.Sh SEE ALSO")
        self.assertIn("section out of order: SYNOPSIS", messages(swapped))
        self.assertIn("not a standard section: NOTES", messages(GOOD.replace(".Sh SEE ALSO", ".Sh NOTES")))
        self.assertIn("no SEE ALSO section", messages(GOOD.replace(".Sh SEE ALSO", ".Sh NOTES")))
        self.assertIn("NAME must have: .Nm example", messages(GOOD.replace(".Nm example", ".Nm other")))
        self.assertIn("no SYNOPSIS section", messages(GOOD.replace(".Sh SYNOPSIS\n.Nm\n.Op Fl v\n", "")))

    def test_unknown_macro_and_open_block(self):
        self.assertIn("not an mdoc macro: .TH", messages(GOOD.replace(".Sh DESCRIPTION", ".TH X 1\n.Sh DESCRIPTION")))
        self.assertTrue(any("still open" in m for m in messages(GOOD.replace(".El\n", ""))))
        self.assertIn(".El closes nothing", messages(GOOD.replace(".Bl -tag -width Ds\n.It Fl v\n", "")))

    def test_cross_references(self):
        self.assertIn("no such Beryllium page: beryllium-nothing(7)",
                      messages(GOOD.replace("beryllium-sandbox 7", "beryllium-nothing 7")))
        self.assertIn(".Xr procstat needs a section", messages(GOOD.replace(".Xr procstat 1 ,", ".Xr procstat ,")))
        unsorted = GOOD.replace(".Xr procstat 1 ,\n.Xr capsicum 4 ,", ".Xr capsicum 4 ,\n.Xr procstat 1 ,")
        self.assertIn("SEE ALSO is not sorted by section, then name", messages(unsorted))
        self.assertIn("a page does not refer to itself with .Xr (use .Nm)",
                      messages(GOOD.replace("The first sentence.", "See\n.Xr example 1 .")))

    def test_placeholder_only_on_the_os_line(self):
        self.assertIn("a placeholder outside the .Os line",
                      messages(GOOD.replace("The first sentence.", "Version @@VERSION@@ is described.")))
        self.assertEqual(messages(GOOD), [])


if __name__ == "__main__":
    unittest.main()
