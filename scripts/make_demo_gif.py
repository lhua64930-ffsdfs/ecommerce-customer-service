"""把按顺序编号的演示截图合成为 GIF。

用法:
    python scripts/make_demo_gif.py <frames_dir> <output.gif>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description="截图合成演示 GIF")
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--duration", type=int, default=1200, help="每帧毫秒数")
    parser.add_argument("--hold", type=int, default=2200, help="最后一帧停留毫秒数")
    args = parser.parse_args()

    frame_paths = sorted(args.frames_dir.glob("*.png"))
    if not frame_paths:
        raise SystemExit(f"没有找到截图帧: {args.frames_dir}")

    frames: list[Image.Image] = []
    for path in frame_paths:
        with Image.open(path) as image:
            frame = image.convert("RGB")
            if frame.width > args.width:
                height = round(frame.height * args.width / frame.width)
                frame = frame.resize((args.width, height), Image.LANCZOS)
            frames.append(frame)

    durations = [args.duration] * (len(frames) - 1) + [args.hold]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        args.output,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    size_mb = args.output.stat().st_size / 1024 / 1024
    print(f"GIF 已生成:{args.output}({len(frames)} 帧,{size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
