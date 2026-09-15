"""Flow-Bar fuer macOS: dieselbe animierte Pill wie auf Windows, als
AppKit-NSPanel statt Tk (PORTING.md 3.3 / Phase 3b).

Architektur:
- Choreografie (Tweens, Timing, Farben, Text-Layout) kommt geteilt aus
  overlay_model.py - die Pille verhaelt sich auf beiden Plattformen gleich.
- Das Panel haengt am NSApplication-Main-Loop, den pystray (Tray-Icon) auf
  dem Main-Thread ohnehin betreibt: start() plant den UI-Aufbau per
  AppHelper.callAfter auf den Main-Loop, der Render-Tick ist ein
  selbst-nachladender AppHelper.callLater-Timer (schnell nur solange die
  Pille sichtbar ist, sonst Schongang).
- Alle set_*-Methoden sind queue-basiert und von beliebigen Threads
  aufrufbar (gleicher Vertrag wie das Windows-Overlay).
- Click-through via setIgnoresMouseEvents; Hover-Ausklappen fragt wie auf
  Windows nur die globale Mausposition ab (NSEvent.mouseLocation).
- Echte Fenster-Transparenz (kein Farb-Schluessel-Trick noetig): Panel ist
  nicht-opak mit clearColor, Ein-/Ausblenden laeuft ueber setAlphaValue_.
- Die View ist geflippt (isFlipped=True), damit die y-nach-unten-Geometrie
  aus overlay.py 1:1 uebernommen werden kann.

Faellt der AppKit-Aufbau fehl (z.B. kein WindowServer in Headless-CI),
degradiert die Pille zum stillen No-op - das Diktat laeuft weiter.
NullOverlay bleibt als expliziter Fallback fuer Umgebungen ohne pyobjc.
"""

import collections
import logging
import math
import queue
import time

from ...overlay_model import (
    ARC_TAP, BAR_SPAN, BAR_STEP, BAR_W, BOTTOM_MARGIN, CHECK_S,
    EXPAND_MAX_LINES, EXPAND_VPAD, FONT_SIZE, GLASS_ALPHA, H, MAX_TEXT_PX,
    MIN_VISIBLE_S, MORPH_S, N_BARS, ORB_GROW_S, ORB_PROCESSING, ORB_SIZE,
    PAD_BOTTOM, PAD_R, PAD_TOP,
    REDUCED_FADE_S, RING_BOUNCE, SLIDE_PX, SOLID_ALPHA, SPRING_ALPHA,
    SPRING_ARC, SPRING_EXPAND, SPRING_HIDE, SPRING_RING, SPRING_SHOW,
    SPRING_WIDTH, TEXT_STATES, THEMES, WAVE_DT, WAVE_LEFT, WAVE_STATES,
    Spring, Tween, check_path, clamp, ease_out, fit_text_tail, mix, orb_dots,
    smooth, wrap_text,
)

log = logging.getLogger("localflow.darwin")

TICK_FAST = 1 / 60          # sichtbar: fluessige Animation
TICK_IDLE = 0.10            # unsichtbar: nur Queue abholen


class NullOverlay:
    """API-kompatibler No-op (Fallback ohne pyobjc/WindowServer)."""

    def start(self):
        log.info("Overlay-Fallback aktiv (NullOverlay) - Status-Feedback "
                 "kommt ueber Sounds.")

    def set_state(self, state: str):
        log.debug("Overlay-State (no-op): %s", state)

    def set_level(self, level: float):
        pass

    def set_text(self, text: str):
        pass

    def set_glass(self, enabled: bool):
        pass

    def set_source(self, source: str):
        pass

    def set_style(self, font_family=None, font_size=None):
        pass

    def set_theme(self, theme: str):
        pass

    def set_reduced_motion(self, enabled: bool):
        pass


