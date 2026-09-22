"""Render a recorded run at real speed with an elapsed-time overlay.

    uv run python scripts/render_gif.py artifacts/flights docs/flights.gif [width]

Frames come from Chrome's screencast (recorded by --record) with Chrome's own capture timestamps, so playback is 1x.
The clip starts 0.3 s before the timed part of the run and holds the final frame for one second.
"""

import json
import subprocess
import sys
from pathlib import Path

FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 900
    meta = json.loads((src / "frames.json").read_text())
    frames = [f for f in meta["frames"] if f["timestamp"] is not None]
    start = meta.get("clock_started_at") or frames[0]["timestamp"]
    keep = [f for f in frames if f["timestamp"] >= start - 0.3]
    if not keep:
        sys.exit("no frames after the clock start")
    lines = []
    for a, b in zip(keep, keep[1:] + [None]):
        duration = (b["timestamp"] - a["timestamp"]) if b else 1.0
        lines.append(f"file '{(src / 'frames' / a['file']).resolve()}'\nduration {max(duration, 0.01):.3f}")
    lines.append(f"file '{(src / 'frames' / keep[-1]['file']).resolve()}'")
    concat = src / "concat.txt"
    concat.write_text("\n".join(lines) + "\n")
    offset = keep[0]["timestamp"] - start
    overlay = (
        f"drawtext=fontfile={FONT}:text='%{{eif\\:max(0\\,(t+({offset:.3f}))*1000)\\:d}} ms'"
        ":fontsize=30:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=10:x=w-tw-24:y=h-th-24"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    common = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat)]
    gif_filter = (
        f"{overlay},fps=12,scale={width}:-1:flags=lanczos,split[s0][s1];"
        "[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3"
    )
    subprocess.run([*common, "-vf", gif_filter, str(out)], check=True)
    mp4 = out.with_suffix(".mp4")
    subprocess.run(
        [
            *common,
            "-vf",
            f"{overlay},scale={width}:-2:flags=lanczos,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
    )
    total = keep[-1]["timestamp"] - keep[0]["timestamp"] + 1.0
    print(
        f"{out} ({out.stat().st_size // 1024} KB) and {mp4.name} ({mp4.stat().st_size // 1024} KB): "
        f"{len(keep)} frames, {total:.1f} s at 1x, timed part {meta.get('elapsed_ms')} ms"
    )


if __name__ == "__main__":
    main()
