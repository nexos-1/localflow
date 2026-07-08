#!/usr/bin/env bash
# ============================================================
#  LocalFlow - Deinstallation fuer macOS:  bash uninstall.sh
#  Beendet die App, entfernt LaunchAgent und bietet an:
#  Modell-Caches loeschen, Ordner komplett entfernen.
#  (Alles in einer Funktion: das Skript darf sich selbst loeschen.)
# ============================================================
set -u

main() {
  local root; root="$(cd "$(dirname "$0")" && pwd)"
  echo "== LocalFlow entfernen =="
  echo "Ordner: $root"

  # 1. Laufende Prozesse dieser Installation beenden
  if pgrep -f "$root/run.py" >/dev/null 2>&1; then
    echo "[1] Beende LocalFlow..."
    pkill -f "$root/run.py" || true
    sleep 1
  else
    echo "[1] LocalFlow laeuft nicht."
  fi

  # 2. LaunchAgent (Autostart)
  local plist="$HOME/Library/LaunchAgents/io.github.nexos-1.localflow.plist"
  if [ -f "$plist" ]; then
    echo "[2] Entferne LaunchAgent (Autostart)..."
    launchctl unload "$plist" 2>/dev/null || true
    rm -f "$plist"
  else
    echo "[2] Kein LaunchAgent."
  fi

  # 3. Whisper-Modell-Cache (~1,6 GB, ausserhalb des Ordners)
  local found=0
  for m in "$HOME"/.cache/huggingface/hub/models--*faster-whisper*; do
    [ -d "$m" ] || continue
    found=1
    echo "[3] Whisper-Modell-Cache: $m ($(du -sh "$m" 2>/dev/null | cut -f1))"
    read -r -p "    Loeschen? (laedt bei Neuinstallation neu) [j/N] " a
    case "$a" in j|J|y|Y) rm -rf "$m"; echo "    geloescht." ;; esac
  done
  [ "$found" = 0 ] && echo "[3] Kein Whisper-Modell-Cache gefunden."

  # 4. Ollama-Cleanup-Modell (Ollama selbst bleibt unangetastet)
  if command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | grep -q "gemma3:4b"; then
    read -r -p "[4] Ollama-Modell gemma3:4b loeschen? (NUR wenn sonst ungenutzt) [j/N] " a
    case "$a" in j|J|y|Y) ollama rm gemma3:4b ;; esac
  else
    echo "[4] Ollama-Modell gemma3:4b nicht vorhanden."
  fi

  # 5. Kompletter Ordner (inkl. data/ = Diktat-History!)
  echo ""
  echo "ACHTUNG: $root/data enthaelt deine komplette Diktat-History."
  read -r -p "[5] Ordner KOMPLETT loeschen (App + venv + History)? [j/N] " a
  case "$a" in
    j|J|y|Y)
      cd /tmp
      rm -rf "$root"
      echo "LocalFlow ist deinstalliert."
      ;;
    *)
      echo ""
      echo "Fertig. Zum vollstaendigen Entfernen einfach den Ordner loeschen."
      echo "(Diktat-History: data/localflow.sqlite, falls du sie behalten willst.)"
      ;;
  esac
}

main "$@"
exit 0
