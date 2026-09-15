"""App-Icon: einmal gezeichnet, als Tray-Icon (PIL.Image) und .ico nutzbar.

Aufbau nach Apples App-Icon-Regeln (app-icons.md): nur gefuellte,
ueberlappende Formen, keine Linien - Mikrofon-Kapsel (Stadion), darunter
ein U-foermiger Kragen (Ring-Ausschnitt), Stiel und Fuss. Drei Varianten
aus demselben Zeichencode fuer das Tray:

- "ready":     orange Scheibe, weisses Mikrofon (Standard)
- "recording": invertiert (weisse Scheibe, oranges Mikrofon) - im Tray auf
               einen Blick als "Aufnahme laeuft" erkennbar
- "paused":    graue Scheibe, weisses Mikrofon
"""

import os

from PIL import Image, ImageDraw

from .settings import APP_DIR

ICO_PATH = os.path.join(APP_DIR, "localflow.ico")

ORANGE = "#ff9500"
GREY = "#9a9a9a"
WHITE = "#ffffff"

VARIANTS = {
    "ready": (ORANGE, WHITE),
    "recording": (WHITE, ORANGE),
    "paused": (GREY, WHITE),
}


def make_icon(color: str | None = None, size: int = 64, variant: str = "ready") -> Image.Image:
    """`color` bleibt aus Kompatibilitaet: ueberschreibt die Scheibenfarbe
    der Variante (aeltere Aufrufer geben "#9a9a9a" fuer Pause)."""
    disc, ink = VARIANTS.get(variant, VARIANTS["ready"])
    if color:
        disc = color
        if color.lower() == WHITE:
            ink = ORANGE
    # Supersampling: 4x zeichnen, dann mit LANCZOS runterrechnen - PIL
    # zeichnet ohne Kantenglaettung, im Tray (16 px) waere das sonst grob.
    ss = 4
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = S / 64  # Basis-Design ist 64 px

    def box(x0, y0, x1, y1):
        return [x0 * u, y0 * u, x1 * u, y1 * u]

    # Scheibe
    d.ellipse(box(3, 3, 61, 61), fill=disc)
    # Kragen: U-foermiger Ring-Ausschnitt (Ellipse minus innere Ellipse,
    # obere Haelfte wieder mit der Scheibenfarbe abgedeckt)
    d.ellipse(box(18, 21, 46, 47), fill=ink)
    d.ellipse(box(22.5, 21, 41.5, 42.5), fill=disc)
    d.rectangle(box(16, 19, 48, 33.5), fill=disc)
    # Kapsel (Stadion), leicht nach oben versetzt fuer Tiefe
    d.rounded_rectangle(box(26, 12, 38, 37), radius=6 * u, fill=ink)
    # Stiel + Fuss
    d.rounded_rectangle(box(30.2, 44, 33.8, 52), radius=1.8 * u, fill=ink)
    d.rounded_rectangle(box(24, 50.5, 40, 54.5), radius=2 * u, fill=ink)
    return img.resize((size, size), Image.LANCZOS)


def ensure_ico() -> str:
    """Mehrgroessen-.ico fuer Verknuepfungen erzeugen (idempotent)."""
    if not os.path.exists(ICO_PATH):
        os.makedirs(APP_DIR, exist_ok=True)
        base = make_icon(size=256)
        base.save(ICO_PATH, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                   (64, 64), (128, 128), (256, 256)])
    return ICO_PATH
