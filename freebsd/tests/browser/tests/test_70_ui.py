# SPDX-License-Identifier: GPL-3.0-only
"""The browser's own window (toolbar), read through UI DevTools.

Home button: turning on Settings > Appearance > "Show home button" must
give a visible, sized button with an icon that nothing hides (owner's bug
report, 3 November 2026: the address bar moved over, but no button showed,
the space did not respond and no tooltip appeared; the same with
--disable-gpu-compositing). In a fresh profile with Helium's default
("classic") layout the button was fine, so this checks every layout Helium
offers, a narrow window, and with --my-settings a copy of the user's own
settings. That found it: in the vertical tabs and dynamic layouts the Home,
Forward and Collapse tabs buttons were zero pixels tall
(patches/ui/beryllium-toolbar-buttons-zero-height.patch). Results: ui-home-button.txt (one row per layout) and
ui-toolbar-<layout>.txt (the window's views around the toolbar)."""

import json
import os
import socket
import time
import unittest

from berytest import context
from berytest import uidevtools as ui
from berytest.browser import Browser, has_display
from berytest.cdp import CDPError

SET_PREF = """new Promise((ok, bad) => {
  if (!window.chrome || !chrome.settingsPrivate) { bad(new Error('settingsPrivate unavailable')); return; }
  chrome.settingsPrivate.setPref('browser.show_home_button', %s, '', ok);
})"""

# Helium's layout settings (helium/patches/helium/ui/layout/), under
# helium.browser: layout is 0 classic, 1 compact, 2 vertical tabs, 3 dynamic.
LAYOUTS = [
    ("classic", {}, []),
    ("classic, centered address bar", {"centered_location_bar": True}, []),
    ("classic, minimal URL", {"minimal_location_bar": True}, []),
    ("classic, narrow window", {}, ["--window-size=640,700"]),
    ("compact", {"layout": 1}, []),
    ("vertical tabs", {"layout": 2}, []),
    ("vertical tabs on the right", {"layout": 2, "vertical_right_aligned": True}, []),
    ("dynamic", {"layout": 3}, []),
    ("zen mode", {"zen_mode": True}, []),  # top bar hidden until revealed
    ("zen mode, top bar pinned", {"zen_mode": True, "zen_mode_top_chrome_pinned": True}, []),
]

