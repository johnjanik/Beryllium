# SPDX-License-Identifier: GPL-3.0-only
"""Tests for what the browser suite's YouTube test says when the video does
not play (freebsd/tests/browser/tests/test_80_youtube.py). The first run
with the network on 0.20.3.17 (11 November 2026) failed with the player's
"Something went wrong" and nothing in the report to say why."""

import collections
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE = os.path.abspath(os.path.join(HERE, "..", "..", "tests", "browser"))
sys.path.insert(0, SUITE)

spec = importlib.util.spec_from_file_location(
    "test_80_youtube", os.path.join(SUITE, "tests", "test_80_youtube.py"))
youtube = importlib.util.module_from_spec(spec)
spec.loader.exec_module(youtube)

S = "session-1"


def event(method, session=S, **params):
    return {"method": method, "sessionId": session, "params": params}


class HostOf(unittest.TestCase):
    def test_numbered_hosts_are_grouped(self):
        self.assertEqual(youtube.host_of("https://rr3---sn-a5mekn6k.googlevideo.com/videoplayback?x=1"),
                         "*.googlevideo.com")
        self.assertEqual(youtube.host_of("https://i.ytimg.com/vi/x/hq.jpg"), "*.ytimg.com")

    def test_other_hosts_are_whole(self):
        self.assertEqual(youtube.host_of("https://www.youtube.com/youtubei/v1/player"),
                         "www.youtube.com")
        # not a subdomain of a grouped host
        self.assertEqual(youtube.host_of("https://notgooglevideo.com/x"), "notgooglevideo.com")

    def test_no_url(self):
        self.assertEqual(youtube.host_of(""), "?")
        self.assertEqual(youtube.host_of(None), "?")


class NetworkSummary(unittest.TestCase):
    EVENTS = [
        event("Network.requestWillBeSent", requestId="1",
              request={"url": "https://rr1---sn-x.googlevideo.com/videoplayback?a"}),
        event("Network.requestWillBeSent", requestId="2",
              request={"url": "https://rr2---sn-y.googlevideo.com/videoplayback?b"}),
        event("Network.requestWillBeSent", requestId="3",
              request={"url": "https://googleads.g.doubleclick.net/pagead/id"}),
        event("Network.requestWillBeSent", requestId="4",
              request={"url": "https://www.youtube.com/api/stats/qoe"}),
        event("Network.loadingFailed", requestId="3", errorText="net::ERR_BLOCKED_BY_CLIENT",
              blockedReason="inspector"),
        event("Network.loadingFailed", requestId="4", errorText="net::ERR_ABORTED", canceled=True),
        event("Network.responseReceived", requestId="1",
              response={"url": "https://rr1---sn-x.googlevideo.com/videoplayback?a", "status": 403}),
        event("Network.responseReceived", requestId="2",
              response={"url": "https://rr2---sn-y.googlevideo.com/videoplayback?b", "status": 403}),
        event("Network.responseReceived", requestId="9",
              response={"url": "https://www.youtube.com/watch", "status": 200}),
        # another tab's traffic is not this page's
        event("Network.responseReceived", session="other", requestId="7",
              response={"url": "https://example.org/", "status": 500}),
    ]

    def test_failed_and_refused(self):
        failed, refused = youtube.network_summary(self.EVENTS, S)
        self.assertEqual(failed, collections.Counter(
            {("*.doubleclick.net", "net::ERR_BLOCKED_BY_CLIENT"): 1}))
        self.assertEqual(refused, collections.Counter({("*.googlevideo.com", 403): 2}))

    def test_requests_the_page_gave_up_are_not_failures(self):
        failed, _ = youtube.network_summary(self.EVENTS, S)
        self.assertFalse(any(why == "net::ERR_ABORTED" for _, why in failed))

    def test_nothing(self):
        self.assertEqual(youtube.network_summary([], S), (collections.Counter(),
                                                          collections.Counter()))


class ConsoleErrors(unittest.TestCase):
    def test_kinds_and_limit(self):
        events = [
            event("Runtime.consoleAPICalled", type="log", args=[{"value": "fine"}]),
            event("Runtime.consoleAPICalled", type="error",
                  args=[{"value": "player"}, {"description": "TypeError: x is not a function"}]),
            event("Runtime.exceptionThrown",
                  exceptionDetails={"text": "Uncaught", "exception": {"description": "Error: boom\n  at a"}}),
            event("Log.entryAdded", entry={"level": "error", "text": "Failed to load resource: 403",
                                           "url": "https://rr1---sn-x.googlevideo.com/videoplayback"}),
            event("Log.entryAdded", entry={"level": "warning", "text": "ignored"}),
            event("Runtime.consoleAPICalled", session="other", type="error", args=[{"value": "theirs"}]),
        ]
        errors = youtube.console_errors(events, S)
        self.assertEqual(errors, ["player TypeError: x is not a function", "Error: boom at a",
                                  "Failed to load resource: 403 (*.googlevideo.com)"])
        self.assertEqual(len(youtube.console_errors(events, S, limit=1)), 1)

    def test_repeats_once_and_short(self):
        events = [event("Runtime.consoleAPICalled", type="error", args=[{"value": "x" * 900}])] * 4
        errors = youtube.console_errors(events, S)
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(errors[0]), 200)


