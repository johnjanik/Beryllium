# SPDX-License-Identifier: GPL-3.0-only
"""Run-wide state: options, the results directory, scratch space, and the
fixture server with its test pages and media (started on first use)."""

import os
import platform
import shutil
import tempfile

from . import media
from .servers import FixtureServer

PAGES = {
    "blank.html": "<!doctype html><title>blank</title><body></body>",
    "busy.html": """<!doctype html><title>busy</title>
<style>.b{width:40px;height:40px;margin:2px;display:inline-block;background:#c00;
animation:s 1s linear infinite}@keyframes s{to{transform:rotate(360deg)}}</style>
<body><script>
for (let i = 0; i < 400; i++) document.body.appendChild(document.createElement('div')).className = 'b';
const c = document.body.appendChild(document.createElement('canvas')); c.width = c.height = 256;
const g = c.getContext('2d');
(function draw(t) { for (let i = 0; i < 200; i++) { g.fillStyle = `hsl(${(t / 10 + i) % 360},80%,50%)`;
  g.fillRect(Math.random() * 256, Math.random() * 256, 8, 8); } requestAnimationFrame(draw); })(0);
</script></body>""",
}


class Context:
    def __init__(self, options):
        self.options = options
        self.results = options.results
        os.makedirs(self.results, exist_ok=True)
        self._scratch = tempfile.mkdtemp(prefix="berytest.")
        self._fixtures = None
        self._media = None
        self.notes = []  # (test, text) shown in the report

    def scratch(self, name):
        path = tempfile.mkdtemp(prefix=name + ".", dir=self._scratch)
        return path

    def artifact(self, name):
        return os.path.join(self.results, name)

    def note(self, test, text):
        self.notes.append((test, text))

    def is_freebsd(self):
        return platform.system() == "FreeBSD"

    def fixtures(self):
        if self._fixtures is None:
            directory = os.path.join(self._scratch, "fixtures")
            os.makedirs(directory, exist_ok=True)
            for name, html in PAGES.items():
                with open(os.path.join(directory, name), "w") as f:
                    f.write(html)
            self._fixture_dir = directory
            self._fixtures = FixtureServer(directory)
        return self._fixtures

    def media(self):
        """({name: mime}, {name: why missing}) for the generated clips."""
        if self._media is None:
            self.fixtures()
            self._media = media.generate(self._fixture_dir)
        return self._media

    def close(self):
        if self._fixtures:
            self._fixtures.close()
        if not self.options.keep_profiles:
            shutil.rmtree(self._scratch, ignore_errors=True)


CTX = None


def get():
    if CTX is None:
        raise RuntimeError("berytest context not initialised; run through ./run")
    return CTX
