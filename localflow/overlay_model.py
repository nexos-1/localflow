"""Plattformneutraler Kern der Flow-Bar (Overlay-Pill).

Alles hier ist reine Logik ohne UI-Toolkit: Farb-Themen, Geometrie- und
Timing-Konstanten, Easing/Tween-Engine, Farb-Mix (Fake-Alpha Richtung
Pill-Hintergrund) und Text-Layout-Helfer. Genutzt von overlay.py (Tk,
Windows) und platform/darwin/overlay.py (AppKit, macOS) - Aenderungen an
der Choreografie wirken damit auf beiden Plattformen gleich.

Die Text-Helfer nehmen eine measure(str)->px Funktion, weil die Breiten-
Messung toolkit-spezifisch ist (tkfont vs. NSAttributedString).
"""

import math

# Farb-Themen der Pille. Saemtliche Fake-Alpha-Fades mischen Richtung "bg",
# deshalb funktioniert jedes in sich konsistente Thema ohne weitere Aenderung.
THEMES = {
    # Standard: dunkle Pille mit Verlauf (bg oben -> bg2 unten, unten
    # durchscheinender), fast-weisser Text. Referenz: Apples Status-Pille.
    "dark": {"bg": "#161618", "bg2": "#0b0b0d", "border": "#2a2a2e", "fg": "#f5f5f7", "dim": "#9a9ca6"},
    # Light Mode: weisse Pille mit dunkler Tinte (Text 17:1, Sekundaer 5.1:1)
    # und kraeftigerer Haarlinie, damit sie sich von hellen Apps abhebt
    "light": {"bg": "#ffffff", "bg2": "#f4f4f6", "border": "#c6c6cc", "fg": "#1c1c1e", "dim": "#6e6e73"},
}
# Deckkraft des Verlaufs (oben, unten): unten laeuft die Pille ins
# Transparente aus, im Glas-Modus deutlich staerker
PILL_ALPHA = {"solid": (1.0, 0.97), "glass": (0.68, 0.52)}

H = 48                      # Pill-Hoehe (logisch; x Monitor-Skalierung)
FONT_SIZE = 18              # Schriftgroesse in der Pille (logisch)
TICK_MS = 15                # Ziel ~60 fps (Animation selbst ist dt-basiert)
N_BARS = 22
BAR_W, BAR_GAP = 3, 3
BAR_STEP = BAR_W + BAR_GAP
BAR_SPAN = N_BARS * BAR_STEP - BAR_GAP
WAVE_LEFT = 50              # Orb-Zone links vor dem Text (Orb 26 px + Luft)
ORB_ONLY_W = 64             # Pillenbreite ohne Text: nur der Ring, mittig
PAD_R = 20
WAVE_DT = 1 / 30            # Waveform-Scrolltakt, von der Framerate entkoppelt

SHOW_S = 0.20               # Einblenden (Fade + Slide-up)
HIDE_S = 0.16               # Ausblenden
MORPH_S = 0.22              # State-Wechsel: Breiten-Tween + Content-Fade
MIN_VISIBLE_S = 0.30        # Anti-Blitz: so lange bleibt die Pill mindestens
PAD_TOP = 6                 # Canvas-Luft oben (Platz fuer Slide-Overshoot)
PAD_BOTTOM = 6              # Canvas-Luft unter der Pille (Verankerung)
SLIDE_PX = 18
BOTTOM_MARGIN = 44          # Standard-Abstand der Pille zum Arbeitsflaechen-Rand
SIDE_PAD = 24               # Innenabstand der Pille im Fenster bei links/rechts
# Position der Pille auf der Arbeitsflaeche (Einstellung overlay_position)
POSITIONS = ("bottom-center", "bottom-left", "bottom-right",
             "top-center", "top-left", "top-right")
EXPAND_S = 0.18             # Hover-Ausklappen: Dauer der Wachstums-Animation
EXPAND_MAX_LINES = 8        # so viele Zeilen zeigt die ausgeklappte Pille max.
EXPAND_VPAD = 8             # vertikaler Innenabstand im ausgeklappten Zustand
SOLID_ALPHA = 0.96          # Normal: fast deckende Pille
GLASS_ALPHA = 0.70          # Glas-Optik: Pille durchscheinend (Desktop schimmert)