class DescribeFailure(unittest.TestCase):
    def test_a_refusal_by_youtube(self):
        # What YouTube answered a new profile driven from a data centre.
        d = {"status": "LOGIN_REQUIRED", "reason": "Sign in to confirm you're not a bot",
             "debug": {"state": "40"}}
        lines = youtube.describe_failure(d, collections.Counter(), collections.Counter(), [])
        self.assertEqual(lines[0], "YouTube's answer for the video: LOGIN_REQUIRED "
                                   "(Sign in to confirm you're not a bot)")
        self.assertIn("player: state=40", lines)
        self.assertIn("no request failed and no response had an error status", lines)
        self.assertTrue(youtube.refused_by_youtube(d))

    def test_a_stream_that_was_refused(self):
        d = {"status": "OK", "reason": None, "debug": {"vec": "2", "debug_error": "net.badstatus"}}
        lines = youtube.describe_failure(
            d, collections.Counter({("*.doubleclick.net", "net::ERR_BLOCKED_BY_CLIENT"): 3}),
            collections.Counter({("*.googlevideo.com", 403): 7}), ["Failed to load resource: 403"])
        self.assertEqual(lines[0], "YouTube's answer for the video: OK")
        self.assertIn("responses with an error status: 7 from *.googlevideo.com (403)", lines)
        self.assertIn("requests that failed: 3 to *.doubleclick.net (net::ERR_BLOCKED_BY_CLIENT)",
                      lines)
        self.assertIn("console errors: Failed to load resource: 403", lines)
        self.assertFalse(youtube.refused_by_youtube(d))

    def test_nothing_read(self):
        lines = youtube.describe_failure(None, collections.Counter(), collections.Counter(), [])
        self.assertEqual(lines[0], "YouTube's answer for the video: none read")
        self.assertFalse(youtube.refused_by_youtube(None))
        self.assertFalse(youtube.refused_by_youtube({"status": "not readable: x"}))
        self.assertFalse(youtube.refused_by_youtube({"status": None}))


# The player's own error from the owner's 0.20.3.17 run of 11 November 2026,
# as the report printed it (the test keeps the first 300 characters).
REJECTED = ('{"errorCode":"ump.spsrejectfailure","errorMessage":"Something went wrong. Refresh '
            'or try again later. $BEGIN_LINKLearn more$END_LINK","FL":"HTML5_SPS_UMP_STATUS_REJECTED",'
            '"nn":"","sI":"rn.16;rt.54;lb.123;stall.0;ht.53;elt.NaN;elb.0;ulb.0;ult.0;pb.1;pt.44;'
            'se.0;shost.rr1---sn-h5bupjvh-ucnr.googlevideo')


class StreamProtection(unittest.TestCase):
    def test_the_rejection_of_11_november(self):
        d = {"status": "OK", "reason": None,
             "debug": {"debug_error": REJECTED, "debug_playbackQuality": "large", "state": "80"}}
        self.assertTrue(youtube.rejected_by_stream_protection(d))
        # YouTube had answered OK for the video: not a refusal of the session up front
        self.assertFalse(youtube.refused_by_youtube(d))

    def test_either_code_is_enough(self):
        for text in ('{"errorCode":"ump.spsrejectfailure"}', '{"FL":"HTML5_SPS_UMP_STATUS_REJECTED"}'):
            self.assertTrue(youtube.rejected_by_stream_protection({"debug": {"debug_error": text}}))

    def test_other_errors_are_not_it(self):
        for d in (None, {}, {"debug": {}}, {"debug": {"debug_error": '{"errorCode":"fmt.decode"}'}},
                  {"debug": {"vec": "3"}}):
            self.assertFalse(youtube.rejected_by_stream_protection(d))


class BestSample(unittest.TestCase):
    def test_furthest_into_the_video(self):
        samples = [{"t": 0, "dropped": 0}, {"t": 12.5, "dropped": 1}, {"t": 44.1, "dropped": 2},
                   {"t": 0, "dropped": 0, "playerError": "Something went wrong"}]
        self.assertEqual(youtube.best_sample(samples)["dropped"], 2)

    def test_nothing_played(self):
        self.assertIsNone(youtube.best_sample([]))
        self.assertIsNone(youtube.best_sample([{"t": 0}, {"t": None}]))


class Probe(unittest.TestCase):
    def test_the_page_script_reads_the_answer_and_the_error_fields(self):
        for needle in ("getPlayerResponse", "playabilityStatus", "getDebugText", "debug_error"):
            self.assertIn(needle, youtube.DIAGNOSE)


if __name__ == "__main__":
    unittest.main()
