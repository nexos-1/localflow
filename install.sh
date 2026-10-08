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

# --- AI-Cleanup: eigener llama-server (llama.cpp, Metal) + Gemma 3 4B ---
# Beide Downloads sind auf eine Version gepinnt und per SHA-256 geprueft
# (14-Tage-Regel: b10991 vom 2026-09-15, Modell-Revision vom 2025-05-21).
# LocalFlow startet den Server selbst; Ollama ist nur noch Fallback.
DATA_DIR="${LOCALFLOW_DATA_DIR:-$PWD/data}"
LLAMA_TAG="b10991"
case "$(uname -m)" in
  arm64)  LLAMA_ASSET="llama-$LLAMA_TAG-bin-macos-arm64.tar.gz"
          LLAMA_SHA="8e91ffb9e150d36035272b9b86e915b48c84b4488faae33dcdfe07d33c4c2b3f" ;;
  x86_64) LLAMA_ASSET="llama-$LLAMA_TAG-bin-macos-x64.tar.gz"
          LLAMA_SHA="769b60fc4f828a3389da11039d35512af82acbfb41a2208dbf3b6f4a2ce9ea38" ;;
  *)      LLAMA_ASSET="" ;;
esac
MODEL_REV="d0976223747697cb51e056d85c532013931fe52e"
MODEL_FILE="gemma-3-4b-it-Q4_K_M.gguf"
MODEL_SHA="882e8d2db44dc554fb0ea5077cb7e4bc49e7342a1f0da57901c0802ea21a0863"

verify_sha() {  # verify_sha <datei> <sha256>
  [ "$(shasum -a 256 "$1" | awk '{print $1}')" = "$2" ]
}

LLAMA_OK=0
if [ "${LOCALFLOW_SKIP_LLAMA:-0}" != "1" ] && [ -n "$LLAMA_ASSET" ]; then
  BIN_DIR="$DATA_DIR/llamacpp/bin"
  if [ ! -x "$BIN_DIR/llama-server" ]; then
    echo "Lade llama.cpp $LLAMA_TAG ($LLAMA_ASSET, ~11 MB)..."
    TMP_DIR="$(mktemp -d)"
    curl -fsSL -o "$TMP_DIR/llama.tar.gz" \
      "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_TAG/$LLAMA_ASSET"
    if verify_sha "$TMP_DIR/llama.tar.gz" "$LLAMA_SHA"; then
      mkdir -p "$BIN_DIR"
      tar -xzf "$TMP_DIR/llama.tar.gz" -C "$BIN_DIR" --strip-components 1
    else
      echo "FEHLER: SHA-256 von $LLAMA_ASSET stimmt nicht - verworfen." >&2
    fi
    rm -rf "$TMP_DIR"
  fi
  MODEL_PATH="$DATA_DIR/llamacpp/models/$MODEL_FILE"
  if [ ! -f "$MODEL_PATH" ]; then
    echo "Lade Cleanup-Modell $MODEL_FILE (~2.5 GB)..."
    mkdir -p "$(dirname "$MODEL_PATH")"
    curl -fsSL -o "$MODEL_PATH.part" \
      "https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/$MODEL_REV/$MODEL_FILE"
    if verify_sha "$MODEL_PATH.part" "$MODEL_SHA"; then
      mv "$MODEL_PATH.part" "$MODEL_PATH"
    else
      echo "FEHLER: SHA-256 von $MODEL_FILE stimmt nicht - verworfen." >&2
      rm -f "$MODEL_PATH.part"
    fi
  fi
  if [ -x "$BIN_DIR/llama-server" ] && [ -f "$MODEL_PATH" ]; then
    LLAMA_OK=1
    echo "AI-Cleanup: llama.cpp $LLAMA_TAG + $MODEL_FILE bereit."
  fi
fi

if [ "$LLAMA_OK" != "1" ]; then
  if command -v ollama >/dev/null; then
    if ! ollama list 2>/dev/null | grep -q "gemma3:4b"; then
      echo "Lade Cleanup-Modell gemma3:4b fuer Ollama (~3 GB)..."
      ollama pull gemma3:4b
    fi
  else
    echo "Hinweis: weder llama.cpp noch Ollama verfuegbar - AI-Cleanup deaktiviert."
  fi
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
