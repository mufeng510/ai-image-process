"""Generate minimal-flat app icon for AI Image Process.

Design (1024 master):
- white rounded-square, light slate border
- slate photo frame (rounded rect) with sky fill
- sky-blue sun circle + two slate mountains
- indigo 4-point AI sparkle top-right + tiny sky sparkle

Run: python assets/icons/generate_icons.py
Outputs: icon.png (1024), icon-*.png, icon.ico, icon.icns
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent

# Palette - minimal flat
WHITE = (255, 255, 255, 255)
BORDER = (226, 232, 240, 255)  # slate-200
FRAME_FILL = (248, 250, 252, 255)  # slate-50
INK = (30, 41, 59, 255)  # slate-800
INK2 = (71, 85, 105, 255)  # slate-600
SUN = (14, 165, 233, 255)  # sky-500
ACCENT = (99, 102, 241, 255)  # indigo-500


def star4(draw: ImageDraw.ImageDraw, cx: float, cy: float, r_out: float, r_in: float, fill: tuple) -> None:
    """4-point sparkle: N-E-S-W outer points, concave inner corners."""
    pts = [
        (cx, cy - r_out),  # top
        (cx + r_in, cy - r_in),
        (cx + r_out, cy),  # right
        (cx + r_in, cy + r_in),
        (cx, cy + r_out),  # bottom
        (cx - r_in, cy + r_in),
        (cx - r_out, cy),  # left
        (cx - r_in, cy - r_in),
    ]
    draw.polygon(pts, fill=fill)


def render(master: int = 1024, supersample: int = 4) -> Image.Image:
    s = supersample
    big = master * s
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def sc(v: float) -> float:
        return v * s

    # Background: white rounded square + border
    d.rounded_rectangle(
        [sc(32), sc(32), sc(992), sc(992)],
        radius=sc(220),
        fill=WHITE,
        outline=BORDER,
        width=int(sc(10)),
    )

    # Photo frame
    d.rounded_rectangle(
        [sc(192), sc(300), sc(832), sc(740)],
        radius=sc(72),
        fill=FRAME_FILL,
        outline=INK,
        width=int(sc(36)),
    )

    # Sun
    sun_cx, sun_cy, sun_r = sc(380), sc(470), sc(64)
    d.ellipse([sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r], fill=SUN)

    # Mountains (stay inside frame interior, leave light gap above bottom edge)
    d.polygon(
        [(sc(244), sc(682)), (sc(430), sc(488)), (sc(616), sc(682))],
        fill=INK,
    )
    d.polygon(
        [(sc(518), sc(682)), (sc(662), sc(556)), (sc(788), sc(682))],
        fill=INK2,
    )

    # AI sparkles (top-right, resting on white just above frame edge)
    star4(d, sc(744), sc(216), sc(78), sc(17), ACCENT)
    star4(d, sc(622), sc(176), sc(24), sc(7), SUN)

    return img.resize((master, master), Image.LANCZOS)


def main() -> None:
    master = render()
    master.save(OUT / "icon.png", "PNG")

    for size in (256, 128, 64, 48, 32, 16):
        small = master.resize((size, size), Image.LANCZOS)
        small.save(OUT / f"icon-{size}.png", "PNG")

    # Windows ICO (multi-size)
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    master.save(OUT / "icon.ico", "ICO", sizes=ico_sizes)

    # macOS ICNS (Pillow writes icns from PNG sizes)
    try:
        icns_sizes = [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)]
        master.save(OUT / "icon.icns", "ICNS", sizes=icns_sizes)
    except Exception as exc:  # noqa: BLE001
        print(f"[icons] icns skipped: {exc}")

    print(f"[icons] wrote {OUT / 'icon.png'} + icon-*.png + icon.ico (+icon.icns)")


if __name__ == "__main__":
    main()
