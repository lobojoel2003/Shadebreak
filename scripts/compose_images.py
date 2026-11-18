"""Compose README images from raw screenshots and the sample heat plan.

python scripts/compose_images.py docs/images dist/shadebreak-sample-heat-plan-en.pdf
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SAND = (250, 246, 239)


def rounded(image: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *image.size), radius=radius, fill=255)
    out = image.convert("RGBA")
    out.putalpha(mask)
    return out


def shadow(size: tuple[int, int], radius: int, blur: int = 28, opacity: int = 70) -> Image.Image:
    pad = blur * 3
    layer = Image.new("RGBA", (size[0] + pad * 2, size[1] + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (pad, pad, pad + size[0], pad + size[1]), radius=radius, fill=(29, 38, 51, opacity)
    )
    return layer.filter(ImageFilter.GaussianBlur(blur))


def paste_card(canvas: Image.Image, image: Image.Image, xy: tuple[int, int], radius: int) -> None:
    blur = 28
    s = shadow(image.size, radius, blur)
    canvas.alpha_composite(s, (xy[0] - blur * 3, xy[1] - blur * 3 + 18))
    canvas.alpha_composite(rounded(image, radius), xy)


def hero(images: Path) -> None:
    desktop = Image.open(images / "dashboard-desktop.png").convert("RGB")
    phone = Image.open(images / "dashboard-mobile.png").convert("RGB")
    desktop = desktop.resize((1600, round(desktop.height * 1600 / desktop.width)), Image.LANCZOS)
    desktop = desktop.crop((0, 0, 1600, 1000))
    phone = phone.resize((420, round(phone.height * 420 / phone.width)), Image.LANCZOS)
    canvas = Image.new("RGBA", (1960, 1180), (*SAND, 255))
    paste_card(canvas, desktop, (80, 80), 26)
    paste_card(canvas, phone, (1460, 220), 48)
    canvas.convert("RGB").save(images / "hero.png", optimize=True)


def plan_pages(images: Path, pdf: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "110", "-png", str(pdf), f"{tmp}/page"], check=True)
        pages = sorted(Path(tmp).glob("page-*.png"))
        chosen = [
            Image.open(pages[0]).convert("RGB"),
            Image.open(pages[min(3, len(pages) - 1)]).convert("RGB"),
        ]
    gap, margin = 60, 70
    width = sum(p.width for p in chosen) + gap + margin * 2
    height = max(p.height for p in chosen) + margin * 2
    canvas = Image.new("RGBA", (width, height), (*SAND, 255))
    x = margin
    for page in chosen:
        paste_card(canvas, page, (x, margin), 6)
        x += page.width + gap
    canvas.convert("RGB").save(images / "heat-plan.png", optimize=True)


def phones(images: Path, names: list[str], out: str) -> None:
    shots = [Image.open(images / name).convert("RGB") for name in names]
    shots = [s.resize((560, round(s.height * 560 / s.width)), Image.LANCZOS) for s in shots]
    gap, margin = 56, 64
    width = len(shots) * 560 + gap * (len(shots) - 1) + margin * 2
    height = max(s.height for s in shots) + margin * 2
    canvas = Image.new("RGBA", (width, height), (*SAND, 255))
    for index, shot in enumerate(shots):
        paste_card(canvas, shot, (margin + index * (560 + gap), margin), 44)
    canvas.convert("RGB").save(images / out, optimize=True)


def main() -> None:
    images = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/images")
    pdf = Path(sys.argv[2] if len(sys.argv) > 2 else "dist/shadebreak-sample-heat-plan-en.pdf")
    hero(images)
    plan_pages(images, pdf)
    phones(
        images, ["dashboard-mobile.png", "dashboard-mobile-crew.png", "dashboard-mobile-es.png"], "phones.png"
    )
    phones(images, ["texts-thread-mobile.png", "crew-mobile.png"], "texts-and-crew.png")
    print("composed images in", images)


if __name__ == "__main__":
    main()
