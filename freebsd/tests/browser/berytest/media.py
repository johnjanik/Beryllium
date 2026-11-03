# SPDX-License-Identifier: GPL-3.0-only
"""Small media files for playback tests, made with ffmpeg at run time
(pkg install ffmpeg). Each clip is 4 seconds of test pattern and tone."""

import os
import shutil
import subprocess

SRC = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=4",
       "-f", "lavfi", "-i", "sine=frequency=440:duration=4"]
AV1_ENCODERS = (("libsvtav1", ["-preset", "12"]),
                ("libaom-av1", ["-cpu-used", "8", "-row-mt", "1"]),
                ("librav1e", ["-speed", "10"]))


def encoders():
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.split()[1] for line in out.splitlines()
            if len(line.split()) > 1 and line.startswith(" ")}


# name -> (mime type for MSE/canPlayType, needed encoders, ffmpeg arguments)
def recipes(av1):
    av1_name, av1_args = av1 if av1 else (None, [])
    return {
        "h264_aac.mp4": ('video/mp4; codecs="avc1.4d401e, mp4a.40.2"', {"libx264", "aac"},
                         SRC + ["-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p",
                                "-c:a", "aac", "-movflags", "+faststart", "-shortest"]),
        "vp9_opus.webm": ('video/webm; codecs="vp9, opus"', {"libvpx-vp9", "libopus"},
                          SRC + ["-c:v", "libvpx-vp9", "-b:v", "300k", "-deadline", "realtime",
                                 "-cpu-used", "8", "-c:a", "libopus", "-shortest"]),
        "av1_opus.webm": ('video/webm; codecs="av01.0.04M.08, opus"', {av1_name, "libopus"},
                          SRC + ["-c:v", av1_name or "none"] + av1_args
                          + ["-pix_fmt", "yuv420p", "-c:a", "libopus", "-shortest"]),
        # As YouTube streams it (itag 396-style AV1 in fragmented MP4, Opus in WebM).
        "mse_av1.mp4": ('video/mp4; codecs="av01.0.04M.08"', {av1_name},
                        SRC[:4] + ["-c:v", av1_name or "none"] + av1_args
                        + ["-pix_fmt", "yuv420p", "-an", "-movflags",
                           "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4"]),
        "mse_vp9.webm": ('video/webm; codecs="vp9"', {"libvpx-vp9"},
                         SRC[:4] + ["-c:v", "libvpx-vp9", "-b:v", "300k", "-deadline", "realtime",
                                    "-cpu-used", "8", "-an", "-f", "webm"]),
        "mse_opus.webm": ('audio/webm; codecs="opus"', {"libopus"},
                          SRC[4:] + ["-c:a", "libopus", "-vn", "-f", "webm"]),
    }


def generate(directory):
    """Create the clips that this ffmpeg can make; returns {name: mime}
    and {name: reason} for the ones it cannot."""
    made, missing = {}, {}
    if not shutil.which("ffmpeg"):
        return made, {"*": "ffmpeg not installed (pkg install ffmpeg)"}
    have = encoders()
    av1 = next(((n, a) for n, a in AV1_ENCODERS if n in have), None)
    for name, (mime, needs, args) in recipes(av1).items():
        lacking = sorted(n or "an AV1 encoder" for n in needs if n not in have)
        if lacking:
            missing[name] = "ffmpeg lacks " + ", ".join(lacking)
            continue
        path = os.path.join(directory, name)
        if not os.path.exists(path):
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args
                               + [path], capture_output=True, text=True, timeout=300)
            if r.returncode != 0 or not os.path.exists(path):
                missing[name] = "ffmpeg failed: " + r.stderr.strip()[-300:]
                continue
        made[name] = mime
    return made, missing