# Federn statt fester Dauern (Apple: "response" in Sekunden + Daempfungsgrad,
# vgl. Designing Fluid Interfaces). Kritisch gedaempft (1.0) = kein
# Ueberschwingen; nur der Lock-Ring darf schwingen, weil ein Tipp Impuls hat.
# Ein Zielwechsel mitten im Lauf behaelt die Geschwindigkeit - ein Hide,
# das ein laufendes Show unterbricht, bremst sichtbar ab statt abzureissen.
SPRING_SHOW = (0.30, 1.0)   # Slide beim Einblenden (response s, damping)
SPRING_HIDE = (0.22, 1.0)   # Slide beim Ausblenden
SPRING_ALPHA = (0.22, 1.0)  # Praesenz (Fenster-Alpha)
SPRING_WIDTH = (0.28, 1.0)  # Breiten-Morph, auch fuer wachsenden Live-Text
SPRING_EXPAND = (0.35, 1.0)  # Bubble (Ausklappen), Origin Pillen-Unterkante
SPRING_RING = (0.30, 1.0)   # Ring <-> Punkt ohne Impuls (z.B. Replay)
RING_BOUNCE = 0.55          # Daempfung beim Lock per Doppeltipp (~12 % Ueberschwingen)
SPRING_ARC = (0.30, 1.0)    # Ringbogen im Tipp-Fenster (Antizipation)
ARC_TAP = 0.25              # so weit (0..1 Umfang) waechst der Bogen nach Tipp 1
REDUCED_FADE_S = 0.20       # Reduced Motion: reiner Crossfade, kein Slide
MATERIALIZE_FROM = 0.86     # Einblenden: Pille waechst von 86 % um ihre Unterkante
LEAN_SCALE = 0.97           # Tipp-Fenster: Pille lehnt sich minimal zurueck
SPRING_LEAN = (0.20, 1.0)   # Feder fuers Zuruecklehnen
HOLD_EXPAND_S = 1.5         # Bubble klappt auch auf, wenn der Hotkey so lange gehalten wird

# armed = kurzer Tipp, Tipp-Fenster laeuft (Aufnahme geht weiter, Ringbogen
# deutet das moegliche Freisprechen an); done = eingefuegt (Haken).
WAVE_STATES = ("recording", "locked", "armed")
TEXT_STATES = ("loading", "clipboard", "error")
CHECK_S = 0.24              # Haken zeichnet sich in dieser Zeit (ease-out)
DONE_HOLD_S = 0.55          # so lange steht der Haken, bevor die Pille geht
CLIPBOARD_HOLD_S = 2.5      # Standzeit "In der Zwischenablage"
ERROR_HOLD_S = 2.0          # Standzeit "Fehler"
MAX_TEXT_PX = 560           # max Breite der Live-Transkript-Zone in der Pill


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


class Spring:
    """Feder mit Apple-Parametern (response in s, damping ratio). Semi-
    implizites Euler mit Substeps: auch ein verspaeteter Tick (dt bis 0.1 s)
    bleibt stabil. Ein neues Ziel behaelt die aktuelle Geschwindigkeit."""

    __slots__ = ("v", "vel", "target", "k", "c")

    def __init__(self, v: float, response: float = 0.3, damping: float = 1.0):
        self.v = self.target = float(v)
        self.vel = 0.0
        self.tune(response, damping)

    def tune(self, response: float, damping: float):
        w = 2 * math.pi / response      # Steifigkeit aus der Periode
        self.k, self.c = w * w, 2 * damping * w

    def to(self, target: float, velocity: float | None = None):
        self.target = float(target)
        if velocity is not None:
            self.vel = float(velocity)  # Uebergabe aus einer Geste

    def snap(self, v: float):
        self.v = self.target = float(v)
        self.vel = 0.0

    @property
    def settled(self) -> bool:
        return self.vel == 0.0 and self.v == self.target

    def update(self, dt: float) -> float:
        if dt <= 0.0:
            return self.v
        if self.settled:
            return self.v
        n = int(dt / 0.004) + 1
        h = dt / n
        for _ in range(n):
            a = -self.k * (self.v - self.target) - self.c * self.vel
            self.vel += a * h
            self.v += self.vel * h
        if abs(self.v - self.target) < 1e-3 and abs(self.vel) < 1e-2:
            self.v, self.vel = self.target, 0.0
        return self.v


def mix(c1: str, c2: str, t: float) -> str:
    t = clamp(t)
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


