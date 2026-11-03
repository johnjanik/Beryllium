# SPDX-License-Identifier: GPL-3.0-only
"""The browser's own window (toolbar), read through UI DevTools.

Home button: turning on Settings > Appearance > "Show home button" must
give a visible, sized button that nothing covers (owner's bug report,
3 November 2026: the address bar moved over, but no button showed and the
space did not respond). The toolbar layout is saved to ui-toolbar.txt."""

import json
import socket
import time

from berytest import uidevtools as ui
from berytest.base import BrowserTest

SET_PREF = """new Promise((ok, bad) => {
  if (!window.chrome || !chrome.settingsPrivate) { bad(new Error('settingsPrivate unavailable')); return; }
  chrome.settingsPrivate.setPref('browser.show_home_button', %s, '', ok);
})"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


KEY = ("Visible", "IsDrawn", "Enabled", "CanProcessEventsWithinSubtree", "IsPaintLocked",
       "Tooltip")


def summary(props):
    return " ".join(f"{k}={props.get(k)}" for k in KEY if k in props)


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


class Toolbar(BrowserTest):
    NEEDS_DISPLAY = True
    USER_DATA_DIR = True
    PREFS = {"browser": {"show_home_button": False}}
    port = None

    @classmethod
    def extra_args(cls):
        cls.port = free_port()
        return [f"--enable-ui-devtools={cls.port}"]

    def snapshot(self, devtools):
        """[(depth, name, props, node)] for the toolbar subtree."""
        root = devtools.document()
        toolbars = ui.find(root, "ToolbarView")
        self.assertTrue(toolbars, "no ToolbarView in the window")
        out = []
        for node, depth, _ in ui.walk(toolbars[0]):
            out.append((depth, ui.node_name(node), devtools.properties(node["nodeId"]), node))
        return out

    def save(self, label, rows):
        with open(self.ctx.artifact(f"ui-toolbar-{label}.txt"), "w") as f:
            for depth, name, props, _ in rows:
                f.write(f"{'  ' * depth}{name} rect={ui.rect(props)} {summary(props)}\n")
        with open(self.ctx.artifact(f"ui-toolbar-{label}.json"), "w") as f:
            json.dump([{"depth": d, "class": n, "properties": p} for d, n, p, _ in rows],
                      f, indent=1)

    def test_home_button_shows_when_enabled(self):
        """Enabling "Show home button" gives a visible, uncovered button."""
        devtools = ui.UIDevTools(self.port)
        try:
            self.save("before", self.snapshot(devtools))
            page = self.browser.new_page(self.url("settings/appearance"))
            page.eval(SET_PREF % "true")
            time.sleep(2)
            rows = self.snapshot(devtools)
            self.save("after", rows)
        finally:
            devtools.close()
        index = next((i for i, (_, n, _, _) in enumerate(rows) if n == "HomeButton"), None)
        self.assertIsNotNone(index, "no HomeButton view in the toolbar")
        depth, _, props, _ = rows[index]
        icon = None
        for d, n, p, _ in rows[index + 1:]:
            if d <= depth:
                break
            if d == depth + 1 and n == "ImageView":
                icon = p
        r = ui.rect(props)
        self.note(f"HomeButton rect={r} {summary(props)}\n"
                  "Full toolbar layout: ui-toolbar-after.txt (before: ui-toolbar-before.txt)")
        self.assertTrue(ui.visible(props), "HomeButton is not visible")
        self.assertTrue(r and r[2] > 0 and r[3] > 0, f"HomeButton has no size: {r}")
        for key in ("IsDrawn", "Enabled", "CanProcessEventsWithinSubtree"):
            if key in props:
                self.assertEqual(props[key], "true", f"HomeButton {key}={props[key]}")
        if "IsPaintLocked" in props:
            self.assertEqual(props["IsPaintLocked"], "false", "HomeButton painting is locked")
        self.assertIsNotNone(icon, "HomeButton has no icon view")
        ir = ui.rect(icon)
        self.note(f"HomeButton icon rect={ir} {summary(icon)}")
        self.assertTrue(ir and ir[2] > 0 and ir[3] > 0, f"HomeButton icon has no size: {ir}")
        self.assertEqual(icon.get("IsDrawn", "true"), "true", "HomeButton icon is not drawn")
        # Visible siblings drawn over the button's area.
        covering = [f"{n} rect={ui.rect(p)}" for d, n, p, _ in rows
                    if d == depth and n != "HomeButton" and ui.visible(p)
                    and ui.rect(p) and ui.rect(p)[2] > 0 and overlaps(r, ui.rect(p))]
        self.assertEqual(covering, [], "views over the home button: " + ", ".join(covering))
