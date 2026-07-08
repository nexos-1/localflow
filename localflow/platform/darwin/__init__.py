"""macOS-Backend (EXPERIMENTELL - auf echter Hardware UNGETESTET).

Implementiert dieselbe make_backends()-Flaeche wie platform/win32.
Status (siehe PORTING.md, Phase 3):
- inject (NSPasteboard + Cmd+V via CGEvent), hotkey (pynput), sounds
  (afplay), autostart (LaunchAgent), single instance (flock): Code steht,
  laeuft aber erst nach Verifikation auf einem echten Mac / CI-Runner.
- Overlay: bewusst ein No-op-Platzhalter (NullOverlay) - die animierte
  Pill braucht einen AppKit-NSPanel-Host (Phase 3b, nur auf Hardware
  sinnvoll entwickelbar). Feedback kommt solange ueber die Sounds.
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
    from .overlay import NullOverlay

    return SimpleNamespace(
        make_ptt=lambda combo, controller, swallow_mouse=False: _hotkey.PynputPtt(
            combo, controller, swallow_mouse=swallow_mouse),
        add_hotkey=_hotkey.add_hotkey,
        remove_hotkey=_hotkey.remove_hotkey,
        capture_combo=_hotkey.capture_combo,
        inject=_inject,
        make_ducker=lambda duck_volume: NoopDucker(duck_volume=duck_volume),
        make_overlay=NullOverlay,
        sounds=_sounds,
        autostart=SimpleNamespace(is_enabled=_autostart.is_enabled,
                                  set_enabled=_autostart.set_enabled),
        integration=SimpleNamespace(
            acquire_single_instance=_integration.acquire_single_instance,
            ensure_launcher_shortcut=_integration.ensure_launcher_shortcut,
            set_dpi_awareness=_integration.set_dpi_awareness),
    )
