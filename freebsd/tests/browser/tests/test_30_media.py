# SPDX-License-Identifier: GPL-3.0-only
"""Media: codec support, plain playback and Media Source Extensions (the
way YouTube streams: AV1 or VP9 video, Opus audio). A renderer crash here
is the "Error code 11" (SIGSEGV) seen on YouTube."""

import json
import unittest

from berytest.base import BrowserTest
from berytest.cdp import TargetCrashed

CODECS = [
    'video/mp4; codecs="avc1.4d401e"',
    'video/mp4; codecs="av01.0.05M.08"',
    'video/webm; codecs="vp9"',
    'video/webm; codecs="vp09.00.10.08"',
    'video/webm; codecs="av01.0.05M.08"',
    'audio/webm; codecs="opus"',
    'audio/mp4; codecs="mp4a.40.2"',
    'audio/mp4; codecs="opus"',
]
REQUIRED = {'video/webm; codecs="vp9"', 'video/mp4; codecs="av01.0.05M.08"',
            'audio/webm; codecs="opus"'}

SUPPORT = """(async codecs => {
  const out = {};
  for (const c of codecs) {
    let info = null;
    try {
      const [type] = c.split(';');
      const cfg = type.startsWith('video')
        ? {type: 'media-source', video: {contentType: c, width: 1280, height: 720, bitrate: 2e6, framerate: 30}}
        : {type: 'media-source', audio: {contentType: c, channels: 2, bitrate: 128000, samplerate: 48000}};
      const r = await navigator.mediaCapabilities.decodingInfo(cfg);
      info = {supported: r.supported, smooth: r.smooth, powerEfficient: r.powerEfficient};
    } catch (e) { info = String(e); }
    out[c] = {canPlayType: document.createElement('video').canPlayType(c),
              mse: window.MediaSource ? MediaSource.isTypeSupported(c) : false,
              decodingInfo: info};
  }
  return out;
})(%s)"""

PLAY = """(async (src, mse, mime, kind) => {
  const v = document.createElement(kind);
  v.muted = true;
  document.body.appendChild(v);
  const t0 = performance.now();
  if (mse) {
    const ms = new MediaSource();
    v.src = URL.createObjectURL(ms);
    await new Promise(r => ms.addEventListener('sourceopen', r, {once: true}));
    const sb = ms.addSourceBuffer(mime);
    const data = await (await fetch(src)).arrayBuffer();
    await new Promise((ok, bad) => {
      sb.addEventListener('updateend', ok, {once: true});
      sb.addEventListener('error', () => bad(new Error('SourceBuffer error')), {once: true});
      sb.appendBuffer(data);
    });
    ms.endOfStream();
  } else {
    v.src = src;
  }
  try { await v.play(); } catch (e) {
    return {ok: false, stage: 'play', error: String(e), mediaError: v.error && v.error.code};
  }
  const deadline = performance.now() + 15000;
  while (performance.now() < deadline && v.currentTime < 1.5) {
    if (v.error) return {ok: false, stage: 'decode', mediaError: v.error.code, message: v.error.message};
    await new Promise(r => setTimeout(r, 100));
  }
  const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : null;
  return {ok: v.currentTime >= 1.5, currentTime: v.currentTime, readyState: v.readyState,
          frames: q && q.totalVideoFrames, dropped: q && q.droppedVideoFrames,
          width: v.videoWidth || null, height: v.videoHeight || null,
          ms: Math.round(performance.now() - t0)};
})(%s)"""


class Media(BrowserTest):
    def test_codec_support(self):
        """YouTube's codecs are supported: VP9, AV1 (in MP4), Opus."""
        page = self.browser.new_page(self.ctx.fixtures().url("blank.html"))
        support = page.eval(SUPPORT % json.dumps(CODECS))
        with open(self.ctx.artifact("media-codecs.json"), "w") as f:
            json.dump(support, f, indent=2)
        lines = [f"{c}: canPlayType={v['canPlayType'] or '-'} mse={v['mse']} "
                 f"decodingInfo={v['decodingInfo']}" for c, v in support.items()]
        self.note("\n".join(lines))
        missing = sorted(c for c in REQUIRED if not support[c]["mse"])
        self.assertEqual(missing, [], "not supported for streaming")

    def play(self, name, mse=False, kind="video"):
        clips, why = self.ctx.media()
        if name not in clips:
            raise unittest.SkipTest(why.get(name) or why.get("*") or "clip not available")
        page = self.browser.new_page(self.ctx.fixtures().url("blank.html"))
        args = json.dumps([self.ctx.fixtures().url(name), mse, clips[name], kind])[1:-1]
        try:
            result = page.eval(PLAY % args, timeout=60)
        except TargetCrashed as e:
            self.fail(f"renderer crashed playing {name} (error code {e.error_code}; "
                      f"11 is SIGSEGV)\n{self.kernel_crash_log()}\n"
                      f"browser log tail:\n{self.browser.log_tail(30)}")
        finally:
            self.browser.close_page(page)
        self.note(f"{name}: {result}")
        self.assertTrue(result.get("ok"), f"{name} did not play: {result}")
        if kind == "video":
            self.assertTrue(result.get("frames"), f"{name}: no video frames decoded: {result}")

    def test_play_h264_aac(self):
        """H.264 + AAC in MP4 plays."""
        self.play("h264_aac.mp4")

    def test_play_vp9_opus(self):
        """VP9 + Opus in WebM plays."""
        self.play("vp9_opus.webm")

    def test_play_av1_opus(self):
        """AV1 + Opus in WebM plays."""
        self.play("av1_opus.webm")

    def test_mse_av1_mp4(self):
        """AV1 in fragmented MP4 through Media Source (YouTube's AV1 path)."""
        self.play("mse_av1.mp4", mse=True)

    def test_mse_vp9_webm(self):
        """VP9 in WebM through Media Source (YouTube's VP9 path)."""
        self.play("mse_vp9.webm", mse=True)

    def test_mse_opus_webm(self):
        """Opus audio in WebM through Media Source (YouTube's audio path)."""
        self.play("mse_opus.webm", mse=True, kind="audio")