# ---------------------------------------------------------------- Thinking-Orb
# Verarbeitungs-Indikator: ein "working"-Orb (Partikel auf gekippten Bahnen)
# statt dreier wandernder Punkte. Portiert aus thinking-orbs (MIT, Jakub
# Antalik, https://github.com/Jakubantalik/thinking-orbs): orbits.ts,
# lattice.ts (frameWave = "listening") und die Preset-Skalierung aus
# presets.ts / profiles.ts. Reine Geometrie ueber math: ein Frame ist eine
# fertige, z-sortierte Liste (x, y, z, r, white, a) im Orb-Raum 0..size;
# die Painter (Tk, AppKit) zeichnen nur noch. white = Tintenwert (0 = volle
# Tinte, 1 = Papier); auf der Pille ist bg das Papier und fg die Tinte,
# also Deckkraft = (1 - white) * a. Numerisch gegen spec/orbs-golden.json
# der Originalbibliothek verifiziert (tests/test_orb_geometry.py).
ORB_SIZE = 26               # Zeichengroesse des Verarbeitungs-Orbs in der Pille
ORB_PRESET = 32             # Pillen-Preset: wenige, grosse, leuchtende Punkte
ORB_GROW_S = 0.35           # Orb waechst beim Betreten von processing aus der Mitte
ORB_PROCESSING = "ringfast"  # Verarbeitung: derselbe Ring, schneller
ORB_LISTENING = "ring"      # Aufnahme-Signal: 5 Punkte kreisen ruhig auf einer Bahn
ORB_LISTEN_SIZE = 26        # Zeichengroesse des Aufnahme-Orbs
ORB_MIN_R_TK = 0.6          # Tk kennt keine Kantenglaettung: kleinere Punkte fallen weg


def _hash_d(a: float, b: float) -> float:
    h = math.sin(a * 12.9898 + b * 78.233) * 43758.5453
    return h - math.floor(h)


def _js_round(x: float) -> int:
    return int(math.floor(x + 0.5))  # JS Math.round rundet .5 nach oben


def _make_proj(yaw: float, tilt: float, cx: float, cy: float, scale: float):
    st, ct = math.sin(tilt), math.cos(tilt)
    sy, cyw = math.sin(yaw), math.cos(yaw)

    def pt(x, y, z):
        x1 = x * cyw + z * sy
        z1 = -x * sy + z * cyw
        y1 = y * ct - z1 * st
        z2 = y * st + z1 * ct
        return cx + x1 * scale, cy - y1 * scale, z2
    return pt


def _radius_scale(size: float, pow_: float) -> float:
    return (size / 300.0) ** pow_


def _finalize(dots: list, r_min: float) -> list:
    out = [(x, y, z, max(r_min, r), w, a) for (x, y, z, r, w, a) in dots if a >= 0.02]
    out.sort(key=lambda d: d[2])
    return out


def frame_orbits(size: float, t: float, o: dict) -> list:
    """working: Partikel auf gekippten Orbits, Geisterbahnen dahinter."""
    cx = cy = size / 2
    R = (size / 2) * 0.82
    pt = _make_proj(t * 0.12, 0.3, cx, cy, 1)
    rs = _radius_scale(size, o.get("rsPow", 0.6))
    dots = []
    orbit_n = o.get("orbitN", 12)
    ghost_n = o.get("ghostN", 40)
    particles = o.get("particles", 3)
    ghost_r, ghost_a = o.get("ghostR", 0.9), o.get("ghostA", 0.5)
    part_r, part_rd = o.get("partR", 1.2), o.get("partRDepth", 1.6)
    for orb in range(orbit_n):
        h1, h2, h3 = _hash_d(orb, 1.7), _hash_d(orb, 5.2), _hash_d(orb, 8.9)
        ro = R * (0.45 + 0.52 * h1)
        th = h1 * 2 * math.pi
        phi = math.acos(2 * h2 - 1)
        nx, ny, nz = math.sin(phi) * math.cos(th), math.cos(phi), math.sin(phi) * math.sin(th)
        ux, uy, uz = -ny, nx, 0.0
        ul = max(1e-6, math.sqrt(ux * ux + uy * uy))
        ux, uy = ux / ul, uy / ul
        vx = ny * uz - nz * uy
        vy = nz * ux - nx * uz
        vz = nx * uy - ny * ux
        speed = (0.25 + 0.55 * h3) * (1 if h3 > 0.5 else -1)
        for k in range(ghost_n):
            a = (k / ghost_n) * 2 * math.pi
            ca, sa = math.cos(a), math.sin(a)
            px, py, z = pt((ux * ca + vx * sa) * ro, (uy * ca + vy * sa) * ro, (uz * ca + vz * sa) * ro)
            depth = (z / ro + 1) / 2
            dots.append((px, py, z, ghost_r * rs, 0.72, ghost_a * (0.4 + 0.6 * depth)))
        for m in range(particles):
            a = t * speed + (m / particles) * 2 * math.pi + h2 * 6
            ca, sa = math.cos(a), math.sin(a)
            px, py, z = pt((ux * ca + vx * sa) * ro, (uy * ca + vy * sa) * ro, (uz * ca + vz * sa) * ro)
            depth = (z / ro + 1) / 2
            dots.append((px, py, z, (part_r + part_rd * depth) * rs, 0.3 - 0.22 * depth, 1.0))
    return _finalize(dots, o.get("rMin", 0.3))