KEY = ("Visible", "IsDrawn", "Enabled", "CanProcessEventsWithinSubtree", "IsPaintLocked",
       "Tooltip")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def summary(props):
    return " ".join(f"{k}={props.get(k)}" for k in KEY if k in props)


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def inside(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return bx <= ax and by <= ay and ax + aw <= bx + bw and ay + ah <= by + bh


def drawn(props):
    return ui.visible(props) and props.get("IsDrawn", "true") == "true"


def slug(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


class Row:
    """One view: its class, properties, depth, rect in BrowserView
    coordinates, and its ancestors (indices into the list)."""

    def __init__(self, name, props, depth, abs_rect, ancestors):
        self.name, self.props, self.depth = name, props, depth
        self.abs, self.ancestors = abs_rect, ancestors


def snapshot(devtools, attempts=8):
    """Every view under BrowserView, in paint order (a view is painted after
    the views listed before it). The window can change while it is read;
    then read it again."""
    last = None
    for _ in range(attempts):
        root = devtools.document()
        tops = ui.find(root, "BrowserView") or ui.find(root, "ToolbarView")
        if not tops:
            raise AssertionError("no BrowserView or ToolbarView in the window")
        try:
            rows, origin = [], {}
            stack = []  # (depth, row index)
            for node, depth, parent in ui.walk(tops[0]):
                props = devtools.properties(node["nodeId"])
                r = ui.rect(props) or (0, 0, 0, 0)
                px, py = origin.get(id(parent), (0, 0)) if parent is not None and \
                    depth > 0 else (0, 0)
                ax, ay = (px + r[0], py + r[1]) if depth > 0 else (0, 0)
                origin[id(node)] = (ax, ay)
                while stack and stack[-1][0] >= depth:
                    stack.pop()
                rows.append(Row(ui.node_name(node), props, depth, (ax, ay, r[2], r[3]),
                                [i for _, i in stack]))
                stack.append((depth, len(rows) - 1))
            return rows
        except RuntimeError as e:
            last = e
            time.sleep(0.5)
    raise last


def flat_buttons(rows):
    """Toolbar buttons that are shown but have no height (the vertical tabs
    and dynamic layouts, 3 November 2026: Home, Forward, Collapse tabs)."""
    bars = [i for i, r in enumerate(rows) if r.name == "ToolbarView"]
    if not bars:
        return []
    return [f"{r.name} \"{r.props.get('Tooltip', '')}\" {r.abs}" for r in rows
            if r.ancestors and r.ancestors[-1] == bars[0] and r.name.endswith("Button")
            and drawn(r.props) and r.abs[2] > 0 and r.abs[3] <= 0]


def examine(rows, top_bar_may_hide=False):
    """Problems with the Home button in one snapshot, and a description."""
    homes = [i for i, r in enumerate(rows) if r.name == "HomeButton"]
    if not homes:
        return ["no HomeButton view in the window"], "no HomeButton view"
    i = homes[0]
    home = rows[i]
    tops = [rows[a] for a in home.ancestors if rows[a].name == "TopContainerView"]
    if top_bar_may_hide and tops and tops[0].abs[3] <= 0:
        # Zen mode hides the top bar until the pointer reaches the top edge.
        return [], f"top bar hidden, as zen mode intends; HomeButton at {home.abs}"
    problems = []
    flat = flat_buttons(rows)
    if flat:
        problems.append("toolbar buttons with no height: " + ", ".join(flat))
    overflow = [r for r in rows if r.name == "OverflowButton" and drawn(r.props)
                and r.abs[2] > 0]
    if not ui.visible(home.props) and overflow:
        # Chromium moves toolbar buttons into the "Hidden toolbar buttons"
        # menu when the window is too narrow; the Home button goes first.
        return [], (f"HomeButton moved to the overflow menu (window too narrow), as "
                    f"Chromium does; OverflowButton at {overflow[0].abs}")
    if not ui.visible(home.props):
        problems.append("HomeButton not visible")
    if home.props.get("IsDrawn", "true") != "true":
        problems.append("HomeButton not drawn (it or an ancestor is hidden)")
    if home.abs[2] <= 0 or home.abs[3] <= 0:
        problems.append(f"HomeButton has no size: {home.abs}")
    for key in ("Enabled", "CanProcessEventsWithinSubtree"):
        if home.props.get(key, "true") != "true":
            problems.append(f"HomeButton {key}={home.props.get(key)}")
    if home.props.get("IsPaintLocked", "false") != "false":
        problems.append("HomeButton painting is locked")
    icons = [r for r in rows[i + 1:] if home.depth < r.depth and i in r.ancestors
             and r.depth == home.depth + 1 and r.name == "ImageView"]
    if not icons:
        problems.append("HomeButton has no icon view")
    elif icons[0].abs[2] <= 0 or icons[0].abs[3] <= 0 or not drawn(icons[0].props):
        problems.append(f"HomeButton icon not drawn or empty: {icons[0].abs} "
                        f"{summary(icons[0].props)}")
    # Ancestors clip their children: the button must lie inside each of them.
    for a in home.ancestors:
        anc = rows[a]
        if anc.depth > 0 and home.abs[2] > 0 and not inside(home.abs, anc.abs):
            problems.append(f"HomeButton {home.abs} lies outside its ancestor "
                            f"{anc.name} {anc.abs}, which clips it")
    # Views painted later that overlap the button: siblings of the button
    # (a problem: they take its place) and siblings of its ancestors (listed
    # only, since many are transparent containers).
    parent_of_home = home.ancestors[-1] if home.ancestors else None
    lineage = set(home.ancestors) | {i}
    siblings, later = [], []
    for r in rows[i + 1:]:
        if i in r.ancestors or not drawn(r.props) or r.abs[2] <= 0 or r.abs[3] <= 0:
            continue
        if not overlaps(home.abs, r.abs) or not r.ancestors:
            continue
        if r.ancestors[-1] == parent_of_home:
            siblings.append(f"{r.name} {r.abs}")
        elif r.ancestors[-1] in lineage:
            later.append(f"{r.name} {r.abs}")
    if siblings:
        problems.append("views in the toolbar drawn over the HomeButton: " + ", ".join(siblings))
    desc = f"HomeButton at {home.abs} {summary(home.props)}"
    if later:
        desc += "\n    painted after it and overlapping (often transparent): " + ", ".join(later)
    return problems, desc


def save(path, rows, focus=None):
    """The views in the toolbar's part of the window (top 200 px)."""
    with open(path, "w") as f:
        for r in rows:
            if r.abs[1] > 200 and r.depth > 2:
                continue
            mark = "  <-- " + focus if focus and r.name == "HomeButton" else ""
            f.write(f"{'  ' * r.depth}{r.name} at={r.abs} {summary(r.props)}{mark}\n")


class Toolbar(unittest.TestCase):
    def check_layout(self, ctx, name, layout_prefs, args, settings_from=None):
        port = free_port()
        prefs = None if settings_from else {
            "browser": {"show_home_button": False},
            "helium": {"browser": dict(layout_prefs)}}
        browser = Browser(ctx, f"ui-{slug(name)}", args=[f"--enable-ui-devtools={port}"] + args,
                          headless=False, user_data_dir=True, prefs=prefs,
                          settings_from=settings_from).start()
        browser.record_version()
        try:
            devtools = ui.UIDevTools(port)
            try:
                page = browser.new_page(browser.url("settings/appearance"))
                page.eval(SET_PREF % "true")
                time.sleep(2)
                rows = snapshot(devtools)
            finally:
                devtools.close()
        finally:
            browser.stop()
        problems, desc = examine(rows, top_bar_may_hide=name == "zen mode")
        save(ctx.artifact(f"ui-toolbar-{slug(name)}.txt"), rows,
             "; ".join(problems) or "fine")
        with open(ctx.artifact(f"ui-toolbar-{slug(name)}.json"), "w") as f:
            json.dump([{"depth": r.depth, "class": r.name, "at": r.abs,
                        "properties": r.props} for r in rows], f, indent=1)
        return problems, desc

    def test_home_button_shows_in_every_layout(self):
        """"Show home button" gives a visible, uncovered button in every layout."""
        ctx = context.get()
        if ctx.options.headless or not has_display():
            self.skipTest("needs a desktop session (not --headless)")
        cases = list(LAYOUTS)
        mine = getattr(ctx.options, "my_settings", None)
        if mine:
            mine = os.path.expanduser(mine)
            if os.path.isfile(os.path.join(mine, "Default", "Preferences")):
                cases.append(("your settings", None, []))
            else:
                ctx.note(self.id(), f"--my-settings: no Default/Preferences in {mine}")
                mine = None
        table, failed = [], []
        for case in cases:
            name, layout_prefs, args = case[0], case[1], case[2]
            try:
                problems, desc = self.check_layout(
                    ctx, name, layout_prefs or {}, args,
                    settings_from=mine if layout_prefs is None else None)
            except (CDPError, ConnectionError, RuntimeError, AssertionError) as e:
                problems, desc = [f"could not check: {str(e)[:200]}"], ""
            table.append(f"{name}: {'; '.join(problems) if problems else 'fine'}"
                         + (f"\n    {desc}" if desc else ""))
            if problems:
                failed.append(name)
        text = "\n".join(table)
        with open(ctx.artifact("ui-home-button.txt"), "w") as f:
            f.write(text + "\n")
        ctx.note(self.id(), text + "\nViews per layout: ui-toolbar-<layout>.txt")
        self.assertEqual(failed, [], "Home button problems in: " + ", ".join(failed))
