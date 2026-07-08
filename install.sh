#!/usr/bin/env bash
# ============================================================
#  LocalFlow - Setup fuer macOS (EXPERIMENTELL, siehe PORTING.md)
#    bash install.sh
#  Erstellt venv + Dependencies. Der macOS-Port ist ungetestet:
#  kein Overlay (Feedback via Sounds), Permissions siehe unten.
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

echo "== LocalFlow Setup (macOS, experimentell) =="

if ! command -v python3 >/dev/null; then
  echo "Python 3.11+ wird benoetigt (z.B.: brew install python)" >&2
  exit 1
fi
if [ "$(python3 -c 'import sys; print(sys.version_info >= (3, 11))')" != "True" ]; then
  echo "Python 3.11+ wird benoetigt (gefunden: $(python3 --version))" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Erstelle virtuelles Environment..."
  python3 -m venv .venv
fi
echo "Installiere Dependencies..."
.venv/bin/python -m pip install --quiet -r requirements.txt

if command -v ollama >/dev/null; then
  if ! ollama list 2>/dev/null | grep -q "gemma3:4b"; then
    echo "Lade Cleanup-Modell gemma3:4b (~3 GB)..."
    ollama pull gemma3:4b
  fi
else
  echo "Hinweis: Ollama nicht gefunden - AI-Cleanup deaktiviert."
  echo "         Installieren: https://ollama.com/download, dann: ollama pull gemma3:4b"
fi

# ~/Applications/LocalFlow.app erzeugen (lokal gebaut = kein Gatekeeper,
# keine Signatur/Notarisierung noetig) - Start dann per Spotlight.
.venv/bin/python -c "from localflow.platform.darwin.integration import ensure_launcher_shortcut; ensure_launcher_shortcut()" \
  && echo "Launcher erstellt: ~/Applications/LocalFlow.app" \
  || echo "Hinweis: Launcher-Bundle konnte nicht erstellt werden (App laeuft trotzdem)."

cat <<'EOF'

Fertig. Start:
    Spotlight (Cmd+Leertaste) -> "LocalFlow"
  oder mit sichtbaren Logs:
    .venv/bin/python run.py

WICHTIG (macOS-Permissions, beim ersten Start):
  - Mikrofon-Zugriff erlauben
  - Systemeinstellungen -> Datenschutz & Sicherheit -> Bedienungshilfen:
    die App freigeben, die LocalFlow gestartet hat (Terminal beim
    Terminal-Start, LocalFlow/Python beim Spotlight-Start)  [Paste + Hotkeys]
  - ggf. auch unter "Eingabemonitoring"
  - danach die freigegebene App einmal neu starten
Der Port ist EXPERIMENTELL - Details und Status: PORTING.md
EOF
