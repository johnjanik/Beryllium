# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the canvas noise battery (freebsd/privacy/noise-hash/battery,
battery.js, sim.js).

The arithmetic in battery.js and the stand-in noise in sim.js are run with
node and held against the Python model. The runner is tested with a
stand-in for the browser: a script that posts canned reports. With
BATTERY_TEST_BROWSER set to a Chromium-family binary, the whole battery
runs its self-test against it."""

import ast
import importlib.machinery
import importlib.util
import json
import os
import plistlib
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
EVIDENCE = os.path.join(REPO, "freebsd", "privacy", "noise-hash")
sys.path.insert(0, EVIDENCE)

import model  # noqa: E402

loader = importlib.machinery.SourceFileLoader("noise_battery", os.path.join(EVIDENCE, "battery"))
spec = importlib.util.spec_from_loader("noise_battery", loader)
battery = importlib.util.module_from_spec(spec)
loader.exec_module(battery)

NODE = shutil.which("node")


def node(script, stdin=""):
    r = subprocess.run([NODE, "-e", script, EVIDENCE], input=stdin, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "needs node")
class Arithmetic(unittest.TestCase):
    def test_the_stand_in_noise_is_the_python_model(self):
        rng = random.Random(7)
        cases = []
        for n in range(48):
            w, h = rng.randint(1, 9), rng.randint(1, 9)
            pixels = []
            for _ in range(w * h):
                if n % 4 == 0:      # anything: any alpha, zeros and the limits
                    pixels.append(tuple(rng.choice([0, 1, 2, 127, 253, 254, 255,
                                                    rng.randint(0, 255)]) for _ in range(4)))
                elif n % 4 == 1:    # nearly flat
                    pixels.append((100 + rng.randint(0, 2), 50 + rng.randint(0, 1), 200, 255))
                elif n % 4 == 2:    # textured
                    pixels.append((rng.randint(2, 253), rng.randint(2, 253),
                                   rng.randint(2, 253), 255))
                else:               # flat and translucent
                    pixels.append((90, 91, 92, 128))
            token, ox, oy = rng.getrandbits(64), rng.randint(0, 50), rng.randint(0, 50)
            finalize = n % 5 == 0
            want = model.noise_pixels(token, pixels, w, h, ox, oy, finalize=finalize)
            cases.append({"token": str(token), "w": w, "h": h, "ox": ox, "oy": oy,
                          "finalize": finalize, "src": [c for p in pixels for c in p],
                          "want": [c for p in want for c in p]})
        out = node("""
            const sim = require(process.argv[1] + '/sim.js');
            const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
            const bad = [];
            cases.forEach((c, n) => {
              const got = sim.heliumNoise(BigInt(c.token), new Uint8ClampedArray(c.src),
                                          c.w, c.h, c.ox, c.oy, c.finalize);
              if (JSON.stringify([...got]) !== JSON.stringify(c.want)) bad.push(n);
            });
            console.log(JSON.stringify(bad));""", json.dumps(cases))
        self.assertEqual(out, [])

    def test_the_four_sets_are_the_python_models(self):
        out = node("""
            const B = require(process.argv[1] + '/battery.js');
            console.log(JSON.stringify({
              plain: [0, 1, 2, 3].map(low => B.flatSet(low, 64, 64, 100).join(';')),
              moved: [0, 1, 2, 3].map(low => B.flatSet(low, 40, 30, 37, 5, 7).length)}));""")
        self.assertEqual(out["plain"], battery.four_sets())
        self.assertEqual([len(s.split(";")) for s in out["plain"]], [1031, 998, 1085, 982])
        want = [sum(model.predicted_change(low, x + 5, y + 7, 37)
                    for y in range(30) for x in range(40)) for low in range(4)]
        self.assertEqual(out["moved"], want)

    def test_five_bits_are_found_for_heliums_hash_and_none_for_a_fixed_one(self):
        out = node("""
            const B = require(process.argv[1] + '/battery.js');
            const sim = require(process.argv[1] + '/sim.js');
            const report = [];
            const flat = new Uint8ClampedArray(40 * 30 * 4);
            for (let i = 0; i < flat.length; i += 4) { flat[i] = flat[i+1] = flat[i+2] = 100; flat[i+3] = 255; }
            for (const [token, fixed] of [[0x9E3779B97F4A7C15n, false], [0x0123456789ABCDEEn, false],
                                          [0xFFFFFFFFFFFFFFFFn, false], [0x9E3779B97F4A7C15n, true]]) {
              const random = B.randomImage(48, 48, 20261111);
              const mixed = B.mixedImage(96, 48, 20261112);
              const a = B.findLow5(random, sim.heliumNoise(token, random, 48, 48, 0, 0, fixed), 48, 48);
              const b = B.findLow5(mixed, sim.heliumNoise(token, mixed, 96, 48, 0, 0, fixed), 96, 48);
              const keys = B.changedPixels(flat, sim.heliumNoise(token, flat, 40, 30, 5, 7, fixed), 40).keys;
              report.push({low5: Number(token & 31n), fixed, random: a.fits, mixed: b.fits,
                           smooth: b.best.smooth, textured: b.best.textured,
                           constraints: a.best.constraints, closestWrong: a.best.wrong,
                           canvas: B.whichSet(keys, 40, 30, 100, 5, 7),
                           rectangle: B.whichSet(keys, 40, 30, 100, 0, 0)});
            }
            console.log(JSON.stringify(report));""")
        for r in out[:3]:
            self.assertEqual(r["random"], [r["low5"]])
            self.assertEqual(r["mixed"], [r["low5"]])
            self.assertEqual(r["canvas"], r["low5"] & 3, "the noise follows canvas coordinates")
            self.assertIsNone(r["rectangle"])
            self.assertGreater(r["smooth"], 1000, "the mixed image has smooth pixels")
            self.assertGreater(r["textured"], 1000, "the mixed image has textured pixels")
            self.assertGreater(r["constraints"], 3000)
        fixed = out[3]
        self.assertEqual(fixed["random"], [])
        self.assertEqual(fixed["mixed"], [])
        self.assertGreater(fixed["closestWrong"], 1000)
        self.assertIsNone(fixed["canvas"])

    def test_a_snapshot_is_the_same_arithmetic_with_red_and_blue_exchanged(self):
        out = node("""
            const B = require(process.argv[1] + '/battery.js');
            const sim = require(process.argv[1] + '/sim.js');
            const token = 0x0123456789ABCDEEn;
            const grey = new Uint8ClampedArray(20 * 20 * 4);
            for (let i = 0; i < grey.length; i += 4) { grey[i] = grey[i+1] = grey[i+2] = 100; grey[i+3] = 255; }
            const image = B.randomImage(48, 48, 20261111);
            const direct = sim.heliumNoise(token, image, 48, 48, 0, 0, false);
            const snapshot = sim.snapshotNoise(token, image, 48, 48, false);
            console.log(JSON.stringify({
              greyIsTheExchange: B.sameList(sim.snapshotNoise(token, grey, 20, 20, false),
                                            B.exchanged(sim.heliumNoise(token, grey, 20, 20, 0, 0, false))),
              texturedDiffers: !B.sameList(direct, snapshot),
              direct: B.findLow5(image, direct, 48, 48).fits,
              asRead: B.findLow5(image, snapshot, 48, 48).fits,
              exchanged: B.findLow5(B.exchanged(image), B.exchanged(snapshot), 48, 48).fits,
              twice: B.sameList(B.exchanged(B.exchanged(image)), image)}));""")
        self.assertTrue(out["greyIsTheExchange"])
        self.assertTrue(out["texturedDiffers"])
        self.assertEqual(out["direct"], [14])
        self.assertEqual(out["asRead"], [], "read as it stands, no five bits explain a snapshot")
        self.assertEqual(out["exchanged"], [14])
        self.assertTrue(out["twice"])

    def test_an_exact_readback_fits_nothing_in_a_smooth_image(self):
        out = node("""
            const B = require(process.argv[1] + '/battery.js');
            const mixed = B.mixedImage(96, 48, 20261112);
            const found = B.findLow5(mixed, mixed, 96, 48);
            console.log(JSON.stringify({fits: found.fits, changed: found.best.changed}));""")
        self.assertEqual(out, {"fits": [], "changed": 0})


def page_report(which, origin="http://127.0.0.1:1", low5=None, simulated=None):
    """What battery.html would post for a site: which is 0 to 3 (Helium's
    hash), "other" (a hash that uses the whole token) or "none"."""
    weak = which in (0, 1, 2, 3)
    if weak:
        keys = battery.four_sets()[which]
        low5 = which | 4 if low5 is None else low5
    elif which == "other":
        keys = "0,0;1,0;5,3"
    else:
        keys = ""
    count = len(keys.split(";")) if keys else 0
    step = ["1 0 0 0"] if which in (1, 3, "other") else ["-1 0 0 0"] if weak else []
    image = {"exact": which == "none", "changed": 0 if which == "none" else 2000, "smooth": 0,
             "textured": 2304, "constraints": 0 if which == "none" else 4500,
             "fits": [low5] if weak else ([] if which == "other" else list(range(32))),
             "closest": 0, "closestWrong": 0 if which != "other" else 2200, "tooFar": 0,
             "alphaChanged": 0, "dataurlEqual": not weak,
             # Helium noises a snapshot with red and blue exchanged
             "dataurlExchangedFits": [low5] if weak else None}
    green = bool(step) and step[0].split()[1] != "0"
    copy = {"available": True, "changed": 0, "sameAsGetImageData": which == "none"}
    return {"battery": 1, "origin": origin, "ua": "Mozilla/5.0 Chrome/156", "brands": [],
            "cores": 8, "simulated": simulated, "errors": {}, "tests": {
                "flat": {"count": count, "steps": step, "set": which if weak else None,
                         "stable": True, "keys": keys},
                "fills": [{"same": True if weak else None, "steps": step}] * 5,
                "direction": {"applies": weak, "ok": True},
                "offset": {"applies": weak, "follows": "canvas"},
                "dataurl": {"equal": green or not weak, "exchanged": True, "count": count},
                "blob": {"equal": green or not weak, "exchanged": True},
                "offscreen": {"available": True, "sameAsCanvas": True,
                              "blobEqual": green or not weak, "blobExchanged": True},
                "copies": {"webglTexture": copy, "videoFrame": dict(copy, format="RGBA")},
                "webgl": {"available": True, "readPixels": 0, "dataurl": count,
                          "dataurlSet": which if weak else None},
                "textured": image, "mixed": dict(image, smooth=2390)}}


def result_file(label, sets, control=True):
    profiles = []
    if control:
        profiles.append({"kind": "control", "problem": "",
                         "samples": [battery.evaluate(page_report("none"))]})
    for profile in sets:
        profiles.append({"kind": "measure", "problem": "", "samples": [
            battery.evaluate(page_report(which, f"http://127.0.0.1:{n}"))
            for n, which in enumerate(profile)]})
    return {"battery": 1, "label": label, "machine": {"system": "Darwin", "release": "25.1",
                                                      "machine": "arm64"},
            "browser": {"version": "Helium 0.20.3.1"}, "profiles": profiles}


class Evaluate(unittest.TestCase):
    def test_classify_is_done_again_here_by_the_python_model(self):
        sets = battery.four_sets()
        self.assertEqual([battery.classify(s) for s in sets], [0, 1, 2, 3])
        self.assertEqual(battery.classify(""), "none")
        self.assertEqual(battery.classify(sets[2][:-5]), "other")
        self.assertEqual(len({battery.digest(s) for s in sets}), 4)

    def test_a_site_with_heliums_hash(self):
        e = battery.evaluate(page_report(3))
        self.assertEqual((e["set"], e["count"]), (3, 982))
        self.assertTrue(e["page_agrees"])
        self.assertTrue(e["fills_exact"])
        self.assertTrue(e["direction_ok"])
        self.assertEqual(e["offset_follows"], "canvas")
        self.assertEqual(e["low5"], 7)
        self.assertTrue(e["low5_agrees_flat"])
        self.assertTrue(e["mixed_agrees_textured"])
        self.assertFalse(e["exact_everywhere"])
        # a step on red or blue: the snapshot differs, and is the exchange
        self.assertFalse(e["dataurl_equal"])
        self.assertTrue(e["dataurl_exchanged"])
        self.assertTrue(e["blob_exchanged"])
        self.assertTrue(e["offscreen_blob_exchanged"])
        self.assertFalse(e["textured_dataurl_equal"])
        self.assertTrue(e["textured_dataurl_exchanged"])
        self.assertTrue(e["webgl_texture_exact"])
        self.assertTrue(e["video_frame_exact"])
        self.assertFalse(e["webgl_texture_as_getimagedata"])

    def test_a_snapshot_that_five_other_bits_explain_is_not_the_exchange(self):
        report = page_report(3)
        report["tests"]["textured"]["dataurlExchangedFits"] = [1]
        self.assertFalse(battery.evaluate(report)["textured_dataurl_exchanged"])

    def test_a_report_of_the_first_battery_still_reads(self):
        """Result files made before the snapshot and copy tests were added."""
        report = page_report(2)
        del report["tests"]["copies"]
        for name in ("dataurl", "blob"):
            del report["tests"][name]["exchanged"]
        del report["tests"]["offscreen"]["blobExchanged"]
        del report["tests"]["textured"]["dataurlExchangedFits"]
        e = battery.evaluate(report)
        self.assertEqual(e["set"], 2)
        self.assertIsNone(e["dataurl_exchanged"])
        self.assertIsNone(e["textured_dataurl_exchanged"])
        self.assertIsNone(e["webgl_texture_exact"])
        data = {"profiles": [{"kind": "measure", "samples": [e]}], "machine": {}}
        rows = dict(battery.summarise(data)[0])
        self.assertEqual(rows["  toDataURL: or those pixels with red and blue exchanged"],
                         "does not apply")

    def test_five_bits_that_contradict_the_flat_fill_are_seen(self):
        e = battery.evaluate(page_report(3, low5=6))
        self.assertFalse(e["low5_agrees_flat"])

    def test_the_page_is_not_trusted_about_the_set(self):
        report = page_report(1)
        report["tests"]["flat"]["set"] = 2
        self.assertFalse(battery.evaluate(report)["page_agrees"])

    def test_a_site_with_a_hash_that_uses_the_whole_token(self):
        e = battery.evaluate(page_report("other"))
        self.assertEqual(e["set"], "other")
        self.assertIsNone(e["fills_exact"])
        self.assertFalse(e["textured_unique"])
        self.assertIsNone(e["low5_agrees_flat"])

    def test_a_site_without_noise(self):
        e = battery.evaluate(page_report("none"))
        self.assertEqual(e["set"], "none")
        self.assertTrue(e["exact_everywhere"])
        self.assertIsNone(e["textured_unique"])

    def test_a_report_with_tests_missing_does_not_break_it(self):
        e = battery.evaluate({"origin": "x", "tests": {}, "errors": {"webgl": "no context"}})
        self.assertEqual(e["set"], "none")
        self.assertEqual(e["errors"], ["webgl"])


class Summary(unittest.TestCase):
    def verdict(self, sets):
        return battery.summarise(result_file("x", sets))[1]

    def test_verdicts(self):
        self.assertEqual(self.verdict([[0, 1], [3, 3]]),
                         "two bits of the token choose the pixels, in every readback")
        self.assertEqual(self.verdict([["other", "other"]]),
                         "the pixels are not chosen by two bits of the token")
        self.assertEqual(self.verdict([["none", "none"]]), "no canvas noise")
        self.assertTrue(self.verdict([[0, "other"]]).startswith("mixed"))
        self.assertEqual(self.verdict([]), "nothing measured")

    def test_rows(self):
        rows = dict(battery.summarise(result_file("x", [[0, 1, 1], [3, 3, 2]]))[0])
        self.assertEqual(rows["Readbacks"], "6 (2 new profiles)")
        self.assertEqual(rows["Control with the noise switched off: every readback exact"],
                         "1 of 1")
        self.assertEqual(rows["Changed pixels are exactly one of the four sets"], "6 of 6")
        self.assertIn("2 readbacks, 998 pixels", rows["  set 1"])
        self.assertEqual(rows["Counts of changed pixels seen"], "982, 998, 1031, 1085")
        self.assertEqual(rows["A rectangle read at an offset follows"], "canvas coordinates: 6")
        self.assertEqual(rows["Textured image: one value of five low bits explains every step"],
                         "6 of 6")
        self.assertTrue(rows["Pairs of sites in one profile with the same changed pixels"]
                        .startswith("2 of 6"))
        # the canned reports all step on red: no snapshot equals
        # getImageData, and every one is the exchange
        self.assertEqual(rows["toDataURL gives the same pixels as getImageData"], "0 of 6")
        self.assertEqual(rows["  toDataURL: or those pixels with red and blue exchanged"],
                         "6 of 6")
        self.assertEqual(rows["  or the same five bits explain it with red and blue exchanged"],
                         "6 of 6")
        self.assertEqual(
            rows["A canvas copied into a WebGL texture reads back exact, without noise"],
            "6 of 6 (control: 1 of 1)")

    def test_results_made_with_the_stand_in_noise_say_so(self):
        data = result_file("x", [])
        data["profiles"].append({"kind": "measure", "samples": [
            battery.evaluate(page_report(1, simulated="weak"))]})
        self.assertTrue(battery.summarise(data)[1].startswith("NOT A MEASUREMENT"))


class Compare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, label, sets):
        path = os.path.join(self.tmp.name, label + ".json")
        with open(path, "w") as f:
            json.dump(result_file(label, sets), f)
        return path

    def test_two_machines_with_the_same_finding(self):
        text = "\n".join(battery.compare([self.write("mac", [[0, 1], [2, 2]]),
                                          self.write("linux", [[1, 3], [0, 1]])]))
        self.assertIn("the same verdict on each: yes", text)
        self.assertIn("set 1: seen on 2 of 2, the same pixels on each, and the model's", text)
        self.assertIn("set 2: seen on 1 of 2", text)
        self.assertIn("    mac    4 of 4", text)
        self.assertIn("    linux  4 of 4", text)
        self.assertNotIn("NOT", text)

    def test_two_machines_that_differ(self):
        text = "\n".join(battery.compare([self.write("mac", [[0, 1]]),
                                          self.write("fixed", [["other", "other"]])]))
        self.assertIn("the same verdict on each: no", text)


class FindBrowser(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def app(self, executable="Helium", plist=True):
        app = os.path.join(self.tmp.name, "Helium.app")
        os.makedirs(os.path.join(app, "Contents", "MacOS"))
        for name in ("Helium", "helper"):
            with open(os.path.join(app, "Contents", "MacOS", name), "w") as f:
                f.write("#!/bin/sh\n")
        if plist:
            with open(os.path.join(app, "Contents", "Info.plist"), "wb") as f:
                plistlib.dump({"CFBundleExecutable": executable}, f)
        return app

    def test_a_mac_app_gives_its_executable(self):
        app = self.app()
        self.assertEqual(battery.find_browser(app),
                         os.path.join(app, "Contents", "MacOS", "Helium"))

    def test_a_mac_app_without_a_readable_plist(self):
        app = self.app(plist=False)
        self.assertEqual(battery.find_browser(app),
                         os.path.join(app, "Contents", "MacOS", "Helium"))

    def test_a_binary_by_path_or_by_name(self):
        self.assertEqual(battery.find_browser(sys.executable), os.path.abspath(sys.executable))
        self.assertEqual(battery.find_browser("sh"), os.path.abspath(shutil.which("sh")))

    def test_nothing_found(self):
        self.assertIsNone(battery.find_browser(os.path.join(self.tmp.name, "nothing")))
        self.assertIsNone(battery.find_browser(None, system="Plan9"))

    def test_the_command_line(self):
        command = battery.browser_command("/b", "/p", "http://127.0.0.1:1/x")
        self.assertEqual(command[0], "/b")
        self.assertEqual(command[-1], "http://127.0.0.1:1/x")
        self.assertIn("--user-data-dir=/p", command)
        self.assertIn("--headless", command)
        self.assertIn("--use-mock-keychain", command)
        self.assertNotIn(battery.NOISE_OFF, command)
        shown = battery.browser_command("/b", "/p", "u", windows=True, noise_off=True,
                                        extra=["--no-sandbox"])
        self.assertNotIn("--headless", shown)
        self.assertIn(battery.NOISE_OFF, shown)
        self.assertEqual(shown[-2:], ["--no-sandbox", "u"])


class Server(unittest.TestCase):
    def setUp(self):
        self.state = battery.State()
        self.state.expected.add("abc")
        self.servers = battery.start_servers(self.state, 2)
        self.addCleanup(lambda: [s.shutdown() or s.server_close() for s in self.servers])
        self.ports = [s.server_address[1] for s in self.servers]

    def post(self, port, path, message):
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         data=json.dumps(message).encode(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            e.close()
            return e.code

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.ports[0]}{path}", timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, ""

    def test_it_serves_the_page_and_nothing_else(self):
        status, body = self.get("/battery.html")
        self.assertEqual(status, 200)
        self.assertIn('<script src="battery.js"></script>', body)
        self.assertEqual(self.get("/battery.js")[0], 200)
        self.assertEqual(self.get("/sim.js")[0], 200)
        self.assertEqual(self.get("/battery")[0], 404)
        self.assertEqual(self.get("/../../README.md")[0], 404)

    def test_results_arrive_on_every_port_for_a_run_it_started(self):
        self.assertEqual(self.post(self.ports[0], "/result",
                                   {"run": "abc", "index": 0, "report": {"origin": "a"}}), 204)
        self.assertEqual(self.post(self.ports[1], "/result",
                                   {"run": "abc", "index": 1, "report": {"origin": "b"}}), 204)
        self.assertEqual(self.post(self.ports[1], "/done", {"run": "abc"}), 204)
        self.assertEqual(self.state.reports["abc"], {0: {"origin": "a"}, 1: {"origin": "b"}})
        self.assertIn("abc", self.state.done)

    def test_a_run_it_did_not_start_is_refused(self):
        self.assertEqual(self.post(self.ports[0], "/result",
                                   {"run": "zzz", "index": 0, "report": {}}), 403)
        self.assertEqual(self.post(self.ports[0], "/result",
                                   {"run": "manual-1", "index": 0, "report": {}}), 403)
        self.assertEqual(self.state.reports, {})

    def test_by_hand_runs_are_taken_only_when_serving(self):
        self.state.accept_manual = True
        self.assertEqual(self.post(self.ports[0], "/result",
                                   {"run": "manual-1", "index": 0, "report": {}}), 204)

    def test_the_address_the_browser_is_given(self):
        self.assertEqual(battery.page_url([5, 6, 7], "abc", "&simulate=weak"),
                         "http://127.0.0.1:5/battery.html#run=abc&ports=5,6,7&index=0&simulate=weak")


FAKE_BROWSER = """\
#!{python}
# Stands in for a browser: finds the address on its command line and posts
# a canned report to every port, as battery.html would.
import json, sys, time, urllib.request
mode = {mode!r}
url = sys.argv[-1]
profile = [a for a in sys.argv if a.startswith("--user-data-dir=")][0].split("=", 1)[1]
open({seen!r}, "w").write(profile + "\\n" + " ".join(sys.argv[1:]))
import os
os.makedirs(profile, exist_ok=True)
if mode == "dies":
    sys.exit(3)
