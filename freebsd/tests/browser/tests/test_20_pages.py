# SPDX-License-Identifier: GPL-3.0-only
"""Internal pages: each loads without crashing or an error page, and shows
no Helium branding."""

import time

from berytest.base import BrowserTest
from berytest.cdp import CDPError, TargetCrashed

PAGES = ["version", "gpu", "settings", "settings/appearance", "settings/privacy",
         "settings/search", "settings/help", "history", "downloads", "extensions",
         "flags", "about", "sandbox", "components", "policy", "credits",
         "media-internals", "net-internals", "crashes", "newtab"]
# Pages that may name Helium: the credits list the projects Beryllium uses.
HELIUM_ALLOWED = {"credits"}

# All visible text, including inside shadow roots (Settings uses them).
DEEP_TEXT = r"""(() => {
  const out = [];
  const walk = n => {
    if (n.nodeType === 3) {
      const p = n.parentNode && n.parentNode.nodeName;
      if (p !== 'SCRIPT' && p !== 'STYLE') out.push(n.textContent);
    }
    if (n.shadowRoot) walk(n.shadowRoot);
    for (const c of n.childNodes) walk(c);
  };
  walk(document.documentElement);
  return out.join(' ').replace(/\s+/g, ' ').trim();
})()"""


class InternalPages(BrowserTest):
    def test_internal_pages(self):
        """Every internal page loads; none shows an error or says Helium."""
        problems = []
        for path in PAGES:
            with self.subTest(page=path):
                page = self.browser.new_page()
                try:
                    page.navigate(self.url(path), timeout=30)
                    time.sleep(1.5)  # Settings fills its sections after load
                    text = page.eval(DEEP_TEXT)
                except TargetCrashed as e:
                    problems.append(f"{path}: renderer crashed (error code {e.error_code})")
                    continue
                except CDPError as e:
                    problems.append(f"{path}: {e}")
                    continue
                finally:
                    self.browser.close_page(page)
                if not text:
                    problems.append(f"{path}: empty page")
                elif "ERR_" in text and "net-internals" not in path:
                    problems.append(f"{path}: error page: {text[:160]}")
                if "Helium" in text and path not in HELIUM_ALLOWED:
                    i = text.index("Helium")
                    problems.append(f"{path}: says Helium: ...{text[max(0, i - 60):i + 60]}...")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))
