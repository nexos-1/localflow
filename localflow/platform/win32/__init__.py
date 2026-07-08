"""Windows-Backend: buendelt die Win32-Implementierungen hinter den
Vertraegen aus platform/base.py.

Die grossen Win32-Module (hotkey-Hooks, inject, ducking, overlay, sounds)
leben physisch weiterhin unter localflow/ - dieses Paket ist ihr EINZIGER
architektonischer Zugriffspunkt fuer main/web. Ein kuenftiges
darwin-Backend implementiert dieselben Attribute (siehe PORTING.md)."""

from types import SimpleNamespace


def make_backends() -> SimpleNamespace:
    # Imports hier (nicht auf Modulebene), damit `import localflow.platform`
    # auf jedem OS funktioniert und erst die win32-Auswahl Win-Module zieht.
    from ... import hotkey as _hotkey
    from ... import inject as _inject
    from ... import overlay as _overlay
    from ... import sounds as _sounds
    from ...ducking import AudioDucker
    from . import autostart as _autostart
    from . import integration as _integration

    return SimpleNamespace(
        # HotkeyBackend
        make_ptt=lambda combo, controller, swallow_mouse=False: _hotkey.PushToTalk(
            combo, controller, swallow_mouse=swallow_mouse),
        add_hotkey=_hotkey.add_hotkey,
        remove_hotkey=_hotkey.remove_hotkey,
        capture_combo=_hotkey.capture_combo,
        # Injector (Modul erfuellt das Protocol: Konstanten + Funktionen)
        inject=_inject,
        # Ducker
        make_ducker=lambda duck_volume: AudioDucker(duck_volume=duck_volume),
        # OverlayBackend
        make_overlay=_overlay.Overlay,
        # SoundBackend
        sounds=_sounds,
        # AutostartBackend
        autostart=SimpleNamespace(is_enabled=_autostart.is_enabled,
                                  set_enabled=_autostart.set_enabled),
        # AppIntegration
        integration=SimpleNamespace(
            acquire_single_instance=_integration.acquire_single_instance,
            ensure_launcher_shortcut=_integration.ensure_launcher_shortcut,
            set_dpi_awareness=_integration.set_dpi_awareness),
    )
