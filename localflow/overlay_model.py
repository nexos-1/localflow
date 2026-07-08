"""Plattformneutraler Kern der Flow-Bar (Overlay-Pill).

Alles hier ist reine Logik ohne UI-Toolkit: Farb-Themen, Geometrie- und
Timing-Konstanten, Easing/Tween-Engine, Farb-Mix (Fake-Alpha Richtung
Pill-Hintergrund) und Text-Layout-Helfer. Genutzt von overlay.py (Tk,
Windows) und platform/darwin/overlay.py (AppKit, macOS) - Aenderungen an
der Choreografie wirken damit auf beiden Plattformen gleich.

Die Text-Helfer nehmen eine measure(str)->px Funktion, weil die Breiten-
Messung toolkit-spezifisch ist (tkfont vs. NSAttributedString).
"""

# Farb-Themen der Pille. Saemtliche Fake-Alpha-Fades mischen Richtung "bg",
# deshalb funktioniert jedes in sich konsistente Thema ohne weitere Aenderung.
THEMES = {
    # Standard: schwarze Pille, fast-weisser Text
    "dark": {"bg": "#000000", "border": "#26282c", "fg": "#f2f3f5", "dim": "#6f7480"},
    # Light Mode: gemutetes, neutrales Apple-Grau (iOS systemGray2 dark),
    # reinweisser Text; Kontrast >= 4.5:1 (WCAG AA)
    "light": {"bg": "#636366", "border": "#77777a", "fg": "#ffffff", "dim": "#d1d1d6"},
}

H = 40                      # Pill-Hoehe
FONT_SIZE = 11              # Schriftgroesse in der Pille
TICK_MS = 15                # Ziel ~60 fps (Animation selbst ist dt-basiert)
N_BARS = 22
BAR_W, BAR_GAP = 2, 2
BAR_STEP = BAR_W + BAR_GAP
BAR_SPAN = N_BARS * BAR_STEP - BAR_GAP
WAVE_LEFT = 32              # Punkt/Ring-Zone links vor der Waveform (14+8+10)
PAD_R = 14
WAVE_DT = 1 / 30            # Waveform-Scrolltakt, von der Framerate entkoppelt

SHOW_S = 0.20               # Einblenden (Fade + Slide-up)
HIDE_S = 0.16               # Ausblenden
MORPH_S = 0.22              # State-Wechsel: Breiten-Tween + Content-Fade
MIN_VISIBLE_S = 0.30        # Anti-Blitz: so lange bleibt die Pill mindestens
PAD_TOP = 6                 # Canvas-Luft oben (Platz fuer Slide-Overshoot)
PAD_BOTTOM = 6              # Canvas-Luft unter der Pille (Verankerung)
SLIDE_PX = 14
BOTTOM_MARGIN = 44          # Abstand Pill-Unterkante zum Arbeitsflaechen-Rand
EXPAND_S = 0.18             # Hover-Ausklappen: Dauer der Wachstums-Animation
EXPAND_MAX_LINES = 8        # so viele Zeilen zeigt die ausgeklappte Pille max.
EXPAND_VPAD = 8             # vertikaler Innenabstand im ausgeklappten Zustand
SOLID_ALPHA = 0.96          # Normal: fast deckende Pille
GLASS_ALPHA = 0.70          # Glas-Optik: Pille durchscheinend (Desktop schimmert)

WAVE_STATES = ("recording", "locked")
TEXT_STATES = ("loading", "clipboard", "error")
MAX_TEXT_PX = 460           # max Breite der Live-Transkript-Zone in der Pill


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else (hi if v > hi else v)


def ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


def ease_in_out(p: float) -> float:
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_out_back(p: float) -> float:
    c = 1.28  # dezenter Overshoot (~1.5 px bei 14 px Slide)
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def smooth(p: float) -> float:
    p = clamp(p)
    return p * p * (3 - 2 * p)


class Tween:
    """Zielwert-Animation mit fester Dauer und Easing; ein neues Ziel mitten
    im Lauf startet stetig vom aktuellen Wert (kein Sprung)."""

    __slots__ = ("v", "target", "ease", "_from", "_t0", "_dur")

    def __init__(self, v: float, ease):
        self.v = self.target = self._from = float(v)
        self.ease = ease
        self._t0 = self._dur = 0.0

    def to(self, target: float, dur: float, now: float):
        if abs(target - self.target) < 1e-9:
            return
        self._from, self.target = self.v, float(target)
        self._t0, self._dur = now, dur

    def snap(self, v: float):
        self.v = self.target = self._from = float(v)
        self._dur = 0.0

    def update(self, now: float) -> float:
        if self._dur <= 0.0 or now >= self._t0 + self._dur:
            self.v = self.target
        else:
            q = (now - self._t0) / self._dur
            self.v = self._from + (self.target - self._from) * self.ease(q)
        return self.v


def mix(c1: str, c2: str, t: float) -> str:
    t = clamp(t)
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def fit_text_tail(s: str, max_px: float, measure) -> str:
    """Zeigt das ENDE des Textes (neueste Woerter), links mit … gekuerzt."""
    if measure(s) <= max_px:
        return s
    i = 0
    while i < len(s) and measure("… " + s[i:]) > max_px:
        i += 1
    return "… " + s[i:]


def wrap_text(s: str, max_px: float, measure) -> list[str]:
    """Wort-Umbruch auf max_px Breite (fuer die ausgeklappte Ansicht)."""
    lines, cur = [], ""
    for word in s.split():
        trial = word if not cur else cur + " " + word
        if measure(trial) <= max_px or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]
