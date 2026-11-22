"""生成看板图标（.ico），供桌面快捷方式使用。

画一个和看板风格一致的小图标：蓝底圆角 + 白色柱状图 + 上升趋势线，
输出多尺寸 ico（16/32/48/64/128/256），在任务栏和桌面缩略图里都清晰。
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "看板.ico"
SIZE = 512  # 先大尺寸画，再缩，边缘更干净

BLUE_TOP = (37, 99, 235)     # #2563eb
BLUE_BOTTOM = (29, 64, 175)  # 略深
WHITE = (255, 255, 255)


def rounded_mask(size: int, radius_ratio: float = 0.22) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=int(size * radius_ratio), fill=255)
    return mask


def gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(int(BLUE_TOP[i] + (BLUE_BOTTOM[i] - BLUE_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return img


def build() -> Image.Image:
    size = SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    body = gradient(size).convert("RGBA")
    img.paste(body, (0, 0), rounded_mask(size))

    draw = ImageDraw.Draw(img)
    # 先画趋势线（在柱子下面一层，避免压在柱子上显乱）
    pts = [
        (int(size * 0.22), int(size * 0.44)),
        (int(size * 0.41), int(size * 0.32)),
        (int(size * 0.60), int(size * 0.26)),
        (int(size * 0.78), int(size * 0.15)),
    ]
    draw.line(pts, fill=(255, 255, 255, 220), width=int(size * 0.020), joint="curve")
    for px, py in pts:
        r = int(size * 0.024)
        draw.ellipse([px - r, py - r, px + r, py + r], fill=(191, 219, 254))

    # 三根柱子（递增，盖在趋势线上）
    bar_w = int(size * 0.115)
    gap = int(size * 0.055)
    base_y = int(size * 0.76)
    heights = [0.30, 0.46, 0.62]
    start_x = int(size * 0.20)
    for i, h in enumerate(heights):
        x0 = start_x + i * (bar_w + gap)
        y0 = base_y - int(size * h * 0.72)
        draw.rounded_rectangle([x0, y0, x0 + bar_w, base_y],
                               radius=bar_w // 3, fill=WHITE)

    # 底部基线
    draw.rounded_rectangle([int(size * 0.16), base_y + int(size * 0.035),
                            int(size * 0.84), base_y + int(size * 0.055)],
                           radius=int(size * 0.012), fill=(255, 255, 255, 200))

    # 右上角一点高亮，增加辨识度
    dot_r = int(size * 0.055)
    cx, cy = int(size * 0.78), int(size * 0.15)
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=(52, 211, 153))
    return img


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon = build()
    sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    icon.save(OUT, format="ICO", sizes=sizes)
    # 顺手存一张 PNG，方便在文件里预览
    icon.resize((256, 256), Image.LANCZOS).save(OUT.with_suffix(".png"))
    print(f"已生成图标：{OUT}  ({OUT.stat().st_size/1024:.1f} KB)")
    print(f"预览图：{OUT.with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
