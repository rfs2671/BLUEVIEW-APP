"""The Levelog wordmark for pages served by the backend (the assignee's punch
page): the app's own logo, frontend/assets/logo-header.png, made one solid
colour (the app's navy, theme.js light `text.primary`) so it reads on white,
cropped and made small. Run again if the app's logo changes:

    python scripts/make_link_wordmark.py
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "assets" / "logo-header.png"
OUT = ROOT / "backend" / "lib" / "assets" / "levelog-wordmark.png"
NAVY = (0x0A, 0x19, 0x29)
HEIGHT = 60                       # 30 px shown, sharp on a 2x screen


def main() -> None:
    im = Image.open(SRC).convert("RGBA")
    alpha = im.getchannel("A")
    im = Image.merge("RGBA", (*(Image.new("L", im.size, c) for c in NAVY), alpha))
    im = im.crop(alpha.getbbox())
    w = round(im.width * HEIGHT / im.height)
    im.resize((w, HEIGHT), Image.LANCZOS).save(OUT, optimize=True)
    print(OUT, (w, HEIGHT), OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