if mode == "hangs":
    time.sleep(600)
params = dict(p.split("=", 1) for p in url.split("#", 1)[1].split("&"))
ports = params["ports"].split(",")
for index, port in enumerate(ports):
    body = json.dumps({{"run": params["run"], "index": index,
                        "report": {{"origin": "http://127.0.0.1:" + port, "tests": {{}}}}}}).encode()
    urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:%s/result" % port, data=body, method="POST"), timeout=10).close()
urllib.request.urlopen(urllib.request.Request(
    "http://127.0.0.1:%s/done" % ports[-1], data=json.dumps({{"run": params["run"]}}).encode(),
    method="POST"), timeout=10).close()
time.sleep(600)
"""


class Session(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.seen = os.path.join(self.tmp.name, "seen")
        self.state = battery.State()
        self.servers = battery.start_servers(self.state, 3)
        self.addCleanup(lambda: [s.shutdown() or s.server_close() for s in self.servers])
        self.ports = [s.server_address[1] for s in self.servers]
        self.options = type("Options", (), {"windows": False, "browser_args": []})()

    def browser(self, mode):
        path = os.path.join(self.tmp.name, "browser-" + mode)
        with open(path, "w") as f:
            f.write(FAKE_BROWSER.format(python=sys.executable, mode=mode, seen=self.seen))
        os.chmod(path, 0o755)
        return path

    def test_reports_come_back_in_site_order_and_the_profile_is_removed(self):
        started = time.time()
        reports, problem = battery.session(self.state, self.ports, self.browser("answers"),
                                           self.options, noise_off=True, extra_url="&x=1")
        self.assertEqual(problem, "")
        self.assertEqual([r["origin"] for r in reports],
                         [f"http://127.0.0.1:{p}" for p in self.ports])
        self.assertLess(time.time() - started, 30, "it waited for the browser to end by itself")
        with open(self.seen) as f:
            profile, command = f.read().split("\n", 1)
        self.assertFalse(os.path.exists(profile), "the throwaway profile was left behind")
        self.assertIn(battery.NOISE_OFF, command)
        self.assertIn("&x=1", command)

    def test_a_browser_that_ends_at_once(self):
        reports, problem = battery.session(self.state, self.ports, self.browser("dies"),
                                           self.options)
        self.assertEqual(reports, [])
        self.assertIn("the browser ended (status 3) after 0 sites", problem)
        self.assertIn("command:", problem)

    def test_a_browser_that_never_answers_is_stopped(self):
        reports, problem = battery.session(self.state, self.ports, self.browser("hangs"),
                                           self.options, timeout=2)
        self.assertEqual(reports, [])
        self.assertIn("no answer after 2 s (0 of 3 sites)", problem)

    def test_a_browser_that_is_not_there(self):
        reports, problem = battery.session(self.state, self.ports,
                                           os.path.join(self.tmp.name, "missing"), self.options)
        self.assertEqual(reports, [])
        self.assertIn("could not start", problem)


class Source(unittest.TestCase):
    def test_the_runner_and_the_model_are_python_3_8(self):
        """macOS ships Python 3.9; the battery must run there as it is."""
        for name in ("battery", "model.py"):
            with open(os.path.join(EVIDENCE, name)) as f:
                ast.parse(f.read(), feature_version=(3, 8))

    def test_help_names_every_command(self):
        r = subprocess.run([sys.executable, os.path.join(EVIDENCE, "battery"), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        for command in ("run", "selftest", "serve", "compare"):
            self.assertIn(f"battery {command}", r.stdout)


@unittest.skipUnless(os.environ.get("BATTERY_TEST_BROWSER"),
                     "set BATTERY_TEST_BROWSER to a Chromium-family binary")
class WithABrowser(unittest.TestCase):
    def test_self_test(self):
        extra = os.environ.get("BATTERY_TEST_BROWSER_ARGS", "").split()
        r = subprocess.run([sys.executable, os.path.join(EVIDENCE, "battery"), "selftest",
                            "--browser", os.environ["BATTERY_TEST_BROWSER"]]
                           + [f"--browser-arg={a}" for a in extra],
                           capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, textwrap.shorten(r.stdout + r.stderr, 3000))
        self.assertIn("Self-test passed", r.stdout)


if __name__ == "__main__":
    unittest.main()
