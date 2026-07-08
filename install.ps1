# LocalFlow Setup - ein Befehl, fertig.
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Erstellt das venv, installiert Dependencies, legt die Start-Menue-
# Verknuepfung an und startet die App. Whisper-Modell (~1,6 GB) laedt beim
# ersten Start automatisch. Ollama + Modell werden geprueft.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "== LocalFlow Setup ==" -ForegroundColor Cyan

# 1. Python finden: erst `python` im PATH, sonst der Windows-Launcher `py -3`
#    (python.org-Installer setzt oft nur den Launcher).
$pyExe = $null; $pyArgs = @()
if (Get-Command python -ErrorAction SilentlyContinue) {
    if ((& python -c "import sys; print(sys.version_info >= (3, 11))") -eq "True") { $pyExe = "python" }
}
if (-not $pyExe -and (Get-Command py -ErrorAction SilentlyContinue)) {
    if ((& py -3 -c "import sys; print(sys.version_info >= (3, 11))") -eq "True") { $pyExe = "py"; $pyArgs = @("-3") }
}
if (-not $pyExe) {
    Write-Host "Python 3.11+ wird benoetigt: https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "(oder install.bat doppelklicken - das installiert Python automatisch)"
    exit 1
}

# 2. venv + Dependencies
if (-not (Test-Path "$root\.venv")) {
    Write-Host "Erstelle virtuelles Environment..."
    & $pyExe @pyArgs -m venv "$root\.venv"
}
Write-Host "Installiere Dependencies..."
& "$root\.venv\Scripts\python.exe" -m pip install --quiet -r "$root\requirements.txt"

# 3. Ollama pruefen (AI-Cleanup; App laeuft auch ohne, dann Rohtext)
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "Hinweis: Ollama nicht gefunden - AI-Cleanup deaktiviert." -ForegroundColor Yellow
    Write-Host "         Installieren: https://ollama.com/download, dann: ollama pull gemma3:4b"
} else {
    $models = & ollama list 2>$null
    if ($models -notmatch "gemma3:4b") {
        Write-Host "Lade Cleanup-Modell gemma3:4b (~3 GB)..."
        & ollama pull gemma3:4b
    }
}

# 4. Start-Menue-Verknuepfung + Sounds/Icon
# Pfad NICHT in den Quelltext interpolieren (ein "'" im Ordnernamen wuerde den
# Rawstring brechen) - stattdessen als sys.argv uebergeben.
$setup = 'import sys; sys.path.insert(0, sys.argv[1]); from localflow.shortcuts import ensure_start_menu_shortcut; from localflow.sounds import ensure_sounds; ensure_start_menu_shortcut(); ensure_sounds(); print("Verknuepfung + Assets ok")'
& "$root\.venv\Scripts\python.exe" -c $setup "$root"

# 5. Starten
Write-Host ""
Write-Host "Fertig. LocalFlow startet jetzt (Tray-Icon unten rechts)." -ForegroundColor Green
Write-Host "Spaeter wieder oeffnen: Win-Taste druecken, 'LocalFlow' tippen."
Start-Process "$root\.venv\Scripts\pythonw.exe" -ArgumentList "`"$root\run.py`""
