"""No-op-Ducker fuer macOS (kein oeffentliches Per-App-Volume-API).

did_mute_sessions=0 schaltet den Muted-Head-Trim in main automatisch ab -
main.py braucht keinerlei Sonderfall. Optionen fuer spaeter (PORTING.md 3.4):
Systemvolume via osascript oder AppleScript-Pause fuer Music/Spotify.
"""


class NoopDucker:
    def __init__(self, duck_volume: float = 0.0):
        self.duck_volume = duck_volume
        self.is_muted = False
        self.mute_complete_ts = 0.0
        self.did_mute_sessions = 0

    def duck(self):
        pass

    def restore(self):
        pass