def frame_wave(size: float, t: float, o: dict) -> list:
    """listening: eine Welle rollt durch die Breitenringe einer Kugel."""
    cx = cy = size / 2
    R = (size / 2) * 0.874
    pt = _make_proj(t * 0.18, 0.38, cx, cy, 1)
    rs = _radius_scale(size, o.get("rsPow", 0.6))
    dots = []
    rings = o.get("rings", 15)
    lon_density = o.get("lonDensity", 40)
    r_base, r_depth = o.get("rBase", 0.6), o.get("rDepth", 1.7)
    for ri in range(rings + 1):
        lat = -math.pi / 2 + (ri / rings) * math.pi
        cl, sl = math.cos(lat), math.sin(lat)
        w = 0.62 * math.sin(t * 2.1 - ri * 0.52) + 0.38 * math.sin(t * 1.27 + ri * 0.83)
        rr = R * (0.88 + 0.105 * w)
        lon_count = max(1, _js_round(abs(cl) * lon_density))
        crest = max(0.0, w)
        for lj in range(lon_count):
            lon = (lj / lon_count) * 2 * math.pi
            px, py, z = pt(cl * math.cos(lon) * rr, sl * rr, cl * math.sin(lon) * rr)
            depth = (z / R + 1) / 2
            dots.append((px, py, z, (r_base + r_depth * depth) * (1 + 0.4 * crest) * rs,
                         0.66 - 0.56 * depth - 0.1 * crest, 1.0))
    return _finalize(dots, o.get("rMin", 0.3))


def frame_ring(size: float, t: float, o: dict) -> list:
    """Eigener, ruhiger Indikator (nicht aus thinking-orbs): n Punkte kreisen
    gleichmaessig auf einer Bahn, jeder atmet phasenversetzt in Groesse und
    Tinte - wie Apples Status-Pille, ohne Schwarm."""
    n = int(o.get("n", 5))
    c = size / 2
    R = size * o.get("orbit", 0.36)
    r0 = size * o.get("rDot", 0.075)
    spin = o.get("spin", 1.6)
    dots = []
    for i in range(n):
        ph = i * 2 * math.pi / n
        a = t * spin + ph
        breath = math.sin(t * 1.9 + i * 1.26)          # -1..1, je Punkt versetzt
        r = r0 * (1 + 0.35 * breath)
        white = 0.12 - 0.12 * breath                     # gross = hell
        dots.append((c + math.cos(a) * R, c + math.sin(a) * R, 0.0, r, white, 1.0))
    return dots


