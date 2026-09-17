"""macOS-Backend (EXPERIMENTELL - auf echter Hardware UNGETESTET).

Implementiert dieselbe make_backends()-Flaeche wie platform/win32.
Status (siehe PORTING.md, Phase 3):
- inject (NSPasteboard + Cmd+V via CGEvent), hotkey (pynput), sounds
  (afplay), autostart (LaunchAgent), single instance (flock): Code steht,
  laeuft aber erst nach Verifikation auf einem echten Mac / CI-Runner.
- Overlay: animierte Pill als AppKit-NSPanel (Phase 3b), Choreografie
  geteilt mit Windows (overlay_model.py); haengt am NSApp-Loop des
  Tray-Icons. Ohne pyobjc/WindowServer: NullOverlay-Fallback (Sounds).
- Ducking: No-op (macOS hat kein oeffentliches Per-App-Volume-API);
  did_mute_sessions=0 deaktiviert den Head-Trim automatisch.

Alle pyobjc/pynput-Importe passieren lazy in Funktionen, damit dieses
Paket auf jedem OS importierbar und syntax-/logikpruefbar bleibt.
"""

import logging
from types import SimpleNamespace

log = logging.getLogger("localflow.darwin")


def make_backends() -> SimpleNamespace:
    log.warning("macOS-Backend ist EXPERIMENTELL und auf echter Hardware "
                "ungetestet - siehe PORTING.md (Phase 3).")
    from . import autostart as _autostart
    from . import hotkey as _hotkey
    from . import inject as _inject
    from . import integration as _integration
    from . import sounds as _sounds
    from .ducking import NoopDucker
    from .overlay import make_overlay as _make_overlay

    # Tastatur-Layout (TIS) JETZT auf dem Main-Thread lesen: make_backends
    # laeuft beim App-Start im Main-Thread, spaetere Hotkey-Wechsel kommen
    # aus dem Dashboard-Thread und duerfen TIS nicht mehr anfassen.
    try:
        _hotkey.ensure_keycode_context()
    except Exception:  # noqa: BLE001 - ohne pynput (Tests, Fremd-OS) egal
        log.debug("Tastatur-Layout-Kontext nicht vorab lesbar", exc_info=True)

    return SimpleNamespace(
        make_ptt=lambda combo, controller, swallow_mouse=False, gate=None: _hotkey.PynputPtt(
            combo, controller, swallow_mouse=swallow_mouse, gate=gate),
        add_hotkey=_hotkey.add_hotkey,
        remove_hotkey=_hotkey.remove_hotkey,
        capture_combo=_hotkey.capture_combo,
        inject=_inject,
        make_ducker=lambda duck_volume: NoopDucker(duck_volume=duck_volume),
        make_overlay=_make_overlay,
        sounds=_sounds,
        autostart=SimpleNamespace(is_enabled=_autostart.is_enabled,
                                  set_enabled=_autostart.set_enabled),
        integration=SimpleNamespace(
            acquire_single_instance=_integration.acquire_single_instance,
            ensure_launcher_shortcut=_integration.ensure_launcher_shortcut,
            set_dpi_awareness=_integration.set_dpi_awareness,
            is_fullscreen_app_active=_integration.is_fullscreen_app_active,
            prefers_reduced_motion=_integration.prefers_reduced_motion,
            run_on_main=_integration.run_on_main),
    )
