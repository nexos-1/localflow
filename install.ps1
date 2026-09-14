# LocalFlow Setup - ein Befehl, fertig.
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Erstellt das venv, installiert Dependencies, legt die Start-Menue-
# Verknuepfung an und startet die App. Whisper-Modell (~1,6 GB) laedt beim
# ersten Start automatisch. Ollama + Modell werden geprueft.

param([ValidateSet('de', 'en')][string]$UiLanguage)

$ErrorActionPreference = "Stop"
if (-not $UiLanguage) {
    $choice = Read-Host 'Oberflaeche / Interface: Deutsch [de] or English [en] (Enter = keep existing / Deutsch)'
    if ($choice -in @('de', 'en')) { $UiLanguage = $choice }
    elseif ($choice) { throw 'Please choose de or en.' }
}
if ($UiLanguage) { $UiLanguage = $UiLanguage.ToLowerInvariant() }
function Ui($de, $en) {
    if ($UiLanguage -eq 'en') { $en } else { $de }
}
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
    Write-Host (Ui "Python 3.11+ wird benoetigt: https://www.python.org/downloads/" "Python 3.11 or later is required: https://www.python.org/downloads/") -ForegroundColor Red
    Write-Host (Ui "(oder install.bat doppelklicken - das installiert Python automatisch)" "(or double-click install.bat to install Python automatically)")
    exit 1
}

# 2. venv + Dependencies
if (-not (Test-Path "$root\.venv")) {
    Write-Host (Ui "Erstelle virtuelles Environment..." "Creating the Python environment...")
    & $pyExe @pyArgs -m venv "$root\.venv"
}
Write-Host (Ui "Installiere Dependencies..." "Installing required packages...")
& "$root\.venv\Scripts\python.exe" -m pip install --quiet -r "$root\requirements.txt"

# 3. Ollama pruefen (AI-Cleanup; App laeuft auch ohne, dann Rohtext)
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host (Ui "Hinweis: Ollama nicht gefunden - AI-Cleanup deaktiviert." "Note: Ollama was not found - AI cleanup is unavailable.") -ForegroundColor Yellow
    Write-Host (Ui "         Installieren: https://ollama.com/download, dann: ollama pull gemma3:4b" "         Install it from https://ollama.com/download, then run: ollama pull gemma3:4b")
} else {
    $models = & ollama list 2>$null
    if ($models -notmatch "gemma3:4b") {
        Write-Host (Ui "Lade Cleanup-Modell gemma3:4b (~3 GB)..." "Downloading the cleanup model gemma3:4b (~3 GB)...")
        & ollama pull gemma3:4b
    }
}

# 4. Start-Menue-Verknuepfung + Sounds/Icon
# Pfad NICHT in den Quelltext interpolieren (ein "'" im Ordnernamen wuerde den
# Rawstring brechen) - stattdessen als sys.argv uebergeben.
$setup = 'import sys; sys.path.insert(0, sys.argv[1]); from localflow.shortcuts import ensure_start_menu_shortcut; from localflow.sounds import ensure_sounds; ensure_start_menu_shortcut(); ensure_sounds()'
& "$root\.venv\Scripts\python.exe" -c $setup "$root"
Write-Host (Ui "Verknuepfung + Assets ok" "Shortcut and app assets ready")

# Persist the explicit choice; a blank answer preserves existing settings.
if ($UiLanguage) {
    $configure = 'import sys; sys.path.insert(0, sys.argv[1]); from localflow.settings import Settings; Settings().set("ui_language", sys.argv[2])'
    $configure | & "$root\.venv\Scripts\python.exe" - "$root" $UiLanguage
    if ($LASTEXITCODE -ne 0) { throw 'Could not save interface language.' }
}

# 5. Starten
Write-Host ""
Write-Host (Ui "Fertig. LocalFlow startet jetzt (Tray-Icon unten rechts)." "Setup finished. LocalFlow is starting (tray icon at the bottom right).") -ForegroundColor Green
Write-Host (Ui "Spaeter wieder oeffnen: Win-Taste druecken, 'LocalFlow' tippen." "To reopen: press the Windows key and type 'LocalFlow'.")
Start-Process "$root\.venv\Scripts\pythonw.exe" -ArgumentList "`"$root\run.py`""