# Basisprofile (inkform "fine") + Presets je (Zustand, Groesse) aus presets.ts.
_ORB_BASE = {
    "orbits": {"orbitN": 12, "ghostN": 40, "ghostR": 0.9, "ghostA": 0.5, "particles": 3,
               "partR": 1.2, "partRDepth": 1.6, "rsPow": 0.6, "rMin": 0.3},
    "wave": {"rings": 15, "lonDensity": 40, "rBase": 0.6, "rDepth": 1.7, "rsPow": 0.6, "rMin": 0.3},
    "ring": {"n": 5, "orbit": 0.36, "rDot": 0.088, "spin": 1.5},
}
_ORB_MODE = {"working": "orbits", "listening": "wave", "ring": "ring", "ringfast": "ring"}
_ORB_FRAME = {"orbits": frame_orbits, "wave": frame_wave, "ring": frame_ring}
_ORB_STATE_SPEED = {"ringfast": 1.8}   # Verarbeitung: derselbe Ring, schneller
_ORB_PRESETS = {
    "orbits": {64: (1.885, 1.0, 1.0), 20: (3.9, 0.238, 2.4),      # (speed, count, size)
               # Pillen-Preset (eigene Abstimmung, nicht aus der Bibliothek):
               # 3 Bahnen, keine Geisterpunkte, grosse Partikel wie Apples Pille
               32: (2.2, 0.25, 3.6)},
    "wave": {64: (4.388, 0.341, 1.0), 20: (3.998, 0.105, 1.6), 32: (3.6, 0.15, 3.0)},
    "ring": {32: (1.0, 1.0, 1.0), 64: (1.0, 1.0, 1.0), 20: (1.0, 1.0, 1.0)},
}
_ORB_COUNT_LINEAR = ("orbitN", "ghostN")
_ORB_COUNT_PAIR = ("rings", "lonDensity")           # je Seite sqrt(count)
_ORB_RADIUS_KEYS = ("ghostR", "partR", "partRDepth", "rBase", "rDepth")
_orb_cache: dict = {}


def resolve_orb(state: str, size: int):
    """(frame_fn, speed, opts) fuer ein (Zustand, Preset-Groesse)-Paar,
    mit der count-/size-Skalierung aus profiles.ts (einmal berechnet)."""
    key = (state, size)
    hit = _orb_cache.get(key)
    if hit:
        return hit
    mode = _ORB_MODE[state]
    speed, count, size_mul = _ORB_PRESETS[mode][size]
    o = dict(_ORB_BASE[mode])
    if count != 1:
        rt = math.sqrt(count)
        if all(k in o for k in _ORB_COUNT_PAIR):
            for k in _ORB_COUNT_PAIR:
                o[k] = max(2, _js_round(o[k] * rt))
        for k in _ORB_COUNT_LINEAR:
            if k in o and o[k] != 0:
                o[k] = max(1, _js_round(o[k] * count))
    if size == ORB_PRESET and mode == "orbits":
        o["ghostN"] = 0        # Pille: nur die Partikel, keine Geisterbahnen
        o["particles"] = 3
    if size_mul != 1:
        for k in _ORB_RADIUS_KEYS:
            if k in o:
                o[k] = o[k] * size_mul
        o["rSizeMul"] = size_mul
    hit = (_ORB_FRAME[mode], speed * _ORB_STATE_SPEED.get(state, 1.0), o)
    _orb_cache[key] = hit
    return hit


def orb_dots(state: str, now: float, draw_size: float = ORB_SIZE,
             grow: float = 1.0, preset: int = 20, min_r: float = 0.0) -> list:
    """Fertige Punkte fuer den Painter: Orb-Raum 0..draw_size, um die Mitte
    mit `grow` skaliert (Einwachsen), Radien unter min_r verworfen (Tk)."""
    frame, speed, o = resolve_orb(state, preset)
    zoom = draw_size / preset
    c = draw_size / 2
    out = []
    for x, y, z, r, w, a in frame(preset, now * speed, o):
        rr = r * zoom * grow
        if rr < min_r:
            continue
        out.append((c + (x * zoom - c) * grow, c + (y * zoom - c) * grow, rr, w, a))
    return out


def check_path(cx: float, cy: float, p: float) -> list[float]:
    """Haken (kurzer Schenkel links unten, langer nach rechts oben) als
    Polylinie, bis zum Anteil p (0..1) seiner Gesamtlaenge gezeichnet -
    so zeichnet er sich wie ein Strich. Leer bei p ~ 0."""
    p = clamp(p)
    if p <= 0.01:
        return []
    a = (cx - 6.0, cy + 0.5)
    b = (cx - 1.5, cy + 5.0)
    c = (cx + 7.0, cy - 5.0)
    l1 = math.hypot(b[0] - a[0], b[1] - a[1])
    l2 = math.hypot(c[0] - b[0], c[1] - b[1])
    d = p * (l1 + l2)
    if d <= l1:
        f = d / l1
        return [a[0], a[1], a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]
    f = (d - l1) / l2
    return [a[0], a[1], b[0], b[1], b[0] + (c[0] - b[0]) * f, b[1] + (c[1] - b[1]) * f]


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