class DarwinOverlay:
    """Animierte Pill auf NSPanel; Vertrag identisch zum Windows-Overlay."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._panel = None
        self._view = None
        self._font = None
        self._started = False
        self._dead = False       # AppKit-Aufbau gescheitert -> No-op
        self._st = None          # Zustands-Dict, existiert erst nach _setup

    # --- oeffentlicher Vertrag (beliebige Threads) ---------------------

    def start(self):
        if self._started:
            return
        self._started = True
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self._setup)
        except Exception:  # noqa: BLE001 - ohne pyobjc: stiller No-op
            self._dead = True
            log.exception("AppKit-Overlay nicht verfuegbar - Pille deaktiviert")

    def set_state(self, state: str):
        self._queue.put(("state", state))

    def set_level(self, level: float):
        self._queue.put(("level", level))

    def set_text(self, text: str):
        self._queue.put(("text", text or ""))

    def set_glass(self, enabled: bool):
        self._queue.put(("glass", bool(enabled)))

    def set_source(self, source: str):
        # Badge "iPad" gibt es bisher nur im Windows-Overlay; Kanal bleibt kompatibel.
        self._queue.put(("source", "ipad" if source == "ipad" else "pc"))

    def set_style(self, font_family=None, font_size=None):
        self._queue.put(("style", (font_family, font_size)))

    def set_theme(self, theme: str):
        self._queue.put(("theme", theme))

    def set_reduced_motion(self, enabled: bool):
        self._queue.put(("reduced", bool(enabled)))

    # --- AppKit (nur Main-Thread ab hier) -------------------------------

    def _measure(self, s: str) -> float:
        import AppKit
        attrs = {AppKit.NSFontAttributeName: self._font}
        return AppKit.NSString.stringWithString_(s).sizeWithAttributes_(attrs).width

    def _content_width(self, state: str) -> float:
        st = self._st
        if state in WAVE_STATES:
            if st["text"]:
                tw = min(self._measure(st["text"]) + 6, MAX_TEXT_PX)
                return WAVE_LEFT + tw + PAD_R
            return WAVE_LEFT + BAR_SPAN + PAD_R
        if state in ("processing", "done"):
            return 64
        if state == "loading":
            return 14 + 12 + 8 + self._measure("Lade Modelle …") + 14
        if state == "clipboard":
            return 14 + 14 + 8 + self._measure("In der Zwischenablage · Cmd+V") + 14
        if state == "error":
            return 14 + 7 + 8 + self._measure("Fehler") + 14
        return 100

    def _line_h(self) -> float:
        # Zeilenhoehe analog zu tkfont.metrics("linespace") + 3
        f = self._font
        return float(f.ascender() - f.descender() + f.leading()) + 3

    def _setup(self):
        try:
            import AppKit

            outer = self

            class _PillView(AppKit.NSView):
                def isFlipped(self):
                    return True

                def drawRect_(self, rect):  # noqa: N802 - ObjC-Selector
                    try:
                        outer._draw_frame()
                    except Exception:  # noqa: BLE001
                        log.debug("Overlay-Draw fehlgeschlagen", exc_info=True)

            self._AppKit = AppKit
            self._font = AppKit.NSFont.boldSystemFontOfSize_(FONT_SIZE)

            st = {
                "target": "hidden", "vis": "recording", "prev": None,
                "level": 0.0, "smooth": 0.0, "text": "",
                "shown": False, "shown_at": 0.0, "state_t0": 0.0,
                "wave_acc": 0.0, "scroll": 0.0, "win_alpha": -1.0,
                "pill_rect": None,   # (px, py, w, ph) in View-Koordinaten
                "glass": False, "col": THEMES["dark"],
                "reduced": False,    # Reduced Motion: Crossfade statt Slide
                "showing": None,     # Praesenz-Richtung (Feder-Tuning)
            }
            self._st = st
            st["line_h"] = self._line_h()

            base_w = max(self._content_width(s)
                         for s in WAVE_STATES + ("processing",) + TEXT_STATES)
            self._max_w = int(max(base_w, WAVE_LEFT + MAX_TEXT_PX + PAD_R)) + 8
            expand_max_h = 2 * EXPAND_VPAD + EXPAND_MAX_LINES * 48
            self._win_h = int(max(PAD_TOP + H, expand_max_h)
                              + SLIDE_PX + PAD_BOTTOM + 6)

            # Federn wie im Windows-Overlay (overlay_model.Spring): Ziel-
            # wechsel behalten die Geschwindigkeit. Nur der Content-Crossfade
            # hat eine feste Dauer.
            self._width = Spring(self._content_width("recording"), *SPRING_WIDTH)
            self._expand = Spring(0.0, *SPRING_EXPAND)
            self._fade = Tween(1.0, lambda p: p)
            self._ring = Spring(0.0, *SPRING_RING)
            self._arc = Spring(0.0, *SPRING_ARC)
            self._check = Tween(0.0, ease_out)
            self._slide = Spring(1.0, *SPRING_SHOW)
            self._alpha = Spring(0.0, *SPRING_ALPHA)
            self._wave = collections.deque([0.0] * N_BARS, maxlen=N_BARS)
            self._last_t = time.perf_counter()

            rect = AppKit.NSMakeRect(0, 0, self._max_w, self._win_h)
            style = (AppKit.NSWindowStyleMaskBorderless
                     | AppKit.NSWindowStyleMaskNonactivatingPanel)
            panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, style, AppKit.NSBackingStoreBuffered, False)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(AppKit.NSColor.clearColor())
            panel.setHasShadow_(False)
            panel.setLevel_(AppKit.NSStatusWindowLevel)
            panel.setIgnoresMouseEvents_(True)     # click-through, immer
            panel.setHidesOnDeactivate_(False)
            panel.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorStationary
                | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
            panel.setAlphaValue_(0.0)

            view = _PillView.alloc().initWithFrame_(rect)
            panel.setContentView_(view)
            panel.orderFrontRegardless()
            self._panel, self._view = panel, view

            self._tick()
            log.info("AppKit-Overlay bereit (NSPanel, %dx%d)",
                     self._max_w, self._win_h)
        except Exception:  # noqa: BLE001
            self._dead = True
            self._panel = None
            log.exception("AppKit-Overlay-Aufbau fehlgeschlagen - Pille "
                          "deaktiviert (Diktat laeuft weiter)")

    def _position_window(self):
        AppKit = self._AppKit
        screen = AppKit.NSScreen.mainScreen() or (
            AppKit.NSScreen.screens()[0] if AppKit.NSScreen.screens() else None)
        if screen is None:
            return
        vf = screen.visibleFrame()  # Arbeitsflaeche (ohne Dock/Menueleiste)
        x = vf.origin.x + vf.size.width / 2 - self._max_w / 2
        # Fenster-UNTERKANTE so, dass die eingeklappte Pill-Unterkante
        # BOTTOM_MARGIN ueber dem Arbeitsflaechen-Rand sitzt (wie Windows).
        y = vf.origin.y + BOTTOM_MARGIN - PAD_BOTTOM
        self._panel.setFrame_display_(
            AppKit.NSMakeRect(x, y, self._max_w, self._win_h), False)

    def _apply_state(self, new: str, now: float):
        st = self._st
        if new == st["target"]:
            return
        st["target"] = new
        if new in ("hidden", None):
            return
        old = st["vis"]
        if not st["shown"]:
            self._position_window()
            st["vis"], st["prev"] = new, None
            st["text"] = ""
            st["state_t0"] = now
            st["shown_at"] = now
            st["shown"] = True
            self._width.snap(self._content_width(new))
            self._fade.snap(1.0)
            self._ring.snap(1.0 if new == "locked" else 0.0)
            self._arc.snap(ARC_TAP if new == "armed" else 0.0)
            self._check.snap(1.0 if new == "done" else 0.0)
            self._slide.snap(0.0 if st["reduced"] else 1.0)
            self._expand.snap(0.0)
            st["showing"] = None
            self._wave.extend([0.0] * N_BARS)
            st["smooth"] = 0.0
            return
        if new == old:
            return
        if new in WAVE_STATES and old not in WAVE_STATES:
            st["text"] = ""
        st["vis"] = new
        self._width.to(self._content_width(new))
        if {old, new} <= set(WAVE_STATES):
            # Lock per Tipp (Impuls) darf ueberschwingen, zurueck nicht.
            bounce = new == "locked" and not st["reduced"]
            self._ring.tune(SPRING_RING[0], RING_BOUNCE if bounce else SPRING_RING[1])
            self._ring.to(1.0 if new == "locked" else 0.0)
            self._arc.to(ARC_TAP if new == "armed" else 0.0)
        else:
            st["prev"] = old
            st["state_t0"] = now
            self._fade.snap(0.0)
            self._fade.to(1.0, MORPH_S, now)
            self._ring.snap(1.0 if new == "locked" else 0.0)
            self._arc.snap(0.0)
            if new == "done":
                self._check.snap(0.0)
                self._check.to(1.0, CHECK_S, now + MORPH_S * 0.5)

    def _drain_queue(self, now: float):
        st = self._st
        try:
            while True:
                kind, value = self._queue.get_nowait()
                if kind == "state":
                    self._apply_state(value, now)
                elif kind == "level":
                    st["level"] = float(value)
                elif kind == "text":
                    st["text"] = value
                elif kind == "glass":
                    st["glass"] = value
                    st["win_alpha"] = -1.0
                elif kind == "theme":
                    st["col"] = THEMES.get(value, THEMES["dark"])
                elif kind == "reduced":
                    st["reduced"] = bool(value)
                    st["showing"] = None
                elif kind == "style":
                    fam, sz = value
                    try:
                        AppKit = self._AppKit
                        size = max(12, min(32, int(sz))) if sz else \
                            float(self._font.pointSize())
                        if fam:
                            f = (AppKit.NSFont.fontWithName_size_(str(fam), size)
                                 or AppKit.NSFont.boldSystemFontOfSize_(size))
                        else:
                            # nur Groesse: aktuelle Familie behalten
                            f = self._font.fontWithSize_(size)
                        self._font = f
                        st["line_h"] = self._line_h()
                    except Exception:  # noqa: BLE001
                        log.debug("Schrift-Umstellung fehlgeschlagen", exc_info=True)
        except queue.Empty:
            pass

    def _tick(self):
        from PyObjCTools import AppHelper
        present = False
        try:
            st = self._st
            now = time.perf_counter()
            dt = min(now - self._last_t, 0.1)
            self._last_t = now
            self._drain_queue(now)

            want = st["target"] not in ("hidden", None)
            hold = st["shown"] and (now - st["shown_at"]) < MIN_VISIBLE_S
            showing = bool(want or hold)
            if showing != st["showing"]:
                st["showing"] = showing
                self._slide.tune(*(SPRING_SHOW if showing else SPRING_HIDE))
                self._alpha.tune(*((REDUCED_FADE_S, 1.0) if st["reduced"]
                                   else SPRING_ALPHA))
            self._alpha.to(1.0 if showing else 0.0)
            if st["reduced"]:
                self._slide.snap(0.0)
            else:
                self._slide.to(0.0 if showing else 1.0)
            self._alpha.update(dt)
            self._slide.update(dt)
            present = st["shown"] and (self._alpha.v > 0.003
                                       or self._alpha.target > 0.0)

            if present:
                target = st["level"] if (st["vis"] in WAVE_STATES and want) else 0.0
                tau = 0.035 if target > st["smooth"] else 0.09
                st["smooth"] += (target - st["smooth"]) * (1 - math.exp(-dt / tau))
                st["wave_acc"] += dt
                while st["wave_acc"] >= WAVE_DT:
                    st["wave_acc"] -= WAVE_DT
                    self._wave.append(st["smooth"] if st["vis"] in WAVE_STATES else 0.0)
                st["scroll"] = st["wave_acc"] / WAVE_DT
                if st["vis"] not in WAVE_STATES:
                    k = math.exp(-dt / 0.055)
                    for i in range(len(self._wave)):
                        self._wave[i] *= k

                # Hover: globale Mausposition gegen das Pill-Rechteck des
                # letzten Frames (Screen-Koordinaten, y nach oben).
                hovering = False
                if st["vis"] in WAVE_STATES and st["text"] and st["pill_rect"]:
                    try:
                        AppKit = self._AppKit
                        loc = AppKit.NSEvent.mouseLocation()
                        fr = self._panel.frame()
                        px, py, w, ph = st["pill_rect"]
                        left = fr.origin.x + px
                        top = fr.origin.y + fr.size.height - py  # y-up
                        m = 8
                        over = (left - m <= loc.x <= left + w + m
                                and top - ph - m <= loc.y <= top + m)
                        if over and len(wrap_text(st["text"], MAX_TEXT_PX,
                                                  self._measure)) > 1:
                            hovering = True
                    except Exception:  # noqa: BLE001
                        hovering = False
                self._expand.to(1.0 if hovering else 0.0)
                self._expand.update(dt)

                if st["vis"] in WAVE_STATES:
                    cw = self._content_width(st["vis"])
                    fw = WAVE_LEFT + MAX_TEXT_PX + PAD_R
                    self._width.to(cw + (fw - cw) * self._expand.v)
                self._width.update(dt)
                self._ring.update(dt)
                self._arc.update(dt)
                self._check.update(now)
                if self._fade.update(now) >= 1.0:
                    st["prev"] = None
                self._now = now
                self._view.setNeedsDisplay_(True)

                base = GLASS_ALPHA if st["glass"] else SOLID_ALPHA
                a = base * clamp(self._alpha.v)
                if abs(a - st["win_alpha"]) > 0.004:
                    self._panel.setAlphaValue_(a)
                    st["win_alpha"] = a
            elif st["shown"]:
                st["shown"] = False
                st["prev"] = None
                self._fade.snap(1.0)
                if st["win_alpha"] != 0.0:
                    self._panel.setAlphaValue_(0.0)
                    st["win_alpha"] = 0.0
        except Exception:  # noqa: BLE001
            log.debug("Overlay-Tick fehlgeschlagen", exc_info=True)
        finally:
            # Timer IMMER nachladen (eine Exception darf die Kette nicht toeten)
            AppHelper.callLater(TICK_FAST if present else TICK_IDLE, self._tick)

    # --- Zeichnen (im drawRect_ der View) --------------------------------

    def _color(self, hexcol: str):
        AppKit = self._AppKit
        r = int(hexcol[1:3], 16) / 255
        g = int(hexcol[3:5], 16) / 255
        b = int(hexcol[5:7], 16) / 255
        return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)

    def _fill_oval(self, x, y, w, h, hexcol):
        AppKit = self._AppKit
        self._color(hexcol).setFill()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            AppKit.NSMakeRect(x, y, w, h)).fill()

    def _fill_rect(self, x, y, w, h, hexcol):
        AppKit = self._AppKit
        self._color(hexcol).setFill()
        AppKit.NSBezierPath.fillRect_(AppKit.NSMakeRect(x, y, w, h))

    def _stroke_line(self, x1, y1, x2, y2, hexcol, width=1.0):
        AppKit = self._AppKit
        p = AppKit.NSBezierPath.bezierPath()
        p.moveToPoint_((x1, y1))
        p.lineToPoint_((x2, y2))
        p.setLineWidth_(width)
        self._color(hexcol).setStroke()
        p.stroke()

    def _draw_text(self, x, cy, s, hexcol):
        """Text linksbuendig, vertikal auf cy zentriert (wie anchor='w')."""
        AppKit = self._AppKit
        attrs = {AppKit.NSFontAttributeName: self._font,
                 AppKit.NSForegroundColorAttributeName: self._color(hexcol)}
        ns = AppKit.NSString.stringWithString_(s)
        size = ns.sizeWithAttributes_(attrs)
        ns.drawAtPoint_withAttributes_((x, cy - size.height / 2), attrs)

    def _rounded_pill(self, x, y, w, ph):
        st = self._st
        r = H // 2
        if ph <= H + 0.5:
            # Eingeklappt: Stadium-Pille mit Rand (wie Windows)
            self._fill_oval(x + 1, y + 1, 2 * r - 2, H - 2, st["col"]["bg"])
            self._fill_oval(x + w - 2 * r + 1, y + 1, 2 * r - 2, H - 2, st["col"]["bg"])
            self._fill_rect(x + r, y + 1, w - 2 * r, H - 2, st["col"]["bg"])
            # Rand: Ovale nachziehen + Deck-/Bodenlinie
            AppKit = self._AppKit
            for ox in (x + 1, x + w - 2 * r + 1):
                p = AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                    AppKit.NSMakeRect(ox, y + 1, 2 * r - 2, H - 2))
                self._color(st["col"]["border"]).setStroke()
                p.stroke()
            # Mittelteil des Rands wieder mit bg fuellen (Oval-Konturen
            # laufen sonst durch die Pillenmitte)
            self._fill_rect(x + r, y + 1, w - 2 * r, H - 2, st["col"]["bg"])
            self._stroke_line(x + r, y + 1, x + w - r, y + 1, st["col"]["border"])
            self._stroke_line(x + r, y + H - 1, x + w - r, y + H - 1, st["col"]["border"])
            return
        # Ausgeklappt: abgerundetes Rechteck (ohne Rand, wie Windows)
        AppKit = self._AppKit
        self._color(st["col"]["bg"]).setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AppKit.NSMakeRect(x, y, w, ph), r, r).fill()

    def _draw_content(self, state, alpha, now, px, py, w, ph=float(H)):
        st = self._st
        if alpha <= 0.01:
            return
        bg, fg, dim = st["col"]["bg"], st["col"]["fg"], st["col"]["dim"]
        cy = py + ph - H / 2
        if state in WAVE_STATES:
            rp = self._ring.v
            pulse = 1.0 if state == "armed" else \
                1 + 0.10 * math.sin((now - st["shown_at"]) * 4.5)
            # rp > 1 = Ueberschwingen der Lock-Feder: Ring poppt kurz groesser
            r = 3.2 * pulse * (1 + 0.22 * math.sin(math.pi * clamp(rp))
                               + 0.9 * max(0.0, rp - 1.0))
            cx = px + 18
            if rp < 0.99:
                self._fill_oval(cx - r, cy - r, 2 * r, 2 * r,
                                mix(bg, fg, (1 - rp) * alpha))
            if rp > 0.01:
                AppKit = self._AppKit
                p = AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                    AppKit.NSMakeRect(cx - r, cy - r, 2 * r, 2 * r))
                p.setLineWidth_(1.6)
                self._color(mix(bg, fg, rp * alpha)).setStroke()
                p.stroke()
            av = self._arc.v
            if av > 0.01 and rp < 0.5:
                # Ringbogen (Tipp-Fenster); geflippte View: Winkel laufen
                # gespiegelt, deshalb von 90 abwaerts
                AppKit = self._AppKit
                ra = r + 3.0
                p = AppKit.NSBezierPath.bezierPath()
                p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                    (cx, cy), ra, -90.0, -90.0 + 360.0 * clamp(av), False)
                p.setLineWidth_(1.4)
                self._color(mix(bg, fg, 0.8 * alpha)).setStroke()
                p.stroke()
            zone = max(6.0, w - WAVE_LEFT - PAD_R)
            x0 = px + WAVE_LEFT
            if st["text"] and ph > H + 1.0:
                lines = wrap_text(st["text"], zone, self._measure)
                maxn = max(1, int((ph - 2 * EXPAND_VPAD) / st["line_h"]))
                col = mix(bg, fg, 0.94 * alpha)
                for k, ln in enumerate(reversed(lines[-maxn:])):
                    self._draw_text(x0, cy - k * st["line_h"], ln, col)
            elif st["text"]:
                shown = fit_text_tail(st["text"], zone, self._measure)
                self._draw_text(x0, cy, shown, mix(bg, fg, 0.94 * alpha))
            else:
                scale = min(1.0, zone / BAR_SPAN)
                self._stroke_line(x0, cy, x0 + BAR_SPAN * scale, cy,
                                  mix(bg, fg, 0.22 * alpha))
                bw = max(1.0, BAR_W * scale)
                for i, lvl in enumerate(self._wave):
                    h = lvl * (H - 14) / 2
                    if h < 0.5:
                        continue
                    off = i * BAR_STEP - st["scroll"] * BAR_STEP
                    edge = clamp((off + BAR_STEP) / 10.0)
                    if edge <= 0.0:
                        continue
                    x = x0 + off * scale
                    shade = (0.45 + 0.55 * (i / (N_BARS - 1))) * edge * alpha
                    self._fill_rect(x, cy - h, bw, 2 * h, mix(bg, fg, shade))
        elif state == "processing":
            # Thinking-Orb "working" (geteilte Geometrie, CoreGraphics glaettet)
            grow = smooth((now - st["state_t0"]) / ORB_GROW_S)
            t_orb = now
            if st["reduced"]:
                grow, t_orb = 1.0, 0.6
            ox = px + w / 2 - ORB_SIZE / 2
            oy = cy - ORB_SIZE / 2
            for x, y, rr, white, a in orb_dots(ORB_PROCESSING, t_orb, ORB_SIZE, grow):
                self._fill_oval(ox + x - rr, oy + y - rr, 2 * rr, 2 * rr,
                                mix(bg, fg, (1 - white) * a * alpha))
        elif state == "done":
            pts = check_path(px + w / 2, cy, clamp(self._check.v))
            if pts:
                AppKit = self._AppKit
                p = AppKit.NSBezierPath.bezierPath()
                p.moveToPoint_((pts[0], pts[1]))
                for i in range(2, len(pts), 2):
                    p.lineToPoint_((pts[i], pts[i + 1]))
                p.setLineWidth_(2.0)
                p.setLineCapStyle_(AppKit.NSLineCapStyleRound)
                p.setLineJoinStyle_(AppKit.NSLineJoinStyleRound)
                self._color(mix(bg, fg, alpha)).setStroke()
                p.stroke()
        elif state == "loading":
            AppKit = self._AppKit
            a0 = ((now - st["state_t0"]) * 240) % 360
            p = AppKit.NSBezierPath.bezierPath()
            # Geflippte View: Winkel laufen andersrum - fuer den Spinner egal.
            p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
                (px + 20, cy), 6.0, a0, a0 + 100)
            p.setLineWidth_(2.0)
            self._color(mix(bg, dim, alpha)).setStroke()
            p.stroke()
            self._draw_text(px + 34, cy, "Lade Modelle …", mix(bg, dim, alpha))
        elif state == "clipboard":
            AppKit = self._AppKit
            dimc = mix(bg, dim, alpha)
            p = AppKit.NSBezierPath.bezierPathWithRect_(AppKit.NSMakeRect(px + 15, cy - 6, 10, 13))
            p.setLineWidth_(1.4)
            self._color(dimc).setStroke()
            p.stroke()
            self._fill_rect(px + 18, cy - 8, 4, 3, dimc)
            self._draw_text(px + 36, cy, "In der Zwischenablage · Cmd+V",
                            mix(bg, fg, alpha))
        elif state == "error":
            self._fill_oval(px + 14, cy - 3.5, 7, 7, mix(bg, dim, alpha))
            self._draw_text(px + 29, cy, "Fehler", mix(bg, fg, alpha))

    def _draw_frame(self):
        st = self._st
        if st is None or not st["shown"]:
            return
        now = getattr(self, "_now", time.perf_counter())
        w = self._width.v
        px = (self._max_w - w) / 2
        slide_off = SLIDE_PX * clamp(self._slide.v, -0.25, 1.1)
        pill_bottom = (self._win_h - PAD_BOTTOM) + slide_off
        ph = float(H)
        if self._expand.v > 0.001 and st["text"]:
            zone = max(20.0, w - WAVE_LEFT - PAD_R)
            nlines = min(len(wrap_text(st["text"], zone, self._measure)),
                         EXPAND_MAX_LINES)
            full_h = max(float(H), 2 * EXPAND_VPAD + max(1, nlines) * st["line_h"])
            full_h = min(full_h, float(self._win_h - PAD_BOTTOM - 2))
            ph = H + (full_h - H) * self._expand.v
        py = pill_bottom - ph
        # Materialisieren: die Pille waechst beim Einblenden von 86 % auf
        # 100 % um ihre Unterkante (Origin = wo sie herkommt), gekoppelt an
        # die Praesenz-Feder. CoreGraphics zeichnet geglaettet, deshalb nur
        # hier und nicht in der Tk-Variante. Reduced Motion: keine Skalierung.
        AppKit = self._AppKit
        scale = 1.0 if st["reduced"] else 0.86 + 0.14 * clamp(self._alpha.v)
        AppKit.NSGraphicsContext.saveGraphicsState()
        if scale < 0.999:
            tf = AppKit.NSAffineTransform.transform()
            tf.translateXBy_yBy_(self._max_w / 2, pill_bottom)
            tf.scaleBy_(scale)
            tf.translateXBy_yBy_(-self._max_w / 2, -pill_bottom)
            tf.concat()
        self._rounded_pill(px, py, w, ph)

        f = self._fade.v
        if st["prev"] is not None:
            a_prev = smooth(1 - f / 0.45)
            self._draw_content(st["prev"], a_prev, now, px, py, w, ph)
            a_vis = smooth((f - 0.5) / 0.5)
        else:
            a_vis = 1.0
        if st["vis"] in TEXT_STATES:
            a_vis *= clamp((w - self._content_width(st["vis"]) + 8) / 8)
        self._draw_content(st["vis"], a_vis, now, px, py, w, ph)
        AppKit.NSGraphicsContext.restoreGraphicsState()
        st["pill_rect"] = (px, py, w, ph)


def make_overlay():
    """Echtes AppKit-Overlay, wenn pyobjc da ist - sonst NullOverlay."""
    import importlib
    try:
        importlib.import_module("AppKit")
        importlib.import_module("PyObjCTools.AppHelper")
        return DarwinOverlay()
    except Exception:  # noqa: BLE001
        log.warning("pyobjc nicht verfuegbar - Overlay deaktiviert (NullOverlay)")
        return NullOverlay()
