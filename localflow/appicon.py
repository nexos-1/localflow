"""App-Icon: einmal gezeichnet, als Tray-Icon (PIL.Image) und .ico nutzbar."""

import os

from PIL import Image, ImageDraw

from .settings import APP_DIR

ICO_PATH = os.path.join(APP_DIR, "localflow.ico")


def make_icon(color: str = "#4f8cff", size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64  # Basis-Design ist 64px
    d.ellipse([4 * s, 4 * s, 60 * s, 60 * s], fill=color)
    # stilisiertes Mikrofon
    d.rounded_rectangle([26 * s, 14 * s, 38 * s, 38 * s], radius=6 * s, fill="white")
    d.arc([20 * s, 26 * s, 44 * s, 46 * s], start=0, end=180, fill="white",
          width=max(1, int(3 * s)))
    d.line([32 * s, 46 * s, 32 * s, 52 * s], fill="white", width=max(1, int(3 * s)))
    return img


def ensure_ico() -> str:
    """Mehrgroessen-.ico fuer Verknuepfungen erzeugen (idempotent)."""
    if not os.path.exists(ICO_PATH):
        os.makedirs(APP_DIR, exist_ok=True)
        base = make_icon(size=256)
        base.save(ICO_PATH, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                   (64, 64), (128, 128), (256, 256)])
    return ICO_PATH
